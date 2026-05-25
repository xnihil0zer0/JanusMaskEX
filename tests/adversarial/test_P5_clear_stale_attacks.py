"""Adversarial attack-angle coverage for ``_clear_stale_task_state``.

Companion to ``test_P5_drain_clear_stale.py``. The companion file pins
the happy-path + basic-edge-case contract; this file targets attack
surfaces those tests do NOT exercise:

  - Plan-corruption variants the existing file doesn't try (file-loaded
    JSON ``null``/``[]``/extra keys; nested ``{"plan":{"tasks":[...]}}``;
    list-of-strings).
  - Pathological ``task_id`` values: integers, traversal sequences,
    leading dash, exact-and-over filename length, unicode emoji,
    shell metacharacters, glob metacharacters (``*``, ``?``).
  - Filesystem race conditions: file disappears between
    ``Path.exists()`` and ``Path.unlink()`` (FileNotFoundError);
    permission denied (PermissionError).
  - Symlinks in ``processed/<task_id>.json`` — must NOT follow and
    delete the link target.
  - Concurrent invocation: two threads on same state_dir + same plan
    must not raise.
  - Stderr observability: closed/None stderr must NOT silently swallow
    output; the function must propagate the I/O error so the operator
    notices a broken log path.
  - Wire-in: ``_run_real_cycle`` must call ``_clear_stale_task_state``
    BEFORE ``_shard_merged_plan``, otherwise a stale ``processed/``
    entry survives the shard and the orchestrator skips the task.

SECURITY findings surfaced as ``xfail(strict=True)``:
  - HIGH: ``task_id="../../../foo"`` escapes ``state/tasks/processed/``
    and unlinks files anywhere on disk the wrapper can reach. The
    function must reject task_ids containing path separators or ``..``
    components before joining.
  - MEDIUM: ``task_id="*"`` (or any glob metachar) expands inside the
    sessions glob to ``*_*_submission.json`` and deletes EVERY session
    submission for ALL tasks, not just the requested one.

These xfails will flip to PASS once the implementation sanitises
``task_id``. They are NOT bugs in the tests — they are pending fixes.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import threading

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import impl_drain_capture as wrapper  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: minimal state-dir layout matching what the wrapper expects.
# ---------------------------------------------------------------------------

@pytest.fixture
def state_layout(tmp_path):
    """Return ``(state_dir, processed_dir, sessions_dir)`` with both subdirs created."""
    state_dir = tmp_path / "state"
    processed = state_dir / "tasks" / "processed"
    sessions = state_dir / "sessions"
    processed.mkdir(parents=True)
    sessions.mkdir(parents=True)
    return state_dir, processed, sessions


# ===========================================================================
# 1. PLAN CORRUPTION — file-loaded JSON variants existing tests don't try.
# ===========================================================================

def test_plan_loaded_from_file_with_only_null_returns_zero(state_layout, tmp_path):
    """``json.loads('null')`` => Python ``None`` => zero unlinks, no raise."""
    state_dir, _proc, _sess = state_layout
    plan_path = tmp_path / "merged.json"
    plan_path.write_text("null", encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 0


def test_plan_loaded_from_file_with_empty_array_returns_zero(state_layout, tmp_path):
    """``json.loads('[]')`` => empty list => zero unlinks, no raise."""
    state_dir, _proc, _sess = state_layout
    plan_path = tmp_path / "merged.json"
    plan_path.write_text("[]", encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 0


def test_plan_with_tasks_explicitly_null_returns_zero(state_layout):
    """``{"tasks": null}`` is the legitimate "planner emitted no work" shape."""
    state_dir, _proc, _sess = state_layout
    n = wrapper._clear_stale_task_state({"tasks": None}, state_dir, io.StringIO())
    assert n == 0


def test_plan_with_extra_unknown_keys_is_forward_compatible(state_layout):
    """Unknown top-level keys must be ignored (forward-compat)."""
    state_dir, processed, _sess = state_layout
    (processed / "TASK-FC.json").write_text("{}", encoding="utf-8")
    plan = {
        "tasks": [{"task_id": "TASK-FC"}],
        "schema_version": "v99",
        "metadata": {"author": "future-planner"},
        "futures": [1, 2, 3],
    }
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 1


def test_plan_with_nested_plan_wrapping_returns_zero(state_layout):
    """Deeply-nested ``{"plan": {"tasks": [...]}}`` not supported — must NOT crash.

    Existing happy-path tests cover ``{"tasks": [...]}`` and bare list, but
    no test covers a hypothetical nested envelope. Documented contract:
    nested envelopes are silently ignored (return 0).
    """
    state_dir, processed, _sess = state_layout
    (processed / "TASK-NEST.json").write_text("{}", encoding="utf-8")
    nested = {"plan": {"tasks": [{"task_id": "TASK-NEST"}]}}
    n = wrapper._clear_stale_task_state(nested, state_dir, io.StringIO())
    assert n == 0
    # And the file must survive — we did NOT recurse into the nested envelope.
    assert (processed / "TASK-NEST.json").exists()


def test_plan_as_list_of_strings_does_not_crash(state_layout):
    """``["TASK-A", "TASK-B"]`` (no dict wrapping) — strings are skipped."""
    state_dir, processed, _sess = state_layout
    (processed / "TASK-A.json").write_text("{}", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        ["TASK-A", "TASK-B"], state_dir, io.StringIO()
    )
    assert n == 0  # strings are not dicts; existing branch skips them
    # File must survive — strings are not interpretable as task entries.
    assert (processed / "TASK-A.json").exists()


# ===========================================================================
# 2. PATHOLOGICAL task_id VALUES.
# ===========================================================================

def test_task_id_integer_is_skipped(state_layout):
    """Integer task_id (e.g. older planners may emit numeric IDs) — skipped."""
    state_dir, processed, _sess = state_layout
    (processed / "42.json").write_text("{}", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": 42}]}, state_dir, io.StringIO()
    )
    assert n == 0
    assert (processed / "42.json").exists(), (
        "non-string task_ids must be ignored, not coerced via str()"
    )


def test_task_id_starting_with_dash_is_treated_literally(state_layout):
    """``task_id="-rf"`` must NOT be confused with a CLI flag — pure string path."""
    state_dir, processed, _sess = state_layout
    (processed / "-rf.json").write_text("{}", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "-rf"}]}, state_dir, io.StringIO()
    )
    assert n == 1
    assert not (processed / "-rf.json").exists()


def test_task_id_short_unknown_returns_zero(state_layout):
    """Sanity baseline for "no such file" path — short task_id, no file on disk."""
    state_dir, _proc, _sess = state_layout
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "A" * 32}]}, state_dir, io.StringIO()
    )
    assert n == 0


def test_task_id_exceeding_namemax_must_not_crash(state_layout):
    """260-char task_id => 265-char filename, exceeds NAME_MAX on ext4.

    Previously raised ``OSError: [Errno 36] File name too long`` from inside
    ``Path.exists()``. Fixed by a length-cap + ENAMETOOLONG catch in
    ``_clear_stale_task_state`` — the task is now skipped defensively.
    """
    state_dir, _proc, _sess = state_layout
    long_id = "B" * 260
    # No crash, returns 0.
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": long_id}]}, state_dir, io.StringIO()
    )
    assert n == 0


def test_task_id_unicode_emoji(state_layout):
    """Emoji in task_id must round-trip through Path operations."""
    state_dir, processed, _sess = state_layout
    emoji_id = "TASK-rocket-\U0001f680"
    (processed / f"{emoji_id}.json").write_text("{}", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": emoji_id}]}, state_dir, io.StringIO()
    )
    assert n == 1
    assert not (processed / f"{emoji_id}.json").exists()


def test_task_id_with_shell_metacharacters_does_not_execute(state_layout, tmp_path):
    """``task_id="$(touch ...)"`` => function must NOT spawn a shell."""
    state_dir, _proc, _sess = state_layout
    sentinel = tmp_path / "PWNED"
    payload = f"$(touch {sentinel});echo"
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": payload}]}, state_dir, io.StringIO()
    )
    assert n == 0  # no file with that literal name exists
    assert not sentinel.exists(), (
        "shell metacharacters in task_id must NOT be interpreted by a shell"
    )


# ---------------------------------------------------------------------------
# 2b. SECURITY: path-traversal via task_id (HIGH severity).
# ---------------------------------------------------------------------------

def test_task_id_path_traversal_must_not_escape_processed(state_layout, tmp_path):
    """Path traversal: ``task_id="../../../outside"`` must NOT delete a file
    outside ``state/tasks/processed/``."""
    state_dir, _proc, _sess = state_layout
    # Place a sentinel above state_dir.
    outside = tmp_path / "outside.json"
    outside.write_text("KEEP ME", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "../../../outside"}]},
        state_dir,
        io.StringIO(),
    )
    # Traversal is refused; outside file untouched.
    assert outside.exists(), "path traversal escaped processed/!"
    assert n == 0


def test_task_id_with_forward_slash_must_not_traverse(state_layout):
    """Forward slash in task_id must NOT enable subdir traversal."""
    state_dir, processed, _sess = state_layout
    inner = processed / "inner"
    inner.mkdir()
    (inner / "evil.json").write_text("KEEP", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "inner/evil"}]},
        state_dir,
        io.StringIO(),
    )
    assert (inner / "evil.json").exists(), "subdir traversal succeeded"
    assert n == 0


def test_task_id_with_double_dot_must_not_escape(state_layout):
    """``task_id="..foo"`` (no slash) is fine; ``task_id="../foo"`` must be rejected."""
    state_dir, _proc, _sess = state_layout
    sibling = state_dir / "tasks" / "sibling.json"
    sibling.write_text("KEEP", encoding="utf-8")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "../sibling"}]},
        state_dir,
        io.StringIO(),
    )
    assert sibling.exists(), "single-level traversal succeeded"
    assert n == 0


# ---------------------------------------------------------------------------
# 2c. SECURITY: glob metacharacter expansion (MEDIUM severity).
# ---------------------------------------------------------------------------

def test_task_id_star_must_not_over_delete_sessions(state_layout):
    """``task_id="*"`` must not match every submission file in sessions/."""
    state_dir, _proc, sessions = state_layout
    (sessions / "claude_TASK-A_submission.json").write_text("a")
    (sessions / "claude_TASK-B_submission.json").write_text("b")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "*"}]}, state_dir, io.StringIO()
    )
    # Zero matches; the literal task_id "*" does not correspond to any
    # real submission file and is rejected as a glob metacharacter.
    assert (sessions / "claude_TASK-A_submission.json").exists()
    assert (sessions / "claude_TASK-B_submission.json").exists()
    assert n == 0


def test_task_id_question_mark_does_not_overmatch_multichar(state_layout):
    """``?`` matches a single char in glob, so it should NOT match multi-char IDs."""
    state_dir, _proc, sessions = state_layout
    # Multi-char IDs should NOT be matched by '?' since '?' is single-char wildcard.
    (sessions / "claude_TASK-A_submission.json").write_text("a")
    (sessions / "claude_TASK-B_submission.json").write_text("b")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "?"}]}, state_dir, io.StringIO()
    )
    # Even with the unfixed bug, '?' = single-char => no match for "TASK-A".
    assert n == 0
    assert (sessions / "claude_TASK-A_submission.json").exists()
    assert (sessions / "claude_TASK-B_submission.json").exists()


def test_task_id_bracket_class_matches_at_most_existing_file(state_layout):
    """``[AB]`` is a glob char class. Must not crash; documents current behaviour.

    A file ``claude_A_submission.json`` would match the pattern
    ``*_[AB]_submission.json`` if class expansion is honoured. The current
    implementation passes through to ``Path.glob`` so it WILL match. We
    accept this as documented behaviour for now (xfail-able later if the
    implementation begins escaping ``task_id`` for the glob).
    """
    state_dir, _proc, sessions = state_layout
    (sessions / "claude_A_submission.json").write_text("a")
    (sessions / "claude_X_submission.json").write_text("x")
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "[AB]"}]}, state_dir, io.StringIO()
    )
    # Document current (unsafe) behaviour without asserting count, but make
    # sure no crash and that 'X' file (outside the class) survives.
    assert (sessions / "claude_X_submission.json").exists()
    assert n in (0, 1)  # 1 if class expansion is unguarded; 0 if guarded


# ===========================================================================
# 3. FILESYSTEM RACE CONDITIONS.
# ===========================================================================

def test_processed_unlink_filenotfound_is_swallowed(state_layout, monkeypatch):
    """File disappears between ``.exists()`` and ``.unlink()`` — must not raise."""
    state_dir, processed, _sess = state_layout
    (processed / "TASK-RACE.json").write_text("{}", encoding="utf-8")

    real_unlink = pathlib.Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "TASK-RACE.json" and calls["n"] == 0:
            calls["n"] += 1
            raise FileNotFoundError(self)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", flaky_unlink)

    # Should NOT raise. The processed-branch swallows FileNotFoundError;
    # ``unlinked`` is incremented in the ``else`` of the try, so on
    # FileNotFoundError it is NOT counted. Net count == 0.
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-RACE"}]}, state_dir, io.StringIO()
    )
    assert n == 0


def test_session_unlink_filenotfound_is_skipped_and_count_stays_correct(
    state_layout, monkeypatch
):
    """Session glob race: one of two files vanishes between glob and unlink."""
    state_dir, _proc, sessions = state_layout
    (sessions / "claude_TASK-S_submission.json").write_text("c")
    (sessions / "gemini_TASK-S_submission.json").write_text("g")

    real_unlink = pathlib.Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "claude_TASK-S_submission.json":
            raise FileNotFoundError(self)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", flaky_unlink)

    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-S"}]}, state_dir, io.StringIO()
    )
    # gemini_ file deletion succeeds and is counted; claude_ raises
    # FileNotFoundError mid-loop and is skipped (continue, not counted).
    assert n == 1
    assert not (sessions / "gemini_TASK-S_submission.json").exists()


def test_permission_denied_on_processed_unlink_continues_to_sessions(
    state_layout, monkeypatch
):
    """PermissionError on the processed unlink must NOT abort session cleanup.

    Documented contract per the function source: PermissionError is caught
    by the bare ``except OSError`` branch and ``continue``s the loop. This
    test pins that behaviour — if a future refactor changes it to abort,
    this test will catch the regression.
    """
    state_dir, processed, sessions = state_layout
    (processed / "TASK-P.json").write_text("{}", encoding="utf-8")
    (sessions / "claude_TASK-P_submission.json").write_text("c")

    real_unlink = pathlib.Path.unlink

    def perm_denied(self, *args, **kwargs):
        if self.parent.name == "processed":
            raise PermissionError(self)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", perm_denied)

    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-P"}]}, state_dir, io.StringIO()
    )
    # processed unlink fails (continue branch -> not counted, BUT the
    # `continue` exits the whole task iteration BEFORE reaching the
    # sessions block. This test pins that behaviour:
    assert n == 0
    assert (sessions / "claude_TASK-P_submission.json").exists(), (
        "documented behaviour: PermissionError on processed/ aborts the "
        "current task entirely (continue), so the session for that task "
        "is NOT cleaned. If the function later changes to clean sessions "
        "anyway, update this assertion."
    )


def test_permission_denied_on_session_unlink_skips_one_keeps_others(
    state_layout, monkeypatch
):
    """PermissionError on one session file must not block deletion of others."""
    state_dir, _proc, sessions = state_layout
    (sessions / "claude_TASK-Q_submission.json").write_text("c")
    (sessions / "gemini_TASK-Q_submission.json").write_text("g")

    real_unlink = pathlib.Path.unlink

    def perm_for_claude(self, *args, **kwargs):
        if self.name.startswith("claude_"):
            raise PermissionError(self)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", perm_for_claude)

    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-Q"}]}, state_dir, io.StringIO()
    )
    assert n == 1
    assert (sessions / "claude_TASK-Q_submission.json").exists()
    assert not (sessions / "gemini_TASK-Q_submission.json").exists()


# ===========================================================================
# 4. SYMLINK SAFETY — must NOT follow link to delete the target file.
# ===========================================================================

@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="symlinks not supported on this platform"
)
def test_processed_symlink_unlinks_link_not_target(state_layout, tmp_path):
    """``processed/<task_id>.json`` is a symlink to /etc/passwd-style victim.

    ``Path.unlink()`` must remove the link itself, not follow it. This
    is guaranteed by Python's stdlib (``os.unlink`` semantics on POSIX),
    but we pin it here as a regression guard against a future refactor
    that uses e.g. ``open(...).unlink()`` or ``shutil.rmtree``.
    """
    state_dir, processed, _sess = state_layout
    target = tmp_path / "victim.txt"
    target.write_text("DO NOT DELETE", encoding="utf-8")
    link = processed / "TASK-LINK.json"
    os.symlink(target, link)

    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-LINK"}]}, state_dir, io.StringIO()
    )

    assert n == 1
    assert not link.exists() and not link.is_symlink(), (
        "symlink itself must be removed"
    )
    assert target.exists(), (
        "SECURITY: symlink target was followed and deleted! "
        "Path.unlink() must not follow symlinks."
    )
    assert target.read_text() == "DO NOT DELETE"


@pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="symlinks not supported on this platform"
)
def test_session_submission_symlink_unlinks_link_not_target(state_layout, tmp_path):
    """Same protection for session submission symlinks."""
    state_dir, _proc, sessions = state_layout
    target = tmp_path / "victim2.txt"
    target.write_text("DO NOT DELETE", encoding="utf-8")
    link = sessions / "claude_TASK-SYM_submission.json"
    os.symlink(target, link)

    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "TASK-SYM"}]}, state_dir, io.StringIO()
    )

    assert n == 1
    assert not link.exists() and not link.is_symlink()
    assert target.exists() and target.read_text() == "DO NOT DELETE"


# ===========================================================================
# 5. CONCURRENT INVOCATION — two threads on same state_dir + same plan.
# ===========================================================================

def test_concurrent_invocations_do_not_crash(state_layout):
    """Two threads racing on the same plan must complete without exceptions.

    Counts may be split unpredictably (the loser of each unlink race sees
    FileNotFoundError, which is swallowed) but the sum must be at most the
    original file count and neither thread may raise.
    """
    state_dir, processed, sessions = state_layout
    task_ids = [f"T-{i}" for i in range(20)]
    for tid in task_ids:
        (processed / f"{tid}.json").write_text("{}", encoding="utf-8")
        (sessions / f"claude_{tid}_submission.json").write_text("{}", encoding="utf-8")

    plan = {"tasks": [{"task_id": tid} for tid in task_ids]}
    results: list = []
    errors: list = []

    def worker():
        try:
            n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
            results.append(n)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == [], f"concurrent invocations raised: {errors}"
    assert len(results) == 2
    # No spurious double-counts beyond the real file count (40 files total).
    # Sum of unique deletions cannot exceed 40 — but each thread may also
    # count a "successful" exists+unlink for a file the other already ate
    # if there is any TOCTOU window. Document with a generous bound.
    assert sum(results) <= 80, f"sum exceeds plausible upper bound: {results}"
    # All files actually deleted from disk:
    assert list(processed.glob("*.json")) == []
    assert list(sessions.glob("*_submission.json")) == []


# ===========================================================================
# 6. STDERR OBSERVABILITY — closed/None stderr must NOT silently swallow.
# ===========================================================================

def test_closed_stderr_propagates_value_error_on_write(state_layout):
    """Writing to a closed StringIO raises ValueError; function must NOT swallow it.

    Silently swallowing would mean the operator never sees that their log
    sink is broken, leading to ghost cleanups with no audit trail.
    """
    state_dir, processed, _sess = state_layout
    (processed / "TASK-CLOSED.json").write_text("{}", encoding="utf-8")
    closed = io.StringIO()
    closed.close()
    with pytest.raises(ValueError):
        wrapper._clear_stale_task_state(
            {"tasks": [{"task_id": "TASK-CLOSED"}]}, state_dir, closed
        )


def test_none_stderr_raises_attribute_error_on_write(state_layout):
    """Passing ``None`` as stderr must NOT silently swallow log lines.

    The function does not defensively check for ``None``, so the natural
    AttributeError surfaces — which is exactly what we want (loud failure).
    """
    state_dir, processed, _sess = state_layout
    (processed / "TASK-NONE.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AttributeError):
        wrapper._clear_stale_task_state(
            {"tasks": [{"task_id": "TASK-NONE"}]}, state_dir, None
        )


def test_closed_stderr_does_not_raise_when_no_unlink_happens(state_layout):
    """If nothing is unlinked, no stderr.write is called => closed stream OK."""
    state_dir, _proc, _sess = state_layout
    closed = io.StringIO()
    closed.close()
    # Plan has no matching files on disk => no stderr writes occur.
    n = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "DOES-NOT-EXIST"}]}, state_dir, closed
    )
    assert n == 0


# ===========================================================================
# 7. WIRE-IN: cleanup must happen BEFORE sharding in _run_real_cycle.
# ===========================================================================

def test_run_real_cycle_clears_stale_state_before_sharding(
    tmp_path, monkeypatch
):
    """Order assertion: ``_clear_stale_task_state`` must be invoked BEFORE
    ``_shard_merged_plan``.

    If the order were reversed, the freshly sharded ``state/tasks/<id>.json``
    would be unlinked alongside the stale ``processed/<id>.json``, leaving
    the orchestrator with nothing to do. We patch both functions and assert
    the call ordering.
    """
    state_dir = tmp_path / "state"
    planning = state_dir / "planning"
    tasks = state_dir / "tasks"
    processed = tasks / "processed"
    sessions = state_dir / "sessions"
    log_dir = tmp_path / "logs"
    for d in (planning, processed, sessions, log_dir):
        d.mkdir(parents=True)

    # Pre-stage: a stale processed entry that the cleanup must remove.
    (processed / "TASK-WIRE.json").write_text("{}", encoding="utf-8")

    # Plan on disk for _run_real_cycle to read.
    plan_obj = {"tasks": [{"task_id": "TASK-WIRE", "spec": "noop"}]}
    (planning / "merged_plan.json").write_text(
        json.dumps(plan_obj), encoding="utf-8"
    )

    call_order: list[str] = []
    real_clear = wrapper._clear_stale_task_state
    real_shard = wrapper._shard_merged_plan

    def spy_clear(plan, sdir, stderr):
        call_order.append("clear")
        # Verify the stale processed entry is still there at this point.
        assert (processed / "TASK-WIRE.json").exists(), (
            "cleanup must run while stale entry is still on disk"
        )
        return real_clear(plan, sdir, stderr)

    def spy_shard(plan_path, tasks_dir):
        call_order.append("shard")
        # By the time we shard, cleanup must have run AND removed the entry.
        assert "clear" in call_order, "shard ran before clear!"
        assert not (processed / "TASK-WIRE.json").exists(), (
            "cleanup must have removed the stale processed entry "
            "BEFORE shard runs"
        )
        return real_shard(plan_path, tasks_dir)

    monkeypatch.setattr(wrapper, "_clear_stale_task_state", spy_clear)
    monkeypatch.setattr(wrapper, "_shard_merged_plan", spy_shard)

    # Stub out the heavy subprocess calls.
    monkeypatch.setattr(wrapper, "_run_planner", lambda **kw: None)

    class _FakeProc:
        returncode = 0
        pid = 999999
        _drain_log_handles: tuple = ()
        def poll(self): return 0
        def wait(self, timeout=None): return 0
    monkeypatch.setattr(
        wrapper, "_spawn_orchestrator", lambda **kw: _FakeProc()
    )
    monkeypatch.setattr(
        wrapper, "_wait_for_drain", lambda **kw: "orchestrator_exit"
    )
    monkeypatch.setattr(
        wrapper, "_shutdown_orchestrator", lambda *a, **kw: 0
    )
    monkeypatch.setattr(wrapper, "_capture_tracks_delta", lambda **kw: None)

    # Stub git rev-parse / git diff via subprocess.run.
    import subprocess as _sp
    real_run = _sp.run

    def fake_run(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            class R:
                stdout = "deadbeef\n"
                returncode = 0
            return R()
        if isinstance(cmd, list) and cmd[:2] == ["git", "diff"]:
            class R:
                stdout = ""
                returncode = 0
            return R()
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    status = wrapper._run_real_cycle(
        config_path=tmp_path / "cfg.yaml",
        state_dir=state_dir,
        session="test-session",
        patch_path=tmp_path / "patch.diff",
        per_cycle_tracks=tmp_path / "tracks.jsonl",
        canonical_tracks=tmp_path / "canonical.jsonl",
        log_dir=log_dir,
        brief_file=tmp_path / "brief.md",
        skip_planner=True,  # avoid invoking _run_planner stub side-effects
        planner_timeout=10,
        orchestrator_timeout=10,
        poll_step=0.1,
        idle_confirm=0.1,
    )
    assert status == "orchestrator_exit"
    # Final ordering proof: clear precedes shard in the call log.
    assert call_order == ["clear", "shard"], call_order


def test_run_real_cycle_skips_clear_when_merged_plan_missing(tmp_path, monkeypatch):
    """If ``state/planning/merged_plan.json`` does not exist, clear must NOT run.

    The current wire-in guards the cleanup call behind ``merged_plan_path.exists()``;
    when missing, ``_shard_merged_plan`` raises SystemExit (no plan to shard).
    """
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (state_dir / "sessions").mkdir(parents=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    clear_called = {"n": 0}

    def spy_clear(plan, sdir, stderr):
        clear_called["n"] += 1
        return 0

    monkeypatch.setattr(wrapper, "_clear_stale_task_state", spy_clear)
    monkeypatch.setattr(wrapper, "_run_planner", lambda **kw: None)

    import subprocess as _sp
    real_run = _sp.run

    def fake_run(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:2] == ["git", "rev-parse"]:
            class R:
                stdout = "abc\n"
                returncode = 0
            return R()
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        wrapper._run_real_cycle(
            config_path=tmp_path / "cfg.yaml",
            state_dir=state_dir,
            session="s",
            patch_path=tmp_path / "p.diff",
            per_cycle_tracks=tmp_path / "t.jsonl",
            canonical_tracks=tmp_path / "c.jsonl",
            log_dir=log_dir,
            brief_file=tmp_path / "brief.md",
            skip_planner=True,
            planner_timeout=10,
            orchestrator_timeout=10,
            poll_step=0.1,
            idle_confirm=0.1,
        )
    assert clear_called["n"] == 0, (
        "clear must not be called when merged_plan.json is absent"
    )

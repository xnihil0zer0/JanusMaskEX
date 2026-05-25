"""Boundary, ordering, and normalization attacks against the P5
scope_exception/scope_revoke machinery in scripts/impl_pre_write.py.

These tests exercise the in-process helpers
``_read_scope_revokes`` and ``_effective_scope_exception_paths`` directly
(fast, deterministic) AND drive the full ``impl_pre_write.py`` gate as a
subprocess for the integration cases (matching the existing project test
pattern). Each test seeds its own ledger from scratch under ``tmp_path``.

xfail markers document confirmed behaviour gaps that callers should know
about (path canonicalisation, wildcard cancellation, paths-as-string).
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


# Load impl_pre_write as a module so we can exercise the helpers directly.
def _load_impl_pre_write():
    spec = importlib.util.spec_from_file_location(
        "impl_pre_write_under_test", SCRIPTS / "impl_pre_write.py"
    )
    module = importlib.util.module_from_spec(spec)
    # impl_pre_write inserts SCRIPTS on sys.path itself when imported.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


IPW = _load_impl_pre_write()


# ----------------------------------------------------------------- helpers


def _ts(offset_seconds: int = 0) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=offset_seconds
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filler(i: int = 0) -> dict:
    return {
        "ts": _ts(-3600 + i),
        "phase": "META",
        "task_id": "META-00-install-hooks",
        "event": "write",
        "detail": f"filler-{i}",
        "files": [],
        "exit": 0,
    }


def _exc(paths: list[str], ts_offset: int = -120, task: str = "META-00-install-hooks") -> dict:
    return {
        "ts": _ts(ts_offset),
        "phase": "META",
        "task_id": task,
        "event": "scope_exception",
        "detail": f"open {paths}",
        "paths": list(paths),
        "approved_by": "test",
        "files": [],
        "exit": 0,
    }


def _rev(paths: list[str], ts_offset: int = -60) -> dict:
    return {
        "ts": _ts(ts_offset),
        "phase": "META",
        "task_id": "",
        "event": "scope_revoke",
        "detail": f"close {paths}",
        "paths": list(paths),
        "approved_by": "test",
        "files": [],
        "exit": 0,
    }


def _start(task: str = "META-00-install-hooks", phase: str = "META",
           offset_seconds: int = -300) -> dict:
    return {
        "ts": _ts(offset_seconds),
        "phase": phase,
        "task_id": task,
        "event": "start",
        "detail": "",
        "files": [],
        "exit": 0,
    }


def _seed_ledger(tmp_path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r) for r in rows)
    ledger.write_text(body + ("\n" if body else ""), encoding="utf-8")
    return ledger


def _run_gate(stdin_payload: dict, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "impl_pre_write.py")],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _decision(proc: subprocess.CompletedProcess) -> str:
    """Return 'allow' or 'deny' for a gate subprocess result."""
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow"
    payload = json.loads(proc.stdout)
    hso = payload.get("hookSpecificOutput") or {}
    decision = hso.get("permissionDecision", "allow")
    return decision


# =====================================================================
# 1. Window-boundary attacks (the 50-row trailing window)
# =====================================================================


def test_window_boundary_revoke_at_last_row_in_window_cancels():
    """Exception at index N (just inside the last-50 window), revoke at
    index N+49 (still inside) -> revoke MUST cancel."""
    rows = [_exc(["x.py"], ts_offset=-200)]
    rows.extend(_filler(i) for i in range(48))
    rows.append(_rev(["x.py"], ts_offset=-30))
    # Sanity: last 50 should contain both.
    assert len(rows) == 50
    assert IPW._effective_scope_exception_paths(rows) == []


def test_window_boundary_exception_aged_out_revoke_alone_does_nothing():
    """Add one extra filler so the exception falls at index -51 (outside
    the window). The revoke remains in window but has nothing to cancel;
    effective set must be empty (because the exception is no longer scanned)."""
    rows = [_exc(["x.py"], ts_offset=-300)]
    rows.extend(_filler(i) for i in range(49))  # one more filler than above
    rows.append(_rev(["x.py"], ts_offset=-30))
    assert len(rows) == 51
    # exception is at index 0 i.e. position -51, just outside window.
    eff = IPW._effective_scope_exception_paths(rows)
    assert eff == [], f"expected empty effective set, got {eff!r}"
    # Revoke is still visible to _read_scope_revokes (it's at -1).
    revs = IPW._read_scope_revokes(rows)
    assert len(revs) == 1


def test_window_boundary_revoke_just_outside_window_does_not_cancel():
    """Exception at the END of the window, revoke pushed OUTSIDE by adding
    51 fillers AFTER the exception. The exception ages out before the
    revoke even matters."""
    # Order: revoke (oldest), then fillers, then exception (recent).
    # Because the revoke has to be LATER in the window than the exception
    # to cancel, putting the revoke before the exception is a no-op.
    rows = [_rev(["x.py"], ts_offset=-1000)]
    rows.extend(_filler(i) for i in range(60))
    rows.append(_exc(["x.py"], ts_offset=-10))
    eff = IPW._effective_scope_exception_paths(rows)
    assert eff == ["x.py"], f"revoke earlier than exception must NOT cancel: {eff!r}"


def test_window_holds_exactly_50_rows():
    """Exception at index 0, 49 fillers, revoke at index 49.
    All 50 rows == the entire window. Revoke MUST cancel."""
    rows = [_exc(["alpha.py"])]
    rows.extend(_filler(i) for i in range(48))
    rows.append(_rev(["alpha.py"]))
    assert len(rows) == 50
    assert IPW._effective_scope_exception_paths(rows) == []


# =====================================================================
# 2. Reverse-order / interleaved revokes
# =====================================================================


def test_revoke_before_exception_in_ledger_position_is_noop():
    """Even when both share the same ts, a revoke that appears earlier in
    the ledger than the exception must NOT cancel it (the inner loop
    starts at i+1)."""
    same_ts = _ts(-200)
    rows = [
        {"ts": same_ts, "event": "scope_revoke", "paths": ["dup.py"]},
        {"ts": same_ts, "event": "scope_exception", "paths": ["dup.py"]},
    ]
    assert IPW._effective_scope_exception_paths(rows) == ["dup.py"]


def test_interleaved_revoke_then_exception_then_revoke_matches_only_later():
    """revoke(A) -> exception(A) -> revoke(A): only the LATER revoke
    counts; the earlier one is in ledger position before the exception
    and must be skipped. Final effective set should be empty."""
    rows = [
        _rev(["a.py"], ts_offset=-300),
        _exc(["a.py"], ts_offset=-200),
        _rev(["a.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_two_exceptions_then_one_revoke_cancels_both_for_shared_path():
    """Two scope_exception rows, both naming p.py, then one revoke for
    p.py. p.py must be revoked from BOTH exceptions."""
    rows = [
        _exc(["p.py", "q.py"], ts_offset=-300),
        _exc(["p.py", "r.py"], ts_offset=-200),
        _rev(["p.py"], ts_offset=-100),
    ]
    eff = IPW._effective_scope_exception_paths(rows)
    # p.py removed from both exceptions; q.py and r.py remain (in ledger order).
    assert "p.py" not in eff
    assert "q.py" in eff and "r.py" in eff


def test_exception_after_revoke_is_immune_to_that_revoke():
    """exception(A) -> revoke(A) -> exception(A). The revoke cancels the
    FIRST exception's contribution but not the SECOND, because the second
    appears later in ledger and the revoke isn't AFTER it."""
    rows = [
        _exc(["m.py"], ts_offset=-300),
        _rev(["m.py"], ts_offset=-200),
        _exc(["m.py"], ts_offset=-100),
    ]
    eff = IPW._effective_scope_exception_paths(rows)
    # The second exception still counts -> m.py present at least once.
    assert "m.py" in eff


# =====================================================================
# 3. Per-path matching (set algebra)
# =====================================================================


def test_revoke_only_affects_named_paths_other_paths_remain():
    """Exception covers [A, B, C]; revoke covers [B] only. Effective set
    must contain A and C but not B."""
    rows = [
        _exc(["a.py", "b.py", "c.py"], ts_offset=-200),
        _rev(["b.py"], ts_offset=-100),
    ]
    eff = IPW._effective_scope_exception_paths(rows)
    assert sorted(eff) == ["a.py", "c.py"]


def test_revoke_naming_unrelated_path_is_inert():
    """Exception covers [A]; revoke covers [Z] which was never opened.
    A must remain effective; the stray Z is silently ignored."""
    rows = [
        _exc(["only-a.py"], ts_offset=-200),
        _rev(["never-opened-z.py"], ts_offset=-100),
    ]
    eff = IPW._effective_scope_exception_paths(rows)
    assert eff == ["only-a.py"]


def test_revoke_with_mixed_known_and_unknown_paths():
    """Exception covers [B]; revoke covers [B, D]. B is revoked, D is
    a no-op. Effective set must be empty."""
    rows = [
        _exc(["b.py"], ts_offset=-200),
        _rev(["b.py", "d.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


# =====================================================================
# 4. Path canonicalisation -- documents current STRING-EQUALITY behaviour
# =====================================================================


def test_revoke_with_dot_prefix_should_cancel_bare_exception():
    rows = [
        _exc(["harness/foo.py"], ts_offset=-200),
        _rev(["./harness/foo.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_revoke_with_double_slash_should_cancel_canonical_exception():
    rows = [
        _exc(["harness/foo.py"], ts_offset=-200),
        _rev(["harness//foo.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_revoke_with_embedded_dot_segment_should_cancel():
    rows = [
        _exc(["harness/foo.py"], ts_offset=-200),
        _rev(["harness/./foo.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_exact_path_match_cancels_as_expected():
    """Control: exact byte-for-byte match must cancel."""
    rows = [
        _exc(["harness/foo.py"], ts_offset=-200),
        _rev(["harness/foo.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


# =====================================================================
# 5. Same-row ts ordering (ts-tie -> ledger position wins)
# =====================================================================


def test_same_ts_revoke_after_exception_wins_via_ledger_position():
    """Two rows with identical ts; the one appearing LATER in the ledger
    is treated as 'at least as new' per the docstring. Revoke after
    exception must cancel."""
    same = _ts(-100)
    rows = [
        {"ts": same, "event": "scope_exception", "paths": ["tie.py"]},
        {"ts": same, "event": "scope_revoke", "paths": ["tie.py"]},
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


# =====================================================================
# 6. Malformed / hostile rows
# =====================================================================


def test_row_missing_event_key_is_ignored():
    rows = [
        {"ts": _ts(-200), "paths": ["nope.py"]},  # no event
        _exc(["good.py"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == ["good.py"]


def test_exception_row_missing_paths_key_yields_nothing():
    rows = [{"ts": _ts(-100), "event": "scope_exception"}]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_exception_row_with_empty_paths_list_yields_nothing():
    rows = [{"ts": _ts(-100), "event": "scope_exception", "paths": []}]
    assert IPW._effective_scope_exception_paths(rows) == []


def test_revoke_row_missing_paths_key_does_not_cancel():
    rows = [
        _exc(["keep.py"], ts_offset=-200),
        {"ts": _ts(-100), "event": "scope_revoke"},  # no paths
    ]
    assert IPW._effective_scope_exception_paths(rows) == ["keep.py"]


def test_paths_as_string_should_be_ignored_or_coerced_not_iterated_as_chars():
    """Hostile producer writes paths='foo.py' instead of paths=['foo.py'].
    Today the code emits ['f','o','o','.','p','y']. Either coerce or skip;
    do NOT splat characters."""
    rows = [{"ts": _ts(-100), "event": "scope_exception", "paths": "foo.py"}]
    eff = IPW._effective_scope_exception_paths(rows)
    # Acceptable behaviours: either treat as the single-element list, OR
    # ignore. NOT acceptable: per-character splat.
    assert eff in ([], ["foo.py"]), f"got per-char splat: {eff!r}"


def test_completely_empty_row_is_ignored():
    rows = [{}]
    assert IPW._effective_scope_exception_paths(rows) == []
    assert IPW._read_scope_revokes(rows) == []


# =====================================================================
# 7. Empty / missing ledger
# =====================================================================


def test_empty_ledger_returns_empty_lists():
    assert IPW._effective_scope_exception_paths([]) == []
    assert IPW._read_scope_revokes([]) == []


def test_ledger_file_missing_yields_empty_via_load_ledger(tmp_path):
    """When the ledger file is absent, load_ledger returns []; the helpers
    must therefore return [] (no crash)."""
    from impl_common import load_ledger
    missing = tmp_path / "state" / "does_not_exist.jsonl"
    rows = load_ledger(missing)
    assert rows == []
    assert IPW._effective_scope_exception_paths(rows) == []


def test_ledger_with_only_blank_lines_yields_empty(tmp_path):
    from impl_common import load_ledger
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("\n\n   \n\n", encoding="utf-8")
    rows = load_ledger(ledger)
    assert rows == []


# =====================================================================
# 8. Performance on large ledgers
# =====================================================================


def test_effective_paths_on_100k_row_ledger_is_fast():
    """The trailing-window slice (`ledger[-50:]`) must keep this O(50)
    regardless of total ledger size. Should easily complete in <100ms."""
    rows = [_filler(i) for i in range(100_000)]
    rows[-25] = _exc(["big.py"], ts_offset=-100)
    rows[-3] = _rev(["big.py"], ts_offset=-50)
    t0 = time.perf_counter()
    out = IPW._effective_scope_exception_paths(rows)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert out == [], "100k-row revoke must still cancel"
    assert elapsed_ms < 100, f"slow scan: {elapsed_ms:.2f}ms"


def test_read_revokes_on_100k_row_ledger_is_fast():
    rows = [_filler(i) for i in range(100_000)]
    rows[-3] = _rev(["big.py"], ts_offset=-50)
    t0 = time.perf_counter()
    out = IPW._read_scope_revokes(rows)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(out) == 1
    assert elapsed_ms < 100, f"slow scan: {elapsed_ms:.2f}ms"


# =====================================================================
# 9. Concurrent ledger writes (load_ledger robustness)
# =====================================================================


def test_load_ledger_tolerates_partial_trailing_line(tmp_path):
    """Another process appended a row but didn't flush the trailing
    newline before we read. load_ledger must not raise; the partial JSON
    line should be skipped (it's not valid JSON)."""
    from impl_common import load_ledger
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(_exc(["good.py"])) + "\n"
    body += '{"ts": "2026-04-19T0'  # truncated mid-line, no newline
    ledger.write_text(body, encoding="utf-8")
    rows = load_ledger(ledger)
    # Good row preserved; partial row dropped; no exception.
    assert len(rows) == 1
    assert rows[0]["event"] == "scope_exception"


def test_load_ledger_under_concurrent_appends_does_not_crash(tmp_path):
    """Spin a writer thread that keeps appending complete rows while we
    repeatedly read. load_ledger must never raise."""
    from impl_common import load_ledger
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("", encoding="utf-8")

    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            with ledger.open("a", encoding="utf-8") as f:
                f.write(json.dumps(_filler(i)) + "\n")
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(200):
            rows = load_ledger(ledger)
            # Every loaded row should be a dict (no malformed half-rows).
            assert all(isinstance(r, dict) for r in rows)
    finally:
        stop.set()
        t.join(timeout=5)


# =====================================================================
# 10. Wildcard exception + specific revoke (current STRING semantics)
# =====================================================================


def test_specific_file_revoke_should_punch_hole_in_wildcard_exception():
    rows = [
        _exc(["tests/adversarial/**"], ts_offset=-200),
        _rev(["tests/adversarial/foo.py"], ts_offset=-100),
    ]
    eff = IPW._effective_scope_exception_paths(rows)
    # Desired: wildcard remains for everything else, but foo.py is closed.
    # We approximate by requiring the wildcard NOT to cover foo.py.
    from impl_common import _glob_match
    assert not any(_glob_match("tests/adversarial/foo.py", p) for p in eff)


def test_wildcard_exception_with_exact_wildcard_revoke_cancels():
    """If both rows name the SAME wildcard string, equality holds and
    cancellation works (string-level). Control test for the gap above."""
    rows = [
        _exc(["tests/adversarial/**"], ts_offset=-200),
        _rev(["tests/adversarial/**"], ts_offset=-100),
    ]
    assert IPW._effective_scope_exception_paths(rows) == []


# =====================================================================
# 11. Gate-1 integration via subprocess
# =====================================================================


def test_gate1_blocks_write_against_revoked_exception_path(tmp_path):
    """End-to-end: an exception+revoke pair for foo/bar.py (out-of-phase
    for META) must cause the pre-write gate to deny."""
    rows = [
        _start("META-00-install-hooks", "META", offset_seconds=-300),
        _exc(["foo/bar.py"], ts_offset=-200),
        _rev(["foo/bar.py"], ts_offset=-100),
    ]
    _seed_ledger(tmp_path, rows)
    proc = _run_gate(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "foo" / "bar.py"),
                "content": "x = 1\n",
            },
        },
        tmp_path,
    )
    assert _decision(proc) == "deny", proc.stdout


def test_gate1_allows_write_against_active_non_revoked_exception(tmp_path):
    """Control: exception with NO matching revoke must let the write
    through (path is otherwise out-of-phase for META)."""
    rows = [
        _start("META-00-install-hooks", "META", offset_seconds=-300),
        _exc(["foo/baz.py"], ts_offset=-100),
    ]
    _seed_ledger(tmp_path, rows)
    proc = _run_gate(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "foo" / "baz.py"),
                "content": "y = 2\n",
            },
        },
        tmp_path,
    )
    assert _decision(proc) != "deny", proc.stdout


def test_gate1_partial_revoke_blocks_only_named_path_via_subprocess(tmp_path):
    """Exception covers [foo/x.py, foo/y.py]; revoke covers [foo/x.py].
    Subprocess must deny x.py and allow y.py."""
    rows = [
        _start("META-00-install-hooks", "META", offset_seconds=-300),
        _exc(["foo/x.py", "foo/y.py"], ts_offset=-200),
        _rev(["foo/x.py"], ts_offset=-100),
    ]
    _seed_ledger(tmp_path, rows)

    proc_x = _run_gate(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "foo" / "x.py"),
                "content": "a = 1\n",
            },
        },
        tmp_path,
    )
    assert _decision(proc_x) == "deny", proc_x.stdout

    proc_y = _run_gate(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "foo" / "y.py"),
                "content": "b = 2\n",
            },
        },
        tmp_path,
    )
    assert _decision(proc_y) != "deny", proc_y.stdout

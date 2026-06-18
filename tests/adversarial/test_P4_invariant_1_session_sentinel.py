"""P4 corrections M13 — session-sentinel invariant 1 (sub-plan 03 §Proposed 4).

Plan §4 invariant 1 states: once ``session_start`` has fired, the
session_id must remain stable across every subsequent hook in the same
round.  The in-repo ledger lives at
``state/sessions/{agent}_{session_id}.ledger.jsonl`` — the filename
itself is the stable sentinel that binds all follow-up hooks to the
same identity.  The existing invariant-1 test at
``tests/hooks/invariants/test_nine_invariants.py:76-93`` only asserts
that rows appended by ``_ledger.append_hook_event`` carry a consistent
``session_id`` field — a weaker proxy that would NOT catch a
regression where two different hooks wrote to two differently-named
ledger files (and both still contained the same ``session_id`` value).

This test is stronger: it drives the real hook entrypoints end-to-end,
asserts the sentinel ledger path is created by ``session_start``, and
asserts a follow-up ``user_prompt_submit`` invocation BINDS TO THE
SAME sentinel — i.e. the same file gets appended to, keyed by the
same session_id, with the ``session_start`` row still present at the
top.  A mutation that let either hook invent its own session_id would
surface as a missing row or a divergent filename.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.hooks import _ledger  # noqa: E402
from harness.hooks.claude import (  # noqa: E402
    session_start as session_start_mod,
    user_prompt_submit as ups_mod,
)


_STABLE_SESSION_ID = "SESS-INV1-SENTINEL-ABC123"


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    """Stage the minimal env + workdir skeleton the real hooks need.

    Returns (state_dir, work_dir) — callers derive the sentinel path
    themselves so an assertion failure points at the exact filename.
    """
    state = tmp_path / "state"
    (state / "sessions").mkdir(parents=True)
    workdir = state / "workdirs" / "claude" / _STABLE_SESSION_ID
    inbox = workdir / "inbox"
    outbox = workdir / "outbox"
    inbox.mkdir(parents=True)
    outbox.mkdir(parents=True)
    (inbox / "task.json").write_text(
        json.dumps({"task_id": "T1", "specification": "Write add(a,b)."}),
        encoding="utf-8",
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 2, "phase": "synthesis", "task_id": "T1"}),
        encoding="utf-8",
    )

    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "2")

    return state, workdir


def _run_hook(main_fn, payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    main_fn(stdin, stdout)
    # Hook stdout always carries a single JSON object.
    return json.loads(stdout.getvalue())


# ---------------------------------------------------------------------------
# (a) session_start writes the sentinel ledger file keyed by session_id.
# ---------------------------------------------------------------------------


def test_session_start_writes_session_sentinel(session_env):
    state, _workdir = session_env
    sentinel = state / "sessions" / f"claude_{_STABLE_SESSION_ID}.ledger.jsonl"
    assert not sentinel.exists()  # clean start

    resp = _run_hook(
        session_start_mod.main,
        {"session_id": _STABLE_SESSION_ID, "source": "startup"},
    )
    assert resp["continue"] is True
    assert sentinel.is_file(), (
        f"session_start must create the per-session ledger sentinel at "
        f"{sentinel}. A session_id that never reaches _ledger breaks "
        f"invariant 1 at the filename layer."
    )
    rows = [
        json.loads(line)
        for line in sentinel.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows, "sentinel is empty; session_start did not append a row"
    assert rows[0]["verb"] == "session_start"
    assert rows[0]["session_id"] == _STABLE_SESSION_ID


# ---------------------------------------------------------------------------
# (b + c) A second hook reads the SAME sentinel and appends to it —
# proving it picked up the session_id session_start just stamped.
# ---------------------------------------------------------------------------


def test_user_prompt_submit_binds_to_same_session_sentinel(session_env):
    state, _workdir = session_env
    sentinel = state / "sessions" / f"claude_{_STABLE_SESSION_ID}.ledger.jsonl"

    # (a) seed via session_start.
    _run_hook(
        session_start_mod.main,
        {"session_id": _STABLE_SESSION_ID, "source": "startup"},
    )
    pre_rows = [
        json.loads(l)
        for l in sentinel.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert {r["verb"] for r in pre_rows} == {"session_start"}

    # (b) a second hook runs under the same session_id.
    resp = _run_hook(
        ups_mod.main,
        {
            "session_id": _STABLE_SESSION_ID,
            "prompt": "First user turn.",
        },
    )
    assert resp["decision"] == "allow"

    # (c) the same sentinel file received new rows, keyed by the same
    # session_id.  No second sentinel file should have been created.
    post_rows = [
        json.loads(l)
        for l in sentinel.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert len(post_rows) > len(pre_rows), (
        "user_prompt_submit did not append to the existing sentinel — "
        "the follow-up hook ignored session_start's session_id."
    )
    assert all(r["session_id"] == _STABLE_SESSION_ID for r in post_rows), (
        "session_id drift across hooks on the same sentinel file. "
        f"Got: {sorted({r['session_id'] for r in post_rows})}"
    )
    # Nobody else created a sibling ledger under a different session_id.
    others = [
        p for p in (state / "sessions").iterdir()
        if p.is_file() and p.name != sentinel.name and p.suffix != ".lock"
    ]
    assert not others, (
        f"extra sentinel files appeared: {[p.name for p in others]}. "
        f"A follow-up hook invented its own session_id."
    )
    # A task_read row must now exist (UserPromptSubmit§(1) injects the
    # task on first prompt).  This proves the hook actually *read* the
    # sentinel — has_verb returning False would have triggered a repeat
    # inject, but because the sentinel is keyed correctly the task_read
    # marker lands on the SAME file.
    assert any(r["verb"] == "task_read" for r in post_rows)


# ---------------------------------------------------------------------------
# Mutation: if a follow-up hook is given a *different* session_id, it
# writes to a different sentinel — the cross-file invariant breaks.
# Confirms the positive test is discriminating.
# ---------------------------------------------------------------------------


def test_mutation_divergent_session_id_splits_sentinel(session_env):
    state, _workdir = session_env
    sentinel = state / "sessions" / f"claude_{_STABLE_SESSION_ID}.ledger.jsonl"

    _run_hook(
        session_start_mod.main,
        {"session_id": _STABLE_SESSION_ID, "source": "startup"},
    )
    assert sentinel.is_file()

    # Simulate the mutation: second hook receives a different session_id.
    rogue = "SESS-ROGUE-DEF456"
    _run_hook(
        ups_mod.main,
        {"session_id": rogue, "prompt": "rogue turn"},
    )
    rogue_path = state / "sessions" / f"claude_{rogue}.ledger.jsonl"
    assert rogue_path.is_file(), (
        "The rogue session_id should have produced a DIFFERENT "
        "sentinel file. If the positive test's 'no sibling files' "
        "assertion ever stops failing here, it is no longer "
        "discriminating."
    )
    # And the original sentinel did NOT get the follow-up rows.
    rows = [
        json.loads(l)
        for l in sentinel.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert [r["verb"] for r in rows] == ["session_start"]


# ---------------------------------------------------------------------------
# Crosscheck: _ledger.ledger_path() on the same agent + session_id
# resolves to the same on-disk file the hook wrote — i.e. the sentinel
# path contract is consistent across reader and writer call-sites.
# ---------------------------------------------------------------------------


def test_ledger_path_matches_session_start_sentinel(session_env):
    state, _ = session_env
    _run_hook(
        session_start_mod.main,
        {"session_id": _STABLE_SESSION_ID, "source": "startup"},
    )
    expected = state / "sessions" / f"claude_{_STABLE_SESSION_ID}.ledger.jsonl"
    resolved = _ledger.ledger_path(_STABLE_SESSION_ID, "claude")
    assert resolved == expected, (
        f"ledger_path contract drift: writer produced {expected}, "
        f"_ledger.ledger_path resolves to {resolved}."
    )
    assert resolved.is_file()

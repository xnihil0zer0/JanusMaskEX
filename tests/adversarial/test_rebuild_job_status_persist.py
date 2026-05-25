"""B3 (session #37) contract: job_status(persist=False) is read-only.

A manual / monitoring status read MUST NOT flip the persisted job ``status`` to
'complete'. The daemon's ``_watch_rebuild_jobs`` emits ``rebuild_complete``
exactly once, guarded by the persisted status; a status read that pre-flipped it
suppressed that telemetry and hung a ledger-grep monitor. The complete-transition
is owned by the daemon, so read-only callers pass persist=False.
"""
from __future__ import annotations

import json
from pathlib import Path

import harness.rebuild.job as job

_REPO = Path(__file__).resolve().parent.parent.parent


def _state(tmp_path) -> Path:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text(
        "# allowlist\n", encoding="utf-8"
    )
    return sd


def _persisted_status(sd: Path, job_id: str) -> str:
    p = sd / "control" / "rebuild" / "jobs" / f"{job_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))["status"]


def _make_complete_job(tmp_path):
    sd = _state(tmp_path)
    j = job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,
    )
    # fill the output module with the real bodies -> job is now complete
    real = (_REPO / "samples" / "mathlib" / "mathlib.py").read_text(encoding="utf-8")
    (tmp_path / "out" / "mathlib.py").write_text(real, encoding="utf-8")
    return sd, j["job_id"]


def test_persist_false_does_not_flip_persisted_status(tmp_path):
    sd, jid = _make_complete_job(tmp_path)
    assert _persisted_status(sd, jid) == "pending"
    st = job.job_status(sd, jid, persist=False)
    # the RETURNED status reflects completion ...
    assert st["complete"] is True
    assert st["status"] == "complete"
    # ... but the persisted file is untouched (monitor-safe)
    assert _persisted_status(sd, jid) == "pending"


def test_persist_true_flips_persisted_status(tmp_path):
    sd, jid = _make_complete_job(tmp_path)
    assert _persisted_status(sd, jid) == "pending"
    job.job_status(sd, jid, persist=True)
    assert _persisted_status(sd, jid) == "complete"


def test_default_persists_for_backward_compat(tmp_path):
    sd, jid = _make_complete_job(tmp_path)
    job.job_status(sd, jid)
    assert _persisted_status(sd, jid) == "complete"

"""Top-level live entrypoint for a NobleGreedv2 bug-hunt session.

``run_hunt`` opens the session DB, SEEDS a fresh session at the initial ``hunt``
phase (so the conductor's first ``plan_next_action`` has a phase to act on),
assembles the default conductor seams
(:func:`ngv2.conductor_seams.build_default_seams`), and drives
:func:`ngv2.conductor_loop.run_until_terminal` to a terminal FSM state. This is
the single live wiring point that ties the spawn runner, the phase workers, the
gates, and the FSM together.

Spawnable via ``python -m ngv2.run_hunt --session-id ... --repo ... --target
... --db ... --out ...``. The awaiting_submission park step is terminal, so the
loop never auto-submits.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from ngv2.conductor_loop import run_until_terminal
from ngv2.conductor_seams import build_default_seams
from ngv2.session_db import SessionDB

_INITIAL_PHASE = "hunt"


def _ensure_seeded(
    db: Any,
    session_id: str,
    repo: str,
    target_path: str,
    db_path: str = "",
) -> Dict[str, Any]:
    """Seed a brand-new session row at the initial ``hunt`` phase.

    The conductor's ``run_conductor_step`` reads ``state['phase']`` strictly, so
    a fresh (absent or phase-less) session must be initialised before the loop
    runs or step 1 raises ``KeyError: 'phase'``. An EXISTING session that
    already carries a ``phase`` is left untouched (resume / re-entry safe) so
    seeding never clobbers in-progress or terminal state.

    Returns the resulting session state dict.
    """
    row = None
    try:
        row = db.get_session(session_id)
    except Exception:
        row = None
    if isinstance(row, dict) and row.get("phase"):
        return dict(row)
    state: Dict[str, Any] = {
        "session_id": session_id,
        "phase": _INITIAL_PHASE,
        "repo": repo,
        "target": target_path,
        "db_path": db_path,
        "findings": 0,
        "pocs": 0,
        "reports": 0,
        "artifacts": [],
    }
    db.save_session(session_id, state)
    return state


def run_hunt(
    session_id: str,
    repo: str,
    target_path: str,
    db_path: str,
    output_dir: str,
    max_steps: int = 50,
    *,
    llm_client: Any = None,
    db: Any = None,
) -> Dict[str, Any]:
    """Drive a hunt session to a terminal FSM state and return the trace.

    Opens ``db_path`` as a :class:`SessionDB` (unless an explicit ``db`` is
    injected), seeds a fresh session at the ``hunt`` phase, builds the default
    seams over the session context (carrying ``db_path`` so the spawned phase
    workers can re-open the session DB), and runs the conductor loop. Returns
    ``run_until_terminal``'s ``{'steps', 'final_step'}`` dict.
    """
    ctx = {
        "session_id": session_id,
        "repo": repo,
        "target_path": target_path,
        "output_dir": output_dir,
        "db_path": db_path,
        "env": {},
    }
    owns_db = db is None
    if owns_db:
        db = SessionDB(db_path)
    try:
        _ensure_seeded(db, session_id, repo, target_path, db_path)
        seams = build_default_seams(session_id, db, llm_client, ctx)
        return run_until_terminal(session_id, seams, max_steps)
    finally:
        if owns_db:
            db.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ngv2.run_hunt")
    parser.add_argument("--session-id", required=True, dest="session_id")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--target", required=True, dest="target_path")
    parser.add_argument("--db", required=True, dest="db_path")
    parser.add_argument("--out", required=True, dest="output_dir")
    parser.add_argument("--max-steps", type=int, default=50, dest="max_steps")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    result = run_hunt(
        args.session_id,
        args.repo,
        args.target_path,
        args.db_path,
        args.output_dir,
        args.max_steps,
    )
    print(json.dumps(result.get("final_step"), default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

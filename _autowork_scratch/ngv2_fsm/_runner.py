"""Reusable spawn body for the ``python -m ngv2.workers.<phase>`` phase workers.

``stage_command_map.command_for_phase`` emits::

    python -m ngv2.workers.<phase> --session-id <id> --repo <r> \
        --target <t> --out <output_dir>/<phase>.json

``main(phase)`` parses that argv, re-opens the session DB (when
``NGV2_SESSION_DB`` is set) to recover the carried-forward context
(``prior_findings`` for the poc phase, ``parked_package`` for the detonate
phase), assembles the live ``seams`` for the phase, runs the phase module's
``run_stage(context, seams)``, and writes the produced artifacts -- plus a
harvestable ``<phase>_report.json`` aggregate the conductor always parses.

Seam selection (owner directive 2026-06-14): the hunt's DEFAULT LLM is agy;
claude is used ONLY for the dual-agent PoC stage. The hunt phase additionally
needs a LEAD GENERATOR (``hunt_lead_client``) rather than the raw chat callable,
and the detonate phase needs a real bwrap-jail detonation seam built over
``poc_runner_live.detonate_live``.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from typing import Any, Dict, List, Optional

__all__ = ["main", "parse_args", "build_context", "build_seams", "run_phase"]


def parse_args(phase: str, argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Runner for phase {phase}")
    parser.add_argument("--session-id", required=True, dest="session_id")
    parser.add_argument("--repo", required=False, dest="repo")
    parser.add_argument("--target", required=False, dest="target")
    parser.add_argument("--out", required=True, dest="out")

    def _error(message):
        raise ValueError(message)

    def _exit(status=0, message=None):
        raise ValueError(message or f"Exit status {status}")

    parser.error = _error
    parser.exit = _exit
    return parser.parse_args(argv)


def build_context(phase: str, args: argparse.Namespace, session_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row = session_row if isinstance(session_row, dict) else {}
    target = row.get("target")
    if target is None:
        target = getattr(args, "target", None)
    repo = row.get("repo")
    if repo is None:
        repo = getattr(args, "repo", None)
    session_id = row.get("session_id")
    if session_id is None:
        session_id = getattr(args, "session_id", None)
    return {
        "phase": phase,
        "target": target,
        "repo": repo,
        "session_id": session_id,
        "phase_input": row.get("phase_input"),
        "prior_findings": row.get("prior_findings"),
        "parked_package": row.get("parked_package"),
    }


def _load_session_row(session_id: str, session_db_override: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    try:
        ref = session_db_override or os.environ.get("NGV2_SESSION_DB")
        if not ref:
            return None
        from ngv2.session_db import SessionDB
        if isinstance(ref, str):
            with SessionDB(ref) as db:
                return db.get_session(session_id)
        elif hasattr(ref, "get_session"):
            return ref.get_session(session_id)
        return None
    except Exception:
        return None


def _hunt_may_confirm(**kwargs: Any) -> bool:
    """Hunt-phase candidate graduation gate.

    The hunt phase surfaces candidate leads; substantive filtering happens at the
    downstream transition gates (poc_authenticity, detonation_evidence,
    sink_presence, sink_reachability). A candidate graduates to a finding when it
    is well-formed -- a non-empty title and a category/description -- so junk is
    dropped here while real leads flow forward to be proven or fail-closed.
    """
    cand = kwargs.get("candidate") or kwargs.get("finding") or kwargs.get("item") or {}
    if not isinstance(cand, dict):
        return False
    title = cand.get("title") or cand.get("name")
    body = cand.get("description") or cand.get("category") or cand.get("cwe")
    return bool(title) and bool(body)


def _make_detonation_seam():
    """Build the detonate-phase seam over the real bwrap-jail detonator.

    Returns a callable accepting the detonate worker's invocation pool
    (``poc``/``target``/``finding``/``parked_package``/``context``). It builds a
    ``contracts.PoC`` from the PoC source, runs ``detonate_live`` in a jail
    against the target repo, and reports a result whose ``success`` /
    ``reproduced`` flags are driven by the SEMANTIC verdict (success marker +
    expected filesystem signature), not a bare exit code -- so a confirmation is
    real. Returns None if the detonator is unavailable.
    """
    try:
        from ngv2.poc_runner_live import detonate_live
        from ngv2.contracts import PoC
        from ngv2.poc_repair_loop import DEFAULT_MARKER, DEFAULT_FS_SIGNATURE
    except Exception:
        return None

    def _coerce_source(poc: Any) -> Optional[str]:
        if isinstance(poc, str):
            return poc
        if isinstance(poc, dict):
            for key in ("poc", "poc_code", "code", "source", "content", "script"):
                val = poc.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        code = getattr(poc, "code", None)
        return code if isinstance(code, str) else None

    def detonation(poc=None, target=None, finding=None, parked_package=None,
                   package=None, context=None, **kw):
        ctx = context if isinstance(context, dict) else {}
        src = _coerce_source(poc) or _coerce_source(parked_package) or _coerce_source(package)
        if not src:
            return {"success": False, "ran_target": False, "error": "no PoC source"}
        info = {}
        for cand in (finding, parked_package, package):
            if isinstance(cand, dict):
                info = cand
                break
        nested = info.get("finding") if isinstance(info.get("finding"), dict) else {}
        fs_sig = info.get("expected_fs_signature") or nested.get("expected_fs_signature") or DEFAULT_FS_SIGNATURE
        marker = info.get("success_marker") or nested.get("success_marker") or DEFAULT_MARKER
        repo_root = ctx.get("repo") or (target if isinstance(target, str) else None)
        finding_id = str(info.get("id") or nested.get("id") or "F-hunt")
        poc_obj = PoC(finding_id=finding_id, language="python", code=src, entrypoint="")
        try:
            dlr = detonate_live(
                poc_obj,
                {"repo_root": repo_root},
                success_marker=marker,
                expected_fs_signature=fs_sig,
            )
        except Exception as exc:
            return {"success": False, "ran_target": True, "error": str(exc)}
        confirmed = dlr.get("verdict") == "confirmed"
        return {
            "success": confirmed,
            "reproduced": confirmed,
            "observed_runtime_effect": confirmed,
            "ran_target": True,
            "verdict": dlr.get("verdict"),
            "exit_code": dlr.get("exit_code"),
            "stdout": dlr.get("stdout", ""),
            "stderr": dlr.get("stderr", ""),
            "duration": dlr.get("duration_ms"),
            "fs_snapshot_diff": dlr.get("fs_snapshot_diff"),
        }

    return detonation


def build_seams(phase: str) -> Dict[str, Any]:
    try:
        seams: Dict[str, Any] = {}
        client: Any = None
        if phase == "poc":
            try:
                from ngv2.claude_cli_client import make_claude_cli_complete
                client = make_claude_cli_complete()
            except Exception:
                client = None
        elif phase == "hunt":
            try:
                from ngv2.hunt_lead_client import make_hunt_lead_client
                client = make_hunt_lead_client()
            except Exception:
                client = None
        if client is None and phase != "poc":
            try:
                from ngv2.agy_client import make_agy_complete
                client = make_agy_complete()
            except Exception:
                client = None
        if client is None:
            try:
                from ngv2.llm_client import make_anthropic_client
                client = make_anthropic_client()
            except Exception:
                client = None
        if client is not None:
            seams["llm_client"] = client
            seams["llm"] = client
            seams["client"] = client
        if phase == "hunt":
            seams["may_confirm"] = _hunt_may_confirm
        elif phase == "triage":
            try:
                from ngv2.sink_reachability_gate import reachable
                seams["may_confirm"] = reachable
                seams["triage_may_confirm"] = reachable
            except Exception:
                pass
        elif phase == "verify":
            try:
                from ngv2.detonation_evidence_gate import evaluate
                seams["may_confirm"] = evaluate
                seams["verify_may_confirm"] = evaluate
            except Exception:
                pass
        elif phase == "poc":
            try:
                from ngv2.poc_writer import write_poc
                seams["writer"] = write_poc
            except Exception:
                pass
            try:
                from ngv2.poc_repair_loop import repair_poc
                seams["repair"] = repair_poc
            except Exception:
                pass
        elif phase == "detonate":
            det = _make_detonation_seam()
            if det is not None:
                seams["detonation"] = det
        elif phase == "novelty":
            try:
                from ngv2.novelty_gate import classify_novelty
                seams["novelty_gate"] = classify_novelty
            except Exception:
                pass
        elif phase == "report":
            try:
                from ngv2.submission_package import build_submission_package
                seams["build_submission_package"] = build_submission_package
            except Exception:
                pass
        return seams
    except Exception:
        return {}


def run_phase(phase: str, context: Dict[str, Any], seams: Dict[str, Any]) -> List[Dict[str, Any]]:
    module = importlib.import_module(f"ngv2.workers.{phase}")
    run_stage = getattr(module, "run_stage")
    result = run_stage(context, seams)
    if result is None:
        return []
    if isinstance(result, dict):
        return [result]
    return list(result)


def _write_artifacts(phase: str, artifacts: List[Dict[str, Any]], out_path: str) -> None:
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    verdicts: List[Any] = []
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        verdict = art.get("verdict")
        if verdict is None and isinstance(art.get("report"), dict):
            verdict = art["report"].get("verdict")
        if verdict is not None:
            verdicts.append(verdict)
    rollup_verdict = None
    if verdicts:
        for bad in ("error", "failure", "unconfirmed", "refuted"):
            if bad in verdicts:
                rollup_verdict = bad
                break
        if rollup_verdict is None:
            rollup_verdict = verdicts[0]
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        filename = art.get("filename")
        content = art.get("content")
        if not filename or content is None:
            continue
        path = os.path.join(out_dir, filename)
        if isinstance(content, str):
            with open(path, "w") as fh:
                fh.write(content)
        else:
            with open(path, "w") as fh:
                fh.write(json.dumps(content, default=str, sort_keys=True))
    rollup = {"phase": phase, "n_artifacts": len(artifacts), "verdict": rollup_verdict, "artifacts": artifacts}
    aggregate_name = f"{phase}_report.json"
    aggregate_path = os.path.join(out_dir, aggregate_name)
    payload = json.dumps(rollup, default=str, sort_keys=True)
    with open(aggregate_path, "w") as fh:
        fh.write(payload)
    if os.path.abspath(out_path) != os.path.abspath(aggregate_path):
        with open(out_path, "w") as fh:
            fh.write(payload)


def main(phase: str, argv: Optional[List[str]] = None, *, session_db: Optional[Any] = None, seams: Optional[Dict[str, Any]] = None) -> int:
    args = parse_args(phase, argv)
    row = _load_session_row(args.session_id, session_db)
    context = build_context(phase, args, row)
    built = build_seams(phase)
    if seams is not None:
        built.update(seams)
    try:
        artifacts = run_phase(phase, context, built)
    except Exception:
        artifacts = []
    _write_artifacts(phase, artifacts, args.out)
    return 0

from __future__ import annotations
import argparse
import importlib
import json
import os
from typing import Any, Dict, List, Optional
var_0 = ['main', 'parse_args', 'build_context', 'build_seams', 'run_phase']

def parse_args(phase: str, argv: Optional[List[str]]=None) -> argparse.Namespace:
    var_1 = argparse.ArgumentParser(description=f'Runner for phase {phase}')
    var_1.add_argument('--session-id', required=True, dest='session_id')
    var_1.add_argument('--repo', required=False, dest='repo')
    var_1.add_argument('--target', required=False, dest='target')
    var_1.add_argument('--out', required=True, dest='out')

    def error_impl(message):
        raise ValueError(message)

    def exit_impl(status=0, message=None):
        raise ValueError(message or f'Exit status {status}')
    var_1.error = error_impl
    var_1.exit = exit_impl
    return var_1.parse_args(argv)

def build_context(phase: str, args: argparse.Namespace, session_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    var_1 = session_row if isinstance(session_row, dict) else {}
    var_2 = var_1.get('target')
    if var_2 is None:
        var_2 = getattr(args, 'target', None)
    var_3 = var_1.get('repo')
    if var_3 is None:
        var_3 = getattr(args, 'repo', None)
    var_4 = var_1.get('session_id')
    if var_4 is None:
        var_4 = getattr(args, 'session_id', None)
    var_5 = {'phase': phase, 'target': var_2, 'repo': var_3, 'session_id': var_4, 'phase_input': var_1.get('phase_input'), 'prior_findings': var_1.get('prior_findings'), 'parked_package': var_1.get('parked_package')}
    return var_5

def _load_session_row(session_id: str, session_db_override: Optional[Any]=None) -> Optional[Dict[str, Any]]:
    try:
        var_1 = session_db_override or os.environ.get('NGV2_SESSION_DB')
        if not var_1:
            return None
        from ngv2.session_db import SessionDB
        if isinstance(var_1, str):
            with SessionDB(var_1) as var_2:
                return var_2.get_session(session_id)
        elif hasattr(var_1, 'get_session'):
            return var_1.get_session(session_id)
        return None
    except Exception:
        return None

def build_seams(phase: str) -> Dict[str, Any]:
    try:
        var_1 = {}
        # LLM client selection (owner directive 2026-06-14): agy is the DEFAULT
        # hunt model for every phase; claude is used ONLY for the dual-agent PoC
        # stage (write_poc + repair_poc). Fall back to the anthropic SDK only when
        # the chosen CLI adapter is unavailable. The CompleteFn closures carry a
        # `.backend` tag ('agy' | 'claude') so the selection is assertable offline.
        var_2 = None
        if phase == 'poc':
            try:
                from ngv2.claude_cli_client import make_claude_cli_complete
                var_2 = make_claude_cli_complete()
            except Exception:
                var_2 = None
        else:
            try:
                from ngv2.agy_client import make_agy_complete
                var_2 = make_agy_complete()
            except Exception:
                var_2 = None
        if var_2 is None:
            try:
                from ngv2.llm_client import make_anthropic_client
                var_2 = make_anthropic_client()
            except Exception:
                var_2 = None
        if var_2 is not None:
            var_1['llm_client'] = var_2
            var_1['llm'] = var_2
            var_1['client'] = var_2
        if phase == 'hunt':
            try:
                from ngv2.sink_presence_gate import present
                var_1['may_confirm'] = present
            except Exception:
                pass
        elif phase == 'triage':
            try:
                from ngv2.sink_reachability_gate import reachable
                var_1['may_confirm'] = reachable
                var_1['triage_may_confirm'] = reachable
            except Exception:
                pass
        elif phase == 'verify':
            try:
                from ngv2.detonation_evidence_gate import evaluate
                var_1['may_confirm'] = evaluate
                var_1['verify_may_confirm'] = evaluate
            except Exception:
                pass
        elif phase == 'poc':
            try:
                from ngv2.poc_writer import write_poc
                var_1['writer'] = write_poc
            except Exception:
                pass
            try:
                from ngv2.poc_repair_loop import repair_poc
                var_1['repair'] = repair_poc
            except Exception:
                pass
        elif phase == 'detonate':
            try:
                from ngv2.poc_runner_live import execute_poc
                var_1['detonation'] = execute_poc
            except Exception:
                pass
        elif phase == 'novelty':
            try:
                from ngv2.novelty_gate import classify_novelty
                var_1['novelty_gate'] = classify_novelty
            except Exception:
                pass
        elif phase == 'report':
            try:
                from ngv2.submission_package import build_submission_package
                var_1['build_submission_package'] = build_submission_package
            except Exception:
                pass
        return var_1
    except Exception:
        return {}

def run_phase(phase: str, context: Dict[str, Any], seams: Dict[str, Any]) -> List[Dict[str, Any]]:
    var_1 = f'ngv2.workers.{phase}'
    var_2 = importlib.import_module(var_1)
    var_3 = getattr(var_2, 'run_stage')
    var_4 = var_3(context, seams)
    if var_4 is None:
        return []
    if isinstance(var_4, dict):
        return [var_4]
    return list(var_4)

def _write_artifacts(phase: str, artifacts: List[Dict[str, Any]], out_path: str) -> None:
    var_1 = os.path.dirname(out_path)
    if var_1:
        os.makedirs(var_1, exist_ok=True)
    var_2 = []
    for var_3 in artifacts:
        if not isinstance(var_3, dict):
            continue
        var_6 = var_3.get('verdict')
        if var_6 is None and 'report' in var_3 and isinstance(var_3['report'], dict):
            var_6 = var_3['report'].get('verdict')
        if var_6 is not None:
            var_2.append(var_6)
    var_4 = None
    if var_2:
        for var_7 in ('error', 'failure', 'unconfirmed', 'refuted'):
            if var_7 in var_2:
                var_4 = var_7
                break
        if var_4 is None:
            var_4 = var_2[0]
    for var_3 in artifacts:
        if not isinstance(var_3, dict):
            continue
        var_8 = var_3.get('filename')
        var_9 = var_3.get('content')
        if not var_8 or var_9 is None:
            continue
        var_10 = os.path.join(var_1, var_8)
        if isinstance(var_9, str):
            with open(var_10, 'w') as var_11:
                var_11.write(var_9)
        else:
            with open(var_10, 'w') as var_11:
                var_11.write(json.dumps(var_9, default=str, sort_keys=True))
    var_5 = {'phase': phase, 'n_artifacts': len(artifacts), 'verdict': var_4, 'artifacts': artifacts}
    var_12 = f'{phase}_report.json'
    var_13 = os.path.join(var_1, var_12)
    var_14 = json.dumps(var_5, default=str, sort_keys=True)
    with open(var_13, 'w') as var_11:
        var_11.write(var_14)
    if os.path.abspath(out_path) != os.path.abspath(var_13):
        with open(out_path, 'w') as var_11:
            var_11.write(var_14)

def main(phase: str, argv: Optional[List[str]]=None, *, session_db: Optional[Any]=None, seams: Optional[Dict[str, Any]]=None) -> int:
    var_1 = parse_args(phase, argv)
    var_2 = _load_session_row(var_1.session_id, session_db)
    var_3 = build_context(phase, var_1, var_2)
    var_4 = build_seams(phase)
    if seams is not None:
        var_4.update(seams)
    try:
        var_5 = run_phase(phase, var_3, var_4)
    except Exception:
        var_5 = []
    _write_artifacts(phase, var_5, var_1.out)
    return 0

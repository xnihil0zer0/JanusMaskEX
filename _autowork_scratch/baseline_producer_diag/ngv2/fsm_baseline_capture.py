"""Module to handle FSM baseline capture state handler logic."""
from typing import Any
from ngv2.fsm_evidence import phase_artifact_hash, advance_gate, ENV_PHASE_ORDER

def baseline_capture(jail_artifact: dict, reachability_artifact: dict | None=None) -> dict:
    """Process a pre-captured benign control summary and adjudicate baseline capture."""
    try:
        reachability_res = advance_gate(reachability_artifact)
        if not reachability_res.get('advance', False):
            return {'advance': False, 'terminal': reachability_res.get('terminal', 'missing_evidence'), 'artifact': None}
        if jail_artifact is None or not isinstance(jail_artifact, dict):
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        if 'content_hash' in jail_artifact:
            jail_gate = advance_gate(jail_artifact)
            if not jail_gate.get('advance', False):
                return {'advance': False, 'terminal': jail_gate.get('terminal', 'missing_evidence'), 'artifact': None}
        source = None
        if isinstance(jail_artifact.get('details'), dict) and isinstance(jail_artifact['details'].get('baseline_input'), dict):
            source = jail_artifact['details']['baseline_input']
        elif isinstance(jail_artifact.get('baseline_input'), dict):
            source = jail_artifact['baseline_input']
        elif isinstance(jail_artifact.get('details'), dict):
            source = jail_artifact['details']
        if source is None:
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        success_marker = source.get('success_marker')
        expected_fs_signature = source.get('expected_fs_signature')
        if success_marker is None or success_marker == '':
            return {'advance': False, 'terminal': 'baseline_vacuous', 'artifact': None}
        if expected_fs_signature is None or expected_fs_signature == '':
            return {'advance': False, 'terminal': 'baseline_vacuous', 'artifact': None}
        control_stdout = source.get('stdout')
        if control_stdout is None:
            control_stdout = ''
        elif not isinstance(control_stdout, str):
            control_stdout = str(control_stdout)
        fs_diff_paths = source.get('fs_diff')
        if not isinstance(fs_diff_paths, list):
            fs_diff_paths = []
        if success_marker in control_stdout:
            return {'advance': False, 'terminal': 'baseline_vacuous', 'artifact': None}
        for path in fs_diff_paths:
            if isinstance(path, str) and expected_fs_signature in path:
                return {'advance': False, 'terminal': 'baseline_vacuous', 'artifact': None}
        details_out = dict(source)
        details_out['control_clean'] = True
        artifact = {'phase': 'baseline_capture', 'status': 'success', 'details': details_out}
        artifact['content_hash'] = phase_artifact_hash(artifact)
        return {'advance': True, 'terminal': '', 'artifact': artifact}
    except Exception:
        return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
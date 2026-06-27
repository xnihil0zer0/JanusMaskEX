"""Module to adjudicate sink-reachability and emit a content-hashed ReachabilityArtifact."""
from typing import Dict, Any, Optional
from ngv2.fsm_evidence import advance_gate, phase_artifact_hash

def reachability_probe(detect_artifact: Optional[Dict[str, Any]], finding: Dict[str, Any], health_artifact: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """Pure, fail-closed reachability_probe env-state adjudicator."""
    try:
        health_check = advance_gate(health_artifact)
        if not health_check.get('advance', False):
            return {'advance': False, 'terminal': health_check.get('terminal', 'missing_evidence'), 'artifact': None}
        if detect_artifact is not None:
            detect_check = advance_gate(detect_artifact)
            if not detect_check.get('advance', False):
                return {'advance': False, 'terminal': detect_check.get('terminal', 'missing_evidence'), 'artifact': None}
        if not isinstance(finding, dict):
            return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        if 'reach_input' not in finding:
            return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        reach_input = finding['reach_input']
        if not isinstance(reach_input, dict):
            return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        if 'sink_present' not in reach_input or 'sink_reachable' not in reach_input:
            return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        sink_present = reach_input['sink_present']
        sink_reachable = reach_input['sink_reachable']
        if not isinstance(sink_present, bool) or not isinstance(sink_reachable, str):
            return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        benign_ping_reached = None
        if 'benign_ping_reached' in reach_input:
            benign_ping_reached = reach_input['benign_ping_reached']
            if not isinstance(benign_ping_reached, bool):
                return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
        if not sink_present:
            return {'advance': False, 'terminal': 'sink_patched', 'artifact': None}
        if sink_reachable == 'constant_only':
            return {'advance': False, 'terminal': 'constant_only', 'artifact': None}
        if sink_reachable != 'reachable' or benign_ping_reached is False:
            return {'advance': False, 'terminal': 'sink_not_reachable', 'artifact': None}
        details = {'sink_present': sink_present, 'sink_reachable': sink_reachable}
        if benign_ping_reached is not None:
            details['benign_ping_reached'] = benign_ping_reached
        artifact_data = {'phase': 'reachability_probe', 'status': 'success', 'details': details}
        artifact_data['content_hash'] = phase_artifact_hash(artifact_data)
        return {'advance': True, 'terminal': '', 'artifact': artifact_data}
    except Exception:
        return {'advance': False, 'terminal': 'malformed_input', 'artifact': None}
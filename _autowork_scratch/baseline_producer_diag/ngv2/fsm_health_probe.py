"""Module to adjudicate FSM health probe results and emit a content-hashed HealthArtifact."""
from typing import Dict, Any, Optional
from ngv2.fsm_evidence import advance_gate, phase_artifact_hash

def health_probe(jail_artifact: dict, provision_artifact: dict | None=None, health_input: dict | None=None) -> dict:
    """Pure, fail-closed health_probe state gate.
    
    Adjudicates prior jail_artifact and optional provision_artifact, and the health_input
    summary, returning advance status, terminal code, and the success HealthArtifact.
    """
    try:
        jail_check = advance_gate(jail_artifact)
        if not jail_check.get('advance', False):
            return {'advance': False, 'terminal': jail_check.get('terminal', 'missing_evidence'), 'artifact': None}
        if provision_artifact is not None:
            provision_check = advance_gate(provision_artifact)
            if not provision_check.get('advance', False):
                return {'advance': False, 'terminal': provision_check.get('terminal', 'missing_evidence'), 'artifact': None}
        if health_input is None:
            if isinstance(jail_artifact, dict) and 'details' in jail_artifact:
                jail_details = jail_artifact['details']
                if isinstance(jail_details, dict):
                    health_input = jail_details.get('health_input')
        if not isinstance(health_input, dict):
            return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
        if 'import_ok' not in health_input or 'is_service' not in health_input:
            return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
        import_ok = health_input['import_ok']
        is_service = health_input['is_service']
        if not isinstance(import_ok, bool) or not isinstance(is_service, bool):
            return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
        if not import_ok:
            return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
        if is_service:
            if 'service_bound' not in health_input or 'health_route_ok' not in health_input:
                return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
            service_bound = health_input['service_bound']
            health_route_ok = health_input['health_route_ok']
            if not isinstance(service_bound, bool) or not isinstance(health_route_ok, bool):
                return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
            if not service_bound or not health_route_ok:
                return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
        details = {}
        for field_name in ('import_ok', 'is_service', 'service_bound', 'bound_addr', 'health_route_ok', 'start_cmd'):
            if field_name in health_input:
                details[field_name] = health_input[field_name]
        artifact_data = {'phase': 'health_probe', 'status': 'success', 'details': details}
        artifact_data['content_hash'] = phase_artifact_hash(artifact_data)
        return {'advance': True, 'terminal': '', 'artifact': artifact_data}
    except Exception:
        return {'advance': False, 'terminal': 'service_no_bind', 'artifact': None}
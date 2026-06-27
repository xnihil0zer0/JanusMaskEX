from typing import Any, Dict, List, Optional
from ngv2.fsm_evidence import phase_artifact_hash, advance_gate, ENV_PHASE_ORDER

def detect(detect_input: Any, prev_artifact: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """Pure detect state handler to classify language/build-system, resolve ABI interpreter pin, and emit a content-hashed DetectArtifact.
    """
    if not isinstance(detect_input, dict):
        return {'advance': False, 'terminal': 'no_eligible_language', 'artifact': None}
    language = detect_input.get('language')
    if language not in ('python', 'javascript'):
        return {'advance': False, 'terminal': 'no_eligible_language', 'artifact': None}
    is_entry = detect_input.get('is_entry') is True
    if not is_entry:
        prev_res = advance_gate(prev_artifact)
        if not prev_res.get('advance', False):
            return {'advance': False, 'terminal': prev_res.get('terminal', 'missing_evidence'), 'artifact': None}
    build_files = detect_input.get('build_files')
    if not isinstance(build_files, list) or not build_files:
        return {'advance': False, 'terminal': 'no_build_system', 'artifact': None}
    head_commit = detect_input.get('head_commit')
    pinned_commit = detect_input.get('pinned_commit')
    if not head_commit or not pinned_commit or head_commit != pinned_commit:
        return {'advance': False, 'terminal': 'sha_mismatch', 'artifact': None}
    if language == 'python':
        resolved_bin = detect_input.get('resolved_python_bin')
        if not resolved_bin or not isinstance(resolved_bin, str):
            return {'advance': False, 'terminal': 'interpreter_unresolved', 'artifact': None}
    elif language == 'javascript':
        resolved_bin = detect_input.get('resolved_node_bin')
        if not resolved_bin or not isinstance(resolved_bin, str):
            return {'advance': False, 'terminal': 'interpreter_unresolved', 'artifact': None}
    artifact_data = {'phase': 'detect', 'status': 'success', 'details': {'language': language, 'build_files': list(build_files), 'head_commit': head_commit, 'pinned_commit': pinned_commit, 'resolved_python_bin': detect_input.get('resolved_python_bin'), 'resolved_node_bin': detect_input.get('resolved_node_bin')}}
    artifact_copy = dict(artifact_data)
    artifact_copy.pop('content_hash', None)
    artifact_data['content_hash'] = phase_artifact_hash(artifact_copy)
    return {'advance': True, 'terminal': '', 'artifact': artifact_data}
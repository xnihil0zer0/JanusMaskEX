import hashlib
import json
from typing import Any, Tuple
PHASE_ORDER: Tuple[str, ...] = ('source', 'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report', 'awaiting_submission', 'submitted', 'done')
ENV_PHASE_ORDER: Tuple[str, ...] = ('detect', 'provision', 'jail_build', 'health_probe', 'reachability_probe', 'baseline_capture')

def phase_artifact_hash(artifact: Any) -> str:
    """Compute a deterministic SHA-256 hash for the artifact."""
    s = json.dumps(artifact, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def advance_gate(artifact: Any) -> dict:
    """Enforce fail-closed check on artifact presence, dict type, and correct content hash."""
    if not isinstance(artifact, dict):
        return {'advance': False, 'terminal': 'missing_evidence'}
    if 'content_hash' not in artifact:
        return {'advance': False, 'terminal': 'missing_evidence'}
    expected_hash = artifact['content_hash']
    if not isinstance(expected_hash, str) or not expected_hash:
        return {'advance': False, 'terminal': 'missing_evidence'}
    try:
        artifact_copy = dict(artifact)
        artifact_copy.pop('content_hash', None)
        computed_hash = phase_artifact_hash(artifact_copy)
    except Exception:
        return {'advance': False, 'terminal': 'missing_evidence'}
    if computed_hash == expected_hash:
        return {'advance': True, 'terminal': ''}
    else:
        return {'advance': False, 'terminal': 'hash_mismatch'}
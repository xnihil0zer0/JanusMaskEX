"""Module to preflight dependency provision results and emit a content-hashed ProvisionArtifact."""
from typing import Any
from ngv2.fsm_evidence import phase_artifact_hash, advance_gate, ENV_PHASE_ORDER

def provision_gate(provision_input: dict, prev_artifact: dict | None=None) -> dict:
    """Validate dependency provision results and transition to the provision state."""
    try:
        prev_res = advance_gate(prev_artifact)
        if not prev_res.get('advance', False):
            return {'advance': False, 'terminal': prev_res.get('terminal', 'missing_evidence'), 'artifact': None}
        if not isinstance(provision_input, dict):
            return {'advance': False, 'terminal': 'provision_unrunnable', 'artifact': None}
        resolved_python_bin = provision_input.get('resolved_python_bin')
        if not resolved_python_bin:
            return {'advance': False, 'terminal': 'interpreter_unresolved', 'artifact': None}
        install_argv = provision_input.get('install_argv')
        if not isinstance(install_argv, list) or '--unshare-net' not in install_argv:
            return {'advance': False, 'terminal': 'install_not_jailed', 'artifact': None}
        installed = provision_input.get('installed_packages') or []
        stderr_named = provision_input.get('install_stderr_named_packages') or []
        lockfile = provision_input.get('lockfile_packages') or []
        lockfile_set = set(lockfile)
        stderr_named_set = set(stderr_named)
        for pkg in installed:
            if pkg in stderr_named_set and pkg not in lockfile_set:
                return {'advance': False, 'terminal': 'attacker_named_package', 'artifact': None}
        smoke_import_ok = provision_input.get('smoke_import_ok')
        if smoke_import_ok is not True:
            return {'advance': False, 'terminal': 'provision_unrunnable', 'artifact': None}
        artifact_data = {'phase': 'provision', 'status': 'success', 'details': {'installed_packages': list(installed), 'install_stderr_named_packages': list(stderr_named), 'lockfile_packages': list(lockfile), 'install_argv': list(install_argv), 'resolved_python_bin': resolved_python_bin, 'smoke_import_ok': smoke_import_ok}}
        artifact_copy = dict(artifact_data)
        artifact_copy.pop('content_hash', None)
        h_val = phase_artifact_hash(artifact_copy)
        artifact_data['content_hash'] = h_val
        return {'advance': True, 'terminal': '', 'artifact': artifact_data}
    except Exception:
        return {'advance': False, 'terminal': 'provision_unrunnable', 'artifact': None}
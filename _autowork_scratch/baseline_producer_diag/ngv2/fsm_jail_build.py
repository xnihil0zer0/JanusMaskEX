"""Module to preflight bubblewrap constructibility and emit a content-hashed JailArtifact."""
from typing import Any
from ngv2.fsm_evidence import phase_artifact_hash, advance_gate, ENV_PHASE_ORDER

def jail_build_gate(jail_input: dict, prev_artifact: dict | None=None) -> dict:
    """Preflight bubblewrap constructibility and emit a content-hashed JailArtifact.
    
    Validates prior artifact, checks bwrap availability, isolation flags,
    and binding paths when provided.
    """
    try:
        advance_res = advance_gate(prev_artifact)
        if not advance_res.get('advance', False):
            return {'advance': False, 'terminal': advance_res.get('terminal', 'missing_evidence'), 'artifact': None}
        if not isinstance(jail_input, dict):
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        if not jail_input.get('bwrap_available', False):
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        jail_argv = jail_input.get('jail_argv', [])
        if not isinstance(jail_argv, list):
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        required_flags = {'--unshare-net', '--unshare-ipc', '--unshare-pid'}
        if not required_flags.issubset(set(jail_argv)):
            return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        repo_root = jail_input.get('repo_root')
        if repo_root:
            repo_bound = False
            for i in range(len(jail_argv) - 2):
                if jail_argv[i] in ('--ro-bind', '--ro-bind-try'):
                    if jail_argv[i + 1] == repo_root or jail_argv[i + 2] == repo_root:
                        repo_bound = True
                        break
            if not repo_bound:
                return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        work_dir = jail_input.get('work_dir')
        if work_dir:
            work_bound = False
            for i in range(len(jail_argv) - 2):
                if jail_argv[i] in ('--bind', '--bind-try'):
                    if jail_argv[i + 1] == work_dir or jail_argv[i + 2] == work_dir:
                        work_bound = True
                        break
            if not work_bound:
                for i in range(len(jail_argv) - 1):
                    if jail_argv[i] == '--tmpfs' and jail_argv[i + 1] == work_dir:
                        work_bound = True
                        break
            if not work_bound:
                return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
        artifact_data = {'phase': 'jail_build', 'status': 'success', 'details': {'bwrap_available': True, 'jail_argv': jail_argv, 'repo_root': repo_root, 'work_dir': work_dir}}
        h_val = phase_artifact_hash(artifact_data)
        artifact_data['content_hash'] = h_val
        return {'advance': True, 'terminal': '', 'artifact': artifact_data}
    except Exception:
        return {'advance': False, 'terminal': 'jail_unavailable', 'artifact': None}
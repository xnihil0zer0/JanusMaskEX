def validate_grounding_bundle(path: str, key: str) -> bool:
    """
    Validates a cryptographic signature of a grounding bundle.
    Rejects missing header/payload/signature, alg: none, and key manipulation.
    """
    try:
        if not os.path.exists(path):
            return False
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    if 'header' not in data or 'payload' not in data or 'signature' not in data:
        return False
    header = data['header']
    payload = data['payload']
    signature = data['signature']
    if not isinstance(header, dict) or not isinstance(signature, str) or (not signature):
        return False
    if 'alg' not in header:
        return False
    alg = header['alg']
    if alg is None or (isinstance(alg, str) and alg.lower() == 'none'):
        return False
    if not isinstance(alg, str) or alg.upper() != 'HS256':
        return False
    try:
        header_str = json.dumps(header, sort_keys=True, separators=(',', ':'))
        payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        message = f'{header_str}.{payload_str}'.encode('utf-8')
        expected_sig = hmac.new(key.encode('utf-8'), message, hashlib.sha256).hexdigest()
        if hmac.compare_digest(signature.strip().lower(), expected_sig.lower()):
            return True
    except Exception:
        return False
    return False

def classify_failure_severity(tb: str) -> str:
    """
    Reads the final exception line of a traceback.
    Classifies SyntaxErrors in imported dependencies as conceptual_mismatch,
    and other errors as implementation_defect.
    """
    if not tb or not tb.strip():
        return 'implementation_defect'
    lines = [line.strip() for line in tb.strip().split('\n') if line.strip()]
    if not lines:
        return 'implementation_defect'
    final_line = lines[-1]
    parts = final_line.split(':', 1)
    exc_type = parts[0].strip()
    if exc_type not in ('SyntaxError', 'IndentationError', 'TabError'):
        return 'implementation_defect'
    file_pattern = re.compile('File "([^"]+)"')
    frames = []
    for line in lines:
        match = file_pattern.search(line)
        if match:
            frames.append(match.group(1))
    if not frames:
        return 'implementation_defect'
    error_file = frames[-1]

    def is_project_file(path: str) -> bool:
        norm = os.path.normpath(path).replace('\\', '/')
        for marker in ['site-packages', '.venv', 'dist-packages', 'lib/python', '/usr/lib']:
            if marker in norm:
                return False
        if os.path.isabs(norm):
            workspace = '/mnt/ai-data/JanusMaskEX'
            try:
                cur_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
            except Exception:
                cur_dir = workspace
            in_workspace = False
            for ws in [workspace, cur_dir]:
                ws_norm = os.path.normpath(ws).replace('\\', '/')
                if norm.startswith(ws_norm):
                    in_workspace = True
                    break
            if not in_workspace:
                return False
            rel_to_ws = os.path.relpath(norm, ws_norm).replace('\\', '/')
            if rel_to_ws.startswith('..'):
                return False
            norm = rel_to_ws
        parts = norm.split('/')
        first_part = parts[0]
        project_folders = {'harness', 'tests', 'webui', 'services', 'overseer', 'autocompiler', 'tools'}
        if first_part in project_folders:
            return True
        basename = os.path.basename(norm)
        known_targets = {'grounding.py', 'state.py', 'orchestrator.py', 'media_manager.py', 'autowork_daemon.py', 'agent_jail.py', 'model_backends.py', 'boundary_smoothing.py', 'conftest.py'}
        if basename in known_targets:
            return True
        return False
    error_in_target = is_project_file(error_file)
    if not error_in_target:
        return 'conceptual_mismatch'
    return 'implementation_defect'
import json
import hmac
import hashlib
import os
import re
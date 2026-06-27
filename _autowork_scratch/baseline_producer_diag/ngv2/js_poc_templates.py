"""Deterministic JavaScript/Node.js PoC-scaffolding generator (pure_fuzz).

This module is a PURE, stdlib-only emitter of JavaScript/Node.js proof-of-concept
*scaffolding* strings for huntr.com style submissions. It performs NO network,
clock, subprocess, LLM, or exploit execution of any kind. Every template is a
plain string builder: caller-supplied ``library_name`` and ``vuln_description``
are interpolated verbatim into inert template text and are NEVER executed,
evaluated, or compiled. Inputs that look like executable payloads are treated as
ordinary text.

Public surface (frozen by the committed oracle):

* ``TEMPLATES``        -- dict mapping CWE id -> callable(library, description) -> str
* ``SUPPORTED_CWES``   -- sorted list of the supported CWE keys
* ``run``              -- normalizes argparse args and returns a stable envelope

The module is deterministic: identical inputs always yield byte-identical output,
and no module-level state is mutated by ``run``.
"""
from __future__ import annotations
import argparse
from typing import Callable
from typing import Dict
from typing import List

def _template_cwe_78(library: str, description: str) -> str:
    """CWE-78: OS Command Injection scaffolding."""
    return "// PoC scaffolding for {lib} -- CWE-78 (OS Command Injection)\n// {desc}\n// NOTE: scaffolding only. Do not execute against systems you do not own.\nconst target = require('{lib}');\n\n// Replace the placeholder with the crafted command-injection payload.\nconst payload = '$(echo INJECTED)';\n\n// Demonstrates how untrusted input reaches a shell sink in {lib}.\n// target.someApi(payload); // <-- sink under analysis\nconsole.log('[PoC] CWE-78 command injection scaffolding for {lib}');\nconsole.log('[PoC] description: {desc}');\n".format(lib=library, desc=description)

def _template_cwe_94(library: str, description: str) -> str:
    """CWE-94: Code Injection scaffolding."""
    return '// PoC scaffolding for {lib} -- CWE-94 (Code Injection)\n// {desc}\n// NOTE: scaffolding only -- the payload string below is never evaluated.\nconst target = require(\'{lib}\');\n\n// Inert template text representing the injected code payload.\nconst payload = \'process.mainModule.require("INJECTED")\';\n\n// Demonstrates how untrusted input reaches a dynamic-code sink in {lib}.\n// target.render(payload); // <-- sink under analysis\nconsole.log(\'[PoC] CWE-94 code injection scaffolding for {lib}\');\nconsole.log(\'[PoC] description: {desc}\');\n'.format(lib=library, desc=description)

def _template_cwe_502(library: str, description: str) -> str:
    """CWE-502: Deserialization of Untrusted Data scaffolding."""
    return '// PoC scaffolding for {lib} -- CWE-502 (Unsafe Deserialization)\n// {desc}\n// NOTE: scaffolding only -- no object is actually deserialized here.\nconst target = require(\'{lib}\');\n\n// Inert serialized blob standing in for the malicious gadget chain.\nconst payload = \'{{"__proto__":{{"polluted":true}}}}\';\n\n// Demonstrates how untrusted serialized input reaches a deserialize sink.\n// target.deserialize(payload); // <-- sink under analysis\nconsole.log(\'[PoC] CWE-502 deserialization scaffolding for {lib}\');\nconsole.log(\'[PoC] description: {desc}\');\n'.format(lib=library, desc=description)

def _template_cwe_22(library: str, description: str) -> str:
    """CWE-22: Path Traversal scaffolding."""
    return "// PoC scaffolding for {lib} -- CWE-22 (Path Traversal)\n// {desc}\n// NOTE: scaffolding only -- no filesystem access is performed.\nconst target = require('{lib}');\n\n// Inert traversal payload pointing outside the intended root.\nconst payload = '../../../../etc/passwd';\n\n// Demonstrates how untrusted path input reaches a file sink in {lib}.\n// target.readFile(payload); // <-- sink under analysis\nconsole.log('[PoC] CWE-22 path traversal scaffolding for {lib}');\nconsole.log('[PoC] description: {desc}');\n".format(lib=library, desc=description)

def _template_cwe_918(library: str, description: str) -> str:
    """CWE-918: Server-Side Request Forgery scaffolding."""
    return "// PoC scaffolding for {lib} -- CWE-918 (Server-Side Request Forgery)\n// {desc}\n// NOTE: scaffolding only -- no network request is issued.\nconst target = require('{lib}');\n\n// Inert SSRF payload aimed at an internal metadata endpoint.\nconst payload = 'http://169.254.169.254/latest/meta-data/';\n\n// Demonstrates how untrusted URL input reaches a request sink in {lib}.\n// target.fetch(payload); // <-- sink under analysis\nconsole.log('[PoC] CWE-918 SSRF scaffolding for {lib}');\nconsole.log('[PoC] description: {desc}');\n".format(lib=library, desc=description)

def _template_cwe_89(library: str, description: str) -> str:
    """CWE-89: SQL Injection scaffolding."""
    return '// PoC scaffolding for {lib} -- CWE-89 (SQL Injection)\n// {desc}\n// NOTE: scaffolding only -- no query is executed against a database.\nconst target = require(\'{lib}\');\n\n// Inert SQL injection payload string.\nconst payload = "\' OR \'1\'=\'1\' -- ";\n\n// Demonstrates how untrusted input reaches a query sink in {lib}.\n// target.query(\'SELECT * FROM users WHERE name = \' + payload);\nconsole.log(\'[PoC] CWE-89 SQL injection scaffolding for {lib}\');\nconsole.log(\'[PoC] description: {desc}\');\n'.format(lib=library, desc=description)

def _template_cwe_601(library: str, description: str) -> str:
    """CWE-601: Open Redirect scaffolding."""
    return "// PoC scaffolding for {lib} -- CWE-601 (Open Redirect)\n// {desc}\n// NOTE: scaffolding only -- no redirect is actually performed.\nconst target = require('{lib}');\n\n// Inert open-redirect payload pointing at an attacker-controlled host.\nconst payload = 'https://attacker.example/login';\n\n// Demonstrates how untrusted input reaches a redirect sink in {lib}.\n// target.redirect(payload); // <-- sink under analysis\nconsole.log('[PoC] CWE-601 open redirect scaffolding for {lib}');\nconsole.log('[PoC] description: {desc}');\n".format(lib=library, desc=description)

def _template_cwe_787(library: str, description: str) -> str:
    """CWE-787: Out-of-bounds Write scaffolding."""
    return "// PoC scaffolding for {lib} -- CWE-787 (Out-of-bounds Write)\n// {desc}\n// NOTE: scaffolding only -- no buffer is actually written out of bounds.\nconst target = require('{lib}');\n\n// Inert oversized payload standing in for the out-of-bounds write input.\nconst payload = 'A'.repeat(4096);\n\n// Demonstrates how untrusted length/offset input reaches a write sink.\n// target.write(payload); // <-- sink under analysis\nconsole.log('[PoC] CWE-787 out-of-bounds write scaffolding for {lib}');\nconsole.log('[PoC] description: {desc}');\n".format(lib=library, desc=description)
TemplateFn = Callable[[str, str], str]

def _cwe_787(library_name: str, vuln_description: str) -> str:
    """CWE-787: Out-of-bounds Write scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-787 (Out-of-bounds Write)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no buffer is mutated by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// Oversized input intended to write past an allocated buffer boundary.\nconst oversizedInput = 'A'.repeat(65536);\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<write_api>(oversizedInput);\n  console.log('[poc] would feed oversized input to {library_name} length:', oversizedInput.length);\n}}\n\nmodule.exports = {{ reproduce }};\n"

def _cwe_601(library_name: str, vuln_description: str) -> str:
    """CWE-601: Open Redirect scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-601 (Open Redirect)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no redirect is performed by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// External destination the victim is redirected to.\nconst externalDestination = 'https://attacker.example/';\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<redirect_api>(externalDestination);\n  console.log('[poc] would redirect via {library_name} to:', externalDestination);\n}}\n\nmodule.exports = {{ reproduce }};\n"

def _cwe_89(library_name: str, vuln_description: str) -> str:
    """CWE-89: SQL Injection scaffolding."""
    return f"""// PoC scaffolding for {library_name} -- CWE-89 (SQL Injection)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no query is executed by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// Tautology payload that subverts the intended WHERE clause.\nconst injectedClause = "' OR '1'='1";\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<query_api>("SELECT * FROM users WHERE name = '" + injectedClause + "'");\n  console.log('[poc] would send injected clause to {library_name}:', injectedClause);\n}}\n\nmodule.exports = {{ reproduce }};\n"""

def _cwe_918(library_name: str, vuln_description: str) -> str:
    """CWE-918: Server-Side Request Forgery scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-918 (Server-Side Request Forgery)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no HTTP request is issued by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// Internal-only URL the attacker coerces {library_name} into requesting.\nconst internalUrl = 'http://169.254.169.254/latest/meta-data/';\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<fetch_api>(internalUrl);\n  console.log('[poc] would fetch internal URL via {library_name}:', internalUrl);\n}}\n\nmodule.exports = {{ reproduce }};\n"

def _cwe_22(library_name: str, vuln_description: str) -> str:
    """CWE-22: Path Traversal scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-22 (Path Traversal)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no files are read or written by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// Traversal sequence that escapes the intended base directory.\nconst traversalPath = '../../../../etc/passwd';\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<path_api>(traversalPath);\n  console.log('[poc] would resolve traversal path via {library_name}:', traversalPath);\n}}\n\nmodule.exports = {{ reproduce }};\n"

def _cwe_502(library_name: str, vuln_description: str) -> str:
    """CWE-502: Deserialization of Untrusted Data scaffolding."""
    return f"""// PoC scaffolding for {library_name} -- CWE-502 (Unsafe Deserialization)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- the crafted blob below is never deserialized here.\n'use strict';\nconst target = require('{library_name}');\n\n// Crafted serialized object representing {vuln_description}.\nconst craftedSerializedBlob = '{{"__proto__":{{"polluted":true}}}}';\n\nfunction reproduce() {{\n  // target.<deserialize_api>(craftedSerializedBlob);\n  console.log('[poc] would deserialize untrusted blob with {library_name}:', craftedSerializedBlob);\n}}\n\nmodule.exports = {{ reproduce }};\n"""

def _cwe_94(library_name: str, vuln_description: str) -> str:
    """CWE-94: Code Injection scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-94 (Code Injection)\n// Vulnerability: {vuln_description}\n// INERT scaffolding only -- no code is evaluated by this template.\n'use strict';\nconst target = require('{library_name}');\n\n// Untrusted source that flows into a dynamic code sink in {library_name}.\nconst untrustedExpression = '1 + 1 /* {vuln_description} */';\n\nfunction reproduce() {{\n  // target.<vulnerable_api>(untrustedExpression);\n  console.log('[poc] would pass expression to {library_name} sink:', untrustedExpression);\n}}\n\nmodule.exports = {{ reproduce }};\n"

def _cwe_78(library_name: str, vuln_description: str) -> str:
    """CWE-78: OS Command Injection scaffolding."""
    return f"// PoC scaffolding for {library_name} -- CWE-78 (OS Command Injection)\n// Vulnerability: {vuln_description}\n// This is INERT scaffolding for manual review; it does not execute commands.\n'use strict';\nconst target = require('{library_name}');\n\n// Replace `injectedArgument` with a benign marker (e.g. a file touch) when\n// reproducing in an isolated sandbox you control.\nconst injectedArgument = 'BENIGN_MARKER; id';\n\nfunction reproduce() {{\n  // {vuln_description}\n  // target.<vulnerable_api>(injectedArgument);\n  console.log('[poc] would invoke {library_name} sink with:', injectedArgument);\n}}\n\nmodule.exports = {{ reproduce }};\n"
TEMPLATES: Dict[str, Callable[[str, str], str]] = dict([('CWE-78', _cwe_78), ('CWE-94', _cwe_94), ('CWE-502', _cwe_502), ('CWE-22', _cwe_22), ('CWE-918', _cwe_918), ('CWE-89', _cwe_89), ('CWE-601', _cwe_601), ('CWE-787', _cwe_787)])
SUPPORTED_CWES: List[str] = sorted(TEMPLATES.keys())
from typing import Union

def run(args: argparse.Namespace) -> Dict[str, Union[str, List[str]]]:
    """Generate a PoC scaffolding envelope from parsed CLI-style arguments.

    ``args`` is an ``argparse.Namespace`` carrying ``cwe_type``,
    ``library_name`` and ``vuln_description``. The CWE is normalized
    (trimmed/upper-cased), the library is trimmed, and an empty/missing
    description is defaulted. On success a stable ``status='ok'`` envelope is
    returned; an unsupported CWE yields a ``status='error'`` envelope. This
    function is pure and deterministic -- no I/O, clock, or randomness.
    """
    cwe = _normalize_cwe(getattr(args, 'cwe_type', ''))
    library = _normalize_library(getattr(args, 'library_name', ''))
    description = _normalize_description(getattr(args, 'vuln_description', None), library)
    builder = TEMPLATES.get(cwe)
    if builder is None:
        return {'status': 'error', 'error': f'Unsupported CWE type: {cwe}', 'supported_cwes': SUPPORTED_CWES}
    poc_template = builder(library, description)
    instructions = [f'Save the emitted scaffolding to a file such as poc_{library}.js.', f'Install {library} in an isolated sandbox you are authorized to test.', 'Replace each `<...>` sink comment with the real vulnerable API call.', 'Run the PoC only in that sandbox and capture the observed impact.']
    return {'status': 'ok', 'cwe': cwe, 'library': library, 'description': description, 'poc_template': poc_template, 'instructions': instructions}

def _normalize_cwe(raw: object) -> str:
    """Normalize a CWE identifier: strip surrounding whitespace, upper-case."""
    return str(raw or '').strip().upper()

def _normalize_library(raw: object) -> str:
    """Normalize a library name by stripping surrounding whitespace."""
    return str(raw or '').strip()

def _normalize_description(raw: object, library: str) -> str:
    """Strip the description; fall back to a default referencing the library."""
    text = '' if raw is None else str(raw).strip()
    if not text:
        return f'Vulnerability in {library}'
    return text
'Pure, stdlib-only generator of JavaScript/Node.js PoC scaffolding strings.\n\nThis module is a deterministic *emitter* of proof-of-concept template strings\nfor huntr.com style vulnerability submissions. It performs NO network, LLM,\nsubprocess, clock, or exploit execution of any kind: every public entry point\nsimply formats a static string from its arguments and returns it.\n\nPublic surface (frozen by tests/test_js_poc_templates.py):\n\n* ``TEMPLATES`` -- mapping of ``CWE-XXX`` identifier to a callable\n  ``(library_name: str, vuln_description: str) -> str`` returning JS scaffolding.\n* ``SUPPORTED_CWES`` -- ``sorted(TEMPLATES.keys())``.\n* ``run(args)`` -- normalizes an ``argparse.Namespace`` and returns a stable\n  result envelope dict.\n\nThe module is pure under gate ``pure_fuzz``: it imports only the standard\nlibrary, introduces no non-determinism, and never evaluates attacker payloads.\n'
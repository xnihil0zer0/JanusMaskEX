"""Agy-backed HUNT lead generator for the NobleGreedv2 conductor loop.

The hunt-phase worker (``ngv2.workers.hunt``) expects its ``llm_client`` seam to
be a callable that takes the stage pool (``target``/``context``/...) and returns
``{"candidates": [<finding-shaped dict>, ...]}`` -- NOT the raw chat-completion
``complete(messages=...)`` callable. ``make_hunt_lead_client`` returns exactly
that adapter: it reads a bounded slice of the target repo's source, asks the agy
CLI (via :func:`ngv2.agy_client.make_agy_complete`, so the selection oracle's
``.backend == 'agy'`` contract holds) to enumerate concrete vulnerability
candidates as JSON, and parses the reply into the candidate list.

Each candidate is shaped so the rest of the FSM can act on it: ``title``,
``category``, ``severity``, ``description``, ``evidence`` (``["file:line"]``),
``sink_name``, ``call_sites``, ``expected_signature`` (a literal substring that
must be present in the vulnerable source), plus the detonation oracle hints
``expected_fs_signature`` and ``success_marker``. Missing oracle hints default to
the project-wide markers so a genuine PoC can still be semantically confirmed.

Pure-ish and fail-soft: any error (no repo, agy failure, unparseable reply)
yields ``{"candidates": []}`` rather than raising, so a hunt step degrades to
"no leads" instead of crashing the conductor.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
DEFAULT_SUCCESS_MARKER = 'VULNERABLE'
DEFAULT_FS_SIGNATURE = 'pwned_marker'
_SOURCE_EXTENSIONS = ('.py',)
_MAX_FILES = 40
_MAX_FILE_BYTES = 20000
_MAX_TOTAL_BYTES = 180000
_SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'tests', 'test', 'docs', 'examples', 'build', 'dist', '.tox'}
_SYSTEM = 'You are a senior application-security researcher hunting for HIGH-IMPACT, ATTACKER-REACHABLE vulnerabilities (command/SQL/code injection, SSRF, path traversal, deserialization, auth/IDOR) in the provided source. Only report a vulnerability when a concrete untrusted input reaches a dangerous sink. Do NOT invent issues.'
_INSTRUCTION = 'Return ONLY a JSON array (no prose) of vulnerability candidates. Each item MUST be an object with keys: title, category (a CWE id like \'CWE-89\'), severity (low|medium|high|critical), description, evidence (an array of "relative/path.py:line" strings pointing at the vulnerable line), sink_name (the dangerous call, e.g. \'os.system\'), call_sites (an array of short code strings showing the sink called with untrusted, non-constant input), and expected_signature (a literal substring copied verbatim from the vulnerable source line). Return [] if you find nothing solid.'

def _iter_source(repo: str) -> List[str]:
    """Walk ``repo`` and return a bounded list of 'path
<source>' blocks."""
    blocks: List[str] = []
    total = 0
    if not isinstance(repo, str) or not os.path.isdir(repo):
        return blocks
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and (not d.startswith('.'))]
        for name in files:
            if not name.endswith(_SOURCE_EXTENSIONS):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    continue
                with open(path, 'r', errors='replace') as fh:
                    text = fh.read()
            except Exception:
                continue
            rel = os.path.relpath(path, repo)
            block = '### FILE: {0}\n{1}'.format(rel, text)
            total += len(block)
            blocks.append(block)
            if len(blocks) >= _MAX_FILES or total >= _MAX_TOTAL_BYTES:
                return blocks
    return blocks

def _build_messages(repo: str, target: Any) -> List[Dict[str, str]]:
    blocks = _iter_source(repo)
    corpus = '\n\n'.join(blocks) if blocks else '(no readable source files)'
    user = 'Target: {0}\nRepo root: {1}\n\n{2}\n\n--- SOURCE ---\n{3}\n--- END SOURCE ---'.format(target, repo, _INSTRUCTION, corpus)
    return [{'role': 'user', 'content': user}]

def _extract_json_array(text: str) -> List[Any]:
    """Best-effort parse of a JSON array of candidates from an LLM reply."""
    if not isinstance(text, str) or not text.strip():
        return []
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ('candidates', 'findings', 'results', 'items', 'vulnerabilities'):
                if isinstance(obj.get(key), list):
                    return obj[key]
            return [obj]
    except Exception:
        pass
    match = re.search('\\[.*\\]', text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, list):
                return obj
        except Exception:
            return []
    return []

def _normalize_candidate(raw: Any, index: int, target: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = raw.get('title') or raw.get('name') or raw.get('summary')
    if not title:
        return None
    cand: Dict[str, Any] = dict(raw)
    cand.setdefault('id', 'HUNT-{0:03d}'.format(index + 1))
    cand['title'] = title
    cand.setdefault('category', raw.get('cwe') or 'CWE-000')
    cand.setdefault('severity', 'high')
    cand.setdefault('description', raw.get('detail') or '')
    cand.setdefault('target', target)
    ev = cand.get('evidence')
    if not isinstance(ev, list):
        cand['evidence'] = [str(ev)] if ev else []
    cs = cand.get('call_sites')
    if not isinstance(cs, list):
        cand['call_sites'] = [str(cs)] if cs else []
    cand.setdefault('expected_fs_signature', DEFAULT_FS_SIGNATURE)
    cand.setdefault('success_marker', DEFAULT_SUCCESS_MARKER)
    return cand

def make_hunt_lead_client(*, complete: Optional[Callable[..., str]]=None, max_tokens: int=4096, **agy_kwargs: Any) -> Callable[..., Dict[str, List[Dict[str, Any]]]]:
    """Return the hunt ``llm_client`` adapter ``(**pool) -> {'candidates': [...]}``.

    ``complete`` defaults to :func:`ngv2.agy_client.make_agy_complete` so the
    returned adapter is agy-backed and tagged ``.backend == 'agy'``.
    """
    chat = complete
    if chat is None:
        from ngv2.agy_client import make_agy_complete
        chat = make_agy_complete(**agy_kwargs)

    def lead_client(**pool: Any) -> Dict[str, List[Dict[str, Any]]]:
        ctx = pool.get('context') or pool.get('ctx') or {}
        if not isinstance(ctx, dict):
            ctx = {}
        repo = ctx.get('repo') or pool.get('repo') or ''
        target = pool.get('target') or pool.get('subject') or ctx.get('target') or repo
        codeql_cands = _codeql_leads(repo, target)
        if codeql_cands:
            return {'candidates': codeql_cands}
        try:
            messages = _build_messages(repo, target)
            reply = chat(messages, max_tokens=max_tokens, system=_SYSTEM)
        except Exception:
            return {'candidates': []}
        raw_items = _extract_json_array(reply)
        candidates: List[Dict[str, Any]] = []
        for index, raw in enumerate(raw_items):
            cand = _normalize_candidate(raw, index, target)
            if cand is not None:
                candidates.append(cand)
        if not candidates:
            log = pool.get('log') or (isinstance(ctx, dict) and ctx.get('log')) or None
            try:
                candidates = _fallback_candidates(repo, target, log if callable(log) else None)
            except Exception:
                candidates = []
        return {'candidates': candidates}
    lead_client.backend = 'agy'
    return lead_client
from ngv2 import pattern_scanner
from ngv2 import sink_extract
_FALLBACK_MAX_CANDIDATES = 20
_FALLBACK_CWE_PRIORITY = ('CWE-78', 'CWE-95', 'CWE-502', 'CWE-918', 'CWE-22', 'CWE-89', 'CWE-327', 'CWE-798')

def _fallback_candidates(repo: Any, target: Any, log: Optional[Callable[[str], None]]=None) -> List[Dict[str, Any]]:
    """Deterministic, fail-soft fallback lead source.

    Invoked ONLY when the agy lead call surfaced zero candidates. Runs the
    stdlib :mod:`ngv2.pattern_scanner` over ``repo`` and converts each regex hit
    into a candidate matching the agy candidate shape EXACTLY (same keys
    ``_normalize_candidate`` produces) so downstream triage/poc consume it
    identically. ``sink_name``/``category`` are reconciled via
    :func:`ngv2.sink_extract.extract_sink` on the hit's source line.

    Ordering is TAINT-AWARE: each hit is run through
    :func:`ngv2.sink_localize.localize_sink` over its containing file to decide
    whether the enclosing function actually FORWARDS its parameters into the
    dangerous call. Candidates are ordered by (forwarding confidence, CWE danger
    priority, scanner order) so genuinely callable, taint-forwarding entrypoints
    surface first. Hits proven NON-forwarding (a hardcoded-template sink such as
    triton's ``create_dockerfile_linux``) are DROPPED when
    ``_FALLBACK_DROP_NONFORWARDING`` is set; hits we cannot analyze are kept and
    ranked as ``unknown``. Bounded to the top ``_FALLBACK_MAX_CANDIDATES``; any
    truncation/drop is logged. Any error yields ``[]`` rather than raising.
    """
    if not isinstance(repo, str) or not os.path.isdir(repo):
        return []
    try:
        report = pattern_scanner.scan_directory(repo)
    except Exception:
        return []
    if not isinstance(report, dict):
        return []
    hits = report.get('findings')
    if not isinstance(hits, list) or not hits:
        return []
    enumerated: List[Dict[str, Any]] = []
    dropped = 0
    for order, hit in enumerate(hits):
        if not isinstance(hit, dict):
            continue
        try:
            cand = _candidate_from_hit(hit, target, repo)
        except Exception:
            continue
        if cand is None:
            continue
        confidence = cand.pop('_sink_confidence', 'unknown')
        if _FALLBACK_DROP_NONFORWARDING and confidence == 'low':
            dropped += 1
            continue
        cand['_order'] = order
        cand['_conf_rank'] = _CONFIDENCE_RANK.get(confidence, 1)
        enumerated.append(cand)

    def _prio(cand: Dict[str, Any]) -> int:
        cat = cand.get('category')
        try:
            return _FALLBACK_CWE_PRIORITY.index(cat)
        except ValueError:
            return len(_FALLBACK_CWE_PRIORITY)
    enumerated.sort(key=lambda c: (c.get('_conf_rank', 1), _prio(c), c.get('_order', 0)))
    truncated = False
    if len(enumerated) > _FALLBACK_MAX_CANDIDATES:
        truncated = True
        enumerated = enumerated[:_FALLBACK_MAX_CANDIDATES]
    candidates: List[Dict[str, Any]] = []
    for index, cand in enumerate(enumerated):
        cand.pop('_order', None)
        cand.pop('_conf_rank', None)
        normalized = _normalize_candidate(cand, index, target)
        if normalized is not None:
            candidates.append(normalized)
    if callable(log):
        if dropped:
            try:
                log('hunt fallback: dropped {0} non-forwarding scanner hit(s)'.format(dropped))
            except Exception:
                pass
        if truncated:
            try:
                log('hunt fallback: truncated scanner hits to top {0}'.format(_FALLBACK_MAX_CANDIDATES))
            except Exception:
                pass
    return candidates

def _candidate_from_hit(hit: Dict[str, Any], target: Any, repo: Any=None) -> Optional[Dict[str, Any]]:
    """Convert one ``pattern_scanner`` finding into an agy-shaped raw candidate.

    When ``repo`` is given, the hit is run through
    :func:`ngv2.sink_localize.localize_sink` over its containing file to decide
    taint forwarding: if the enclosing function genuinely forwards a parameter
    into the dangerous call, the candidate's ``sink_symbol`` is set to that
    function (so poc_writer grounds on a real entrypoint) and a transient
    ``_sink_confidence`` of ``'high'`` is attached; if the call is fed only
    literals/globals the confidence is ``'low'`` (caller may drop/deprioritize).
    Localization is fail-soft: any error -> ``'unknown'`` confidence and the
    original (pre-fix) behavior.
    """
    snippet = hit.get('code') or ''
    path = hit.get('file') or ''
    line = hit.get('line')
    category = hit.get('cwe') or 'CWE-000'
    sink_name = ''
    extracted = sink_extract.extract_sink(snippet) if snippet else None
    if extracted is not None:
        sink_name = extracted.get('sink_name') or ''
        category = extracted.get('category') or category
    evidence = '{0}:{1}'.format(path, line) if path else str(line)
    title = '{0} via {1}'.format(category, sink_name or hit.get('id') or 'sink')
    cand: Dict[str, Any] = {'title': title, 'category': category, 'severity': hit.get('severity') or 'high', 'description': hit.get('description') or '', 'evidence': [evidence], 'sink_name': sink_name, 'call_sites': [snippet] if snippet else [], 'expected_signature': snippet, 'cwe': category, 'source': 'pattern_scanner_fallback'}
    confidence = 'unknown'
    symbol = ''
    if _sink_localize is not None and isinstance(repo, str) and path:
        try:
            abs_path = os.path.join(repo, path) if not os.path.isabs(path) else path
            loc = _sink_localize.localize_sink(abs_path, line, sink_name or None)
            if isinstance(loc, dict):
                confidence = loc.get('confidence') or 'unknown'
                symbol = loc.get('symbol') or ''
        except Exception:
            confidence = 'unknown'
            symbol = ''
    if symbol and confidence == 'high':
        cand['sink_symbol'] = symbol
        cand['entrypoint'] = symbol
    cand['_sink_confidence'] = confidence
    if isinstance(repo, str) and path:
        try:
            from ngv2.source_localize import localize_source as _localize_source
            abs_src = os.path.join(repo, path) if not os.path.isabs(path) else path
            _smeta = _localize_source(abs_src, line or 0)
            if isinstance(_smeta, dict) and _smeta.get('kind') == 'http':
                cand['source_meta'] = _smeta
        except Exception:
            pass
    return cand
_FALLBACK_DROP_NONFORWARDING = True
_CONFIDENCE_RANK = {'high': 0, 'unknown': 1, 'low': 2}
try:
    from ngv2 import sink_localize as _sink_localize
except Exception:
    _sink_localize = None

def _codeql_enabled() -> bool:
    """True when CodeQL leads should run: env flag ON (default) AND binary present.

    NGV2_CODEQL_LEADS in {'0','false','no','off'} (case-insensitive) disables;
    unset/anything else leaves it enabled, but it still no-ops when no codeql
    binary can be auto-detected.
    """
    flag = os.environ.get('NGV2_CODEQL_LEADS')
    if flag is not None and flag.strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    try:
        from ngv2 import codeql_lead_source as _cls
        return _cls.codeql_available()
    except Exception:
        return False

def _codeql_leads(repo: Any, target: Any) -> List[Dict[str, Any]]:
    """Run the CodeQL lead source over ``repo``; return agy-shaped candidates.

    Fail-soft and lazy: returns ``[]`` when disabled, no repo, codeql missing, or
    on ANY error so the caller falls through to the agy/regex paths unchanged.
    """
    if not isinstance(repo, str) or not os.path.isdir(repo):
        return []
    if not _codeql_enabled():
        return []
    try:
        from ngv2 import codeql_lead_source as _cls
        findings = _cls.codeql_scan(repo)
        if not findings:
            return []
        return _cls.findings_to_candidates(findings, target)
    except Exception:
        return []
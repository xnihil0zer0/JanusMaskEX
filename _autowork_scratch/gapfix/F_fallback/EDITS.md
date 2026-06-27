# Gap F: agy-empty-hunt deterministic fallback

Target file: `/home/xnihil0zer0/NobleGreedv2/ngv2/hunt_lead_client.py`
Verified against HEAD `e42ac45`. Three exact old->new edit blocks.

## Pinned signatures / shapes
- **agy candidate shape** (`_normalize_candidate(raw, index, target)`): keys
  `id` (`HUNT-NNN`), `title`, `category` (`cwe` fallback), `severity` (`high`),
  `description`, `target`, `evidence` (`["path:line"]`), `call_sites` (list of
  snippet strings), `expected_fs_signature`, `success_marker`. Fallback reuses
  this exact normalizer so shape is byte-identical to the agy path.
- **scanner**: `ngv2.pattern_scanner.scan_directory(root, include_tests=False) -> dict`
  with `findings: [{'id','file','line','code','severity','cwe','owasp','description'}]`,
  sorted `(file,line,id)`.
- **sink extraction**: `ngv2.sink_extract.extract_sink(snippet) -> {'sink_name','category'} | None`.
- **repo dir source**: inside `lead_client`, `repo = ctx.get('repo') or pool.get('repo') or ''`
  (hunt_lead_client.py:138). Already in scope — no threading needed.

## Edit 1 — imports + tunables (after the `Optional` import / before `DEFAULT_SUCCESS_MARKER`)

OLD:
```python
from typing import Optional
DEFAULT_SUCCESS_MARKER = 'VULNERABLE'
DEFAULT_FS_SIGNATURE = 'pwned_marker'
```
NEW:
```python
from typing import Optional
from ngv2 import pattern_scanner
from ngv2 import sink_extract
DEFAULT_SUCCESS_MARKER = 'VULNERABLE'
DEFAULT_FS_SIGNATURE = 'pwned_marker'
_FALLBACK_MAX_CANDIDATES = 20
_FALLBACK_CWE_PRIORITY = ('CWE-78', 'CWE-95', 'CWE-502', 'CWE-918', 'CWE-22', 'CWE-89', 'CWE-327', 'CWE-798')
```

## Edit 2 — fallback builders (inserted directly before `def make_hunt_lead_client`)

OLD:
```python
def make_hunt_lead_client(*, complete: Optional[Callable[..., str]]=None, max_tokens: int=4096, **agy_kwargs: Any) -> Callable[..., Dict[str, List[Dict[str, Any]]]]:
```
NEW:
```python
def _fallback_candidates(repo: Any, target: Any, log: Optional[Callable[[str], None]]=None) -> List[Dict[str, Any]]:
    """Deterministic, fail-soft fallback lead source.

    Invoked ONLY when the agy lead call surfaced zero candidates. Runs the
    stdlib :mod:`ngv2.pattern_scanner` over ``repo`` and converts each regex hit
    into a candidate matching the agy candidate shape EXACTLY (same keys
    ``_normalize_candidate`` produces) so downstream triage/poc consume it
    identically. ``sink_name``/``category`` are reconciled via
    :func:`ngv2.sink_extract.extract_sink` on the hit's source line.

    Ordering is stable (scanner already sorts by ``file,line,id``; we then sort
    by CWE danger priority while preserving that as a tiebreak). Bounded to the
    top ``_FALLBACK_MAX_CANDIDATES``; any truncation is logged. Any error from
    the scanner/extractor yields ``[]`` rather than raising.
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
    for order, hit in enumerate(hits):
        if not isinstance(hit, dict):
            continue
        try:
            cand = _candidate_from_hit(hit, target)
        except Exception:
            continue
        if cand is not None:
            cand['_order'] = order
            enumerated.append(cand)

    def _prio(cand: Dict[str, Any]) -> int:
        cat = cand.get('category')
        try:
            return _FALLBACK_CWE_PRIORITY.index(cat)
        except ValueError:
            return len(_FALLBACK_CWE_PRIORITY)
    enumerated.sort(key=lambda c: (_prio(c), c.get('_order', 0)))
    truncated = False
    if len(enumerated) > _FALLBACK_MAX_CANDIDATES:
        truncated = True
        enumerated = enumerated[:_FALLBACK_MAX_CANDIDATES]
    candidates: List[Dict[str, Any]] = []
    for index, cand in enumerate(enumerated):
        cand.pop('_order', None)
        normalized = _normalize_candidate(cand, index, target)
        if normalized is not None:
            candidates.append(normalized)
    if truncated and callable(log):
        try:
            log('hunt fallback: truncated scanner hits to top {0}'.format(_FALLBACK_MAX_CANDIDATES))
        except Exception:
            pass
    return candidates

def _candidate_from_hit(hit: Dict[str, Any], target: Any) -> Optional[Dict[str, Any]]:
    """Convert one ``pattern_scanner`` finding into an agy-shaped raw candidate."""
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
    return {'title': title, 'category': category, 'severity': hit.get('severity') or 'high', 'description': hit.get('description') or '', 'evidence': [evidence], 'sink_name': sink_name, 'call_sites': [snippet] if snippet else [], 'expected_signature': snippet, 'cwe': category, 'source': 'pattern_scanner_fallback'}

def make_hunt_lead_client(*, complete: Optional[Callable[..., str]]=None, max_tokens: int=4096, **agy_kwargs: Any) -> Callable[..., Dict[str, List[Dict[str, Any]]]]:
```

## Edit 3 — fire fallback only on empty (inside `lead_client`)

OLD:
```python
        for index, raw in enumerate(raw_items):
            cand = _normalize_candidate(raw, index, target)
            if cand is not None:
                candidates.append(cand)
        return {'candidates': candidates}
    lead_client.backend = 'agy'
```
NEW:
```python
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
```

## Verification
- Oracle `test_hunt_fallback.py`: RED on HEAD (2 fail), GREEN after edit (4/4 pass).
- Regression `-k "hunt or lead or pattern or triage or sink_extract"`: 246 passed, 0 fail.
- Import/construct smoke: OK, `.backend == 'agy'` preserved (no circular import).
- Tree restored to pristine; `git status --short` empty.

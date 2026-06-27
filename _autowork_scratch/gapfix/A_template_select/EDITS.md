# Gap A — exact edits to `ngv2/poc_writer.py` (apply to HEAD)

These edits are textually non-overlapping with Gap B (B edits only the
`_py_*` / `_render_js` renderer functions; A edits `__all__`, adds `sink_to_cwe`,
and prepends an override into `_resolve_template`). No new imports needed
(`re`, `Any`, `List`, `Optional` already imported).

## Edit A.1 — extend `__all__`

OLD:
```python
__all__ = ['Grounding', 'CWETemplate', 'PoCArtifact', 'PER_CWE_TEMPLATES', 'get_template', 'default_resolver', 'ground_finding', 'write_poc', 'synthesize', 'draft_poc']
```
NEW:
```python
__all__ = ['Grounding', 'CWETemplate', 'PoCArtifact', 'PER_CWE_TEMPLATES', 'get_template', 'sink_to_cwe', 'default_resolver', 'ground_finding', 'write_poc', 'synthesize', 'draft_poc']
```

## Edit A.2 — add `_SINK_CWE_RULES` + `sink_to_cwe`, and prepend the sink override into `_resolve_template`

OLD:
```python
def _resolve_template(finding: Finding) -> CWETemplate:
    for attr in ('category', 'pattern', 'rule_id'):
        value = getattr(finding, attr, None)
        if value:
            try:
                return get_template(value)
            except KeyError:
                pass
    for attr in ('cwe', 'title', 'description'):
```
NEW:
```python
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
```

Oracle (already in scratch): `test_template_selection_by_sink.py`. Verified by agent A:
RED on HEAD (ImportError sink_to_cwe + dbgpt→CWE-22), GREEN after (11/11 new, 39/39 poc_writer, 122/122 `-k poc`).

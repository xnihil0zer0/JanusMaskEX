---
interfaces: "EDITS existing ngv2/codeql_runner.py to ADD make_subprocess_runner(codeql_bin, *, cwd, timeout)->Runner — the REAL subprocess-backed runner factory that shells the host codeql binary and parses SARIF from stdout, behind the module's existing injected runner(argv)->(rc,out,err,sarif) seam contract; un-orphans codeql_runner onto the live CodeQL path"
dependencies: ["ngv2_codeql_preflight"]
meta_task_type: io_adapter
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/codeql_runner.py — EDIT to ADD the real subprocess-backed runner factory `make_subprocess_runner`, so the orphaned CodeQL adapter can actually shell the host `codeql` binary (the live path), while every existing builder + the module's purity stay unchanged.

# Scope

EDIT the EXISTING module `ngv2/codeql_runner.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2) to ADD ONE new top-level function `make_subprocess_runner`. The module already defines the injected `Runner = Callable[[List[str]], Tuple[int, str, str, Any]]` seam and the `make_mock_runner` / `make_scripted_runner` test doubles; this adds the REAL production factory. The returned `runner(argv)` runs `[codeql_bin] + argv` via `subprocess.run`, and when the argv requests SARIF output (`--format=sarif*`, the format every existing builder uses with `--output=-`) parses the JSON written to stdout into the `sarif` slot — exactly the 4-tuple `create_database` / `run_security_queries` / `verify_taint_path` / `run_custom_spec` expect. `subprocess` and `json` are imported LAZILY inside the runner body so the module's stdlib-only module-scope purity is preserved and the oracle can script `subprocess.run` without ever spawning codeql. Spawn/timeout failures fail closed: `(1, '', <err>, None)`.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — R-ANCHORED PARTIAL EDIT): `make_subprocess_runner` is a NEW top-level symbol. Per the standing rule, a new top-level function must ride as a TRAILING extra node anchored on an existing symbol's patch — DO NOT whole-file re-emit this 174-line module and DO NOT patch any class method. Emit a partial-edit patch that re-emits the EXISTING anchor function `make_scripted_runner` VERBATIM and appends the NEW `make_subprocess_runner` immediately after it, BYTE-FOR-BYTE as follows (both functions, in this order):

```python
def make_scripted_runner(script: Dict[str, Tuple[int, str, str, Any]], default: Tuple[int, str, str, Any]=(0, '', '', None)) -> Runner:
    """Return a runner that dispatches on the first argv token (the verb).

    Unknown verbs deterministically yield *default* and never raise.
    """

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        verb = argv[0] if argv else ''
        return script.get(verb, default)
    return _runner

def make_subprocess_runner(codeql_bin: str='codeql', *, cwd: Optional[str]=None, timeout: Optional[float]=None) -> Runner:
    """Return the REAL subprocess-backed runner that shells the codeql binary.

    The returned callable runs ``[codeql_bin] + argv`` and yields the
    ``(exit_code, stdout, stderr, sarif)`` 4-tuple the module's command builders
    expect: when the argv requests SARIF output (``--format=sarif*``) and the
    process writes JSON to stdout (``--output=-``), that JSON is parsed into the
    ``sarif`` slot; otherwise ``sarif`` is ``None``. ``subprocess`` is imported
    lazily inside the body so this module stays importable with only stdlib at
    module scope and so the oracle can script it without ever spawning codeql.
    """

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        import json as _json
        import subprocess as _subprocess
        full = [codeql_bin] + list(argv)
        try:
            proc = _subprocess.run(full, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:  # spawn/timeout failure -> non-zero, no sarif
            return (1, '', 'codeql subprocess failed: %s' % exc, None)
        sarif: Any = None
        wants_sarif = any(isinstance(a, str) and a.startswith('--format=sarif') for a in argv)
        if wants_sarif and proc.stdout and proc.stdout.strip():
            try:
                sarif = _json.loads(proc.stdout)
            except ValueError:
                sarif = None
        return (proc.returncode, proc.stdout, proc.stderr, sarif)
    return _runner
```

POST-EMIT SELF-CHECK (mandatory): the module still imports only stdlib at module scope (no top-level `subprocess`/`json`); `make_scripted_runner` is byte-identical to before; `make_subprocess_runner` builds `[codeql_bin] + argv`, parses SARIF only for `--format=sarif*`, and returns `(1, '', <err>, None)` on spawn failure; ALL pre-existing functions (`parse_sarif`, `create_database`, `run_security_queries`, `verify_taint_path`, `run_custom_spec`, `make_mock_runner`) are unchanged.

# Non-Goals

Do NOT spawn real codeql in any test. Do NOT change `parse_sarif` or any existing builder/seam — only ADD `make_subprocess_runner`. Do NOT add a top-level `subprocess`/`json` import (lazy-inside-body only). Do NOT touch any other module. Scan-path / FSM INTEGRATION — wiring this factory into the live driver and Stage-2 orchestration — is explicitly OUT OF SCOPE here and is the codeql_orchestrate + driver leaves' responsibility; this leaf only adds the factory and is verified by its unit oracle. ANTI-SEESAW: this edit shares the `codeql_runner` module with the existing oracle tests/test_codeql_runner.py — your `regression_tests` MUST keep the UNION of BOTH tests/test_codeql_runner.py AND the new tests/ngv2/test_codeql_runner_subprocess_factory_wired.py green.

# Inputs

The committed RED oracle tests/ngv2/test_codeql_runner_subprocess_factory_wired.py (4 tests; currently RED — factory absent). With `subprocess.run` monkeypatched (NEVER real codeql) it pins: the factory builds `[codeql_bin] + argv` and parses SARIF from stdout; a non-sarif command yields `sarif=None`; a spawn failure is fail-closed (`rc != 0`, `sarif=None`); and the existing `create_database` + `run_security_queries` builders drive the factory end-to-end (`db == 'repo-python'`, parsed findings). The EXISTING oracle tests/test_codeql_runner.py is the anti-seesaw UNION partner and must remain green (verified: 160 existing oracles incl. this one stay green against the edited module).

# Deliverables

The edited `ngv2/codeql_runner.py` with `make_subprocess_runner` added (anchored after `make_scripted_runner`), verified GREEN by `python3 -m pytest -q tests/ngv2/test_codeql_runner_subprocess_factory_wired.py tests/test_codeql_runner.py`.

# Required plan shape

EXACTLY ONE impl task. task_id VERBATIM: `ngv2_codeql_runner_subprocess_factory`. meta_task_type=`io_adapter` (subprocess seam factory on an existing module — R-anchored partial edit, NOT whole-file). priority: high. dependencies: `["ngv2_codeql_preflight"]` (license gate lands first; no import edge, ordering only). working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/codeql_runner.py"]` ONLY. partial_edit semantics: R-ANCHORED — re-emit `make_scripted_runner` verbatim and append the new `make_subprocess_runner` as a trailing top-level node per the DISPATCH DIRECTIVE (copy that block VERBATIM into `implementation_notes`); never whole-file, never a class-method patch. verification_command: `python3 -m pytest -q tests/ngv2/test_codeql_runner_subprocess_factory_wired.py tests/test_codeql_runner.py` (CWD-relative — NO `cd`). `test_spec.regression_tests` MUST name ≥2 committed cases across the UNION: `test_factory_builds_argv_and_parses_sarif`, `test_existing_builders_drive_the_factory`, plus the existing suite tests/test_codeql_runner.py. `test_spec.edge_cases` (≥2, reflected in test names): `test_factory_non_sarif_command_yields_no_sarif`, `test_factory_failure_is_fail_closed`. `test_spec.integration_test`: `test_existing_builders_drive_the_factory` (the factory driven by the real builders).

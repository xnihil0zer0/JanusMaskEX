"""Narrow-fuzz module for ``meta_task_type="validation"`` (W77b.2).

Discovers candidate validator-like functions in the canary source —
top-level ``def`` matching ``^(validate_|check_|is_)`` — extracts each
function's annotated signature via
:func:`harness.diff_fuzzer.extract_function_signature`, maps Python
type-annotation strings to Hypothesis strategies per the brief §10.2
table, and runs 200 inputs per validator. Returns ``None`` on
pass/skip; on crash, returns an error string that includes the
exception type **and** the shrunken failing input (binding §13).

Per §11.2 reversed default: when the candidate source already defines
embedded ``test_*`` functions (detected via
:func:`harness.embedded_test_runner.should_run_embedded_tests`),
narrow-fuzz returns ``None`` to avoid redundant coverage. The
``RUN_NARROW_FUZZ_ALWAYS=1`` env var, read at module load, overrides
this skip.

Per §10.3 decorator opt-out: validators may carry an
``_narrow_fuzz_meta`` sentinel attribute (``{"skip": True}`` to skip,
``{"timeout": 10.0}`` to override timeout). Discovery uses ``getattr``
with a default of ``{}`` so undecorated validators run with defaults.
"""
from __future__ import annotations
import ast
import os
import re
import traceback
from typing import Any
from typing import Callable
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from harness.diff_fuzzer import extract_function_signature
from harness.embedded_test_runner import should_run_embedded_tests
_VALIDATOR_PREFIX_RE = re.compile('^(validate_|check_|is_)')
_DEFAULT_INPUT_BUDGET = 200
_RUN_ALWAYS: bool = os.environ.get('RUN_NARROW_FUZZ_ALWAYS') == '1'

def _strategy_for_annotation(annotation: str) -> st.SearchStrategy[Any] | None:
    a = annotation.strip()
    if a in ('str', 'builtins.str'):
        return st.text(alphabet=st.characters(blacklist_categories=('Cs',)))
    if a in ('bool', 'builtins.bool'):
        return st.booleans()
    if a in ('int', 'builtins.int'):
        return st.integers()
    if a in ('list', 'List') or a.startswith('list[') or a.startswith('List['):
        return st.lists(st.one_of(st.integers(), st.text(max_size=8), st.none()), max_size=4)
    if a in ('dict', 'Dict') or a.startswith('dict[') or a.startswith('Dict['):
        return st.dictionaries(st.text(max_size=8), st.one_of(st.none(), st.integers(), st.text(max_size=8)), max_size=4)
    return None

def _discover_validators(module_src: str) -> list[str]:
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return []
    return [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and _VALIDATOR_PREFIX_RE.match(node.name)]

def _build_strategies(sig: dict[str, str]) -> dict[str, st.SearchStrategy[Any]] | None:
    strategies: dict[str, st.SearchStrategy[Any]] = {}
    for param, annot in sig.items():
        s = _strategy_for_annotation(annot)
        if s is None:
            return None
        strategies[param] = s
    return strategies

def _exec_module(module_name: str, module_src: str) -> dict[str, Any] | None:
    # Candidate module code must NEVER be exec'd in-process on the host
    # orchestrator. Instead we write the candidate source to a host-level
    # temp dir and run a small command-loop driver in a SEPARATE python
    # subprocess, jailed via bubblewrap when available. All imports here
    # are lazy/in-body so the module surface gains no new top-level symbol
    # or module-level import.
    import json
    import shutil
    import subprocess
    import tempfile
    from harness.agent_jail import build_jail_argv, bwrap_available

    _here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(_here))
    state_dir = os.path.join(repo_root, 'state')
    try:
        os.makedirs(state_dir, exist_ok=True)
    except Exception:
        pass

    # The host temp dir is the only freely-writable surface inside the jail
    # (build_jail_argv ro-binds /usr /bin ... + repo root and binds work_dir
    # writable). Candidate + driver live here.
    work_dir = tempfile.mkdtemp(prefix='narrow_fuzz_')

    class ProxyCallable:
        """Host-side stand-in for a candidate validator function.

        It is callable and carries a real ``_narrow_fuzz_meta`` dict (as
        reported by the subprocess) so the §10.3 skip/timeout opt-out keeps
        working. Each call is forwarded to the running subprocess; a crash
        is re-raised on the host as a dynamically synthesized exception
        whose ``__class__.__name__`` matches the subprocess exception type
        so Hypothesis can shrink it and the error string keeps the name.
        """

        def __init__(self, proc: Any, fname: str, meta: Any) -> None:
            self._proc = proc
            self._fname = fname
            self._narrow_fuzz_meta = meta if isinstance(meta, dict) else {}

        def __call__(self, **kwargs: Any) -> None:
            proc = self._proc
            try:
                payload = json.dumps({'func': self._fname, 'kwargs': kwargs})
            except (TypeError, ValueError):
                return None
            try:
                proc.stdin.write(payload + chr(10))
                proc.stdin.flush()
            except Exception:
                return None
            resp_line = proc.stdout.readline()
            if not resp_line:
                return None
            try:
                resp = json.loads(resp_line)
            except Exception:
                return None
            if resp.get('status') == 'exc':
                exc_name = str(resp.get('exc_type') or 'Exception')
                exc_msg = resp.get('exc_msg', '')
                synthesized = type(exc_name, (Exception,), {})
                raise synthesized(exc_msg)
            return None

    class CleanDict(dict):
        """Namespace mapping returned to ``fuzz``.

        On garbage collection it guarantees the subprocess is terminated
        and the temp work dir is removed, preventing leakage of file
        handles or stale files.
        """

        _proc: Any = None
        _work_dir: Any = None

        def __del__(self) -> None:
            proc = getattr(self, '_proc', None)
            if proc is not None:
                try:
                    if proc.stdin is not None:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            wd = getattr(self, '_work_dir', None)
            if wd:
                shutil.rmtree(wd, ignore_errors=True)

    # Driver script: it puts the workspace dir and the repo root on
    # sys.path, imports candidate, reports discovered callables + their
    # _narrow_fuzz_meta, then services JSON request lines from stdin.
    # ONLY framed JSON lines go to stdout (diagnostics would go to stderr)
    # to avoid stdin/stdout deadlock. Candidate output is isolated from the
    # framed-JSON protocol stream: stdout is redirected to sys.stderr (which
    # is DEVNULL at spawn) around candidate import and every invocation via
    # contextlib.redirect_stdout, so a candidate cannot spoof or corrupt the
    # readline-based messaging stream; only driver-controlled _emit calls,
    # made outside the redirect, reach the real sys.stdout. Uses no
    # backslash escapes; newlines are emitted via chr(10).
    _driver = """import sys, os, json, traceback, contextlib
_WD = os.path.dirname(os.path.abspath(__file__))
if _WD not in sys.path:
    sys.path.insert(0, _WD)
_REPO = __REPO_ROOT__
if _REPO and _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _emit(obj):
    sys.stdout.write(json.dumps(obj) + chr(10))
    sys.stdout.flush()


try:
    with contextlib.redirect_stdout(sys.stderr):
        import candidate
except BaseException as _exc:
    _emit({'status': 'error', 'exc_type': type(_exc).__name__, 'exc_msg': str(_exc)})
    sys.exit(0)

_funcs = {}
for _name in dir(candidate):
    if _name.startswith('__'):
        continue
    _obj = getattr(candidate, _name)
    if callable(_obj):
        _meta = getattr(_obj, '_narrow_fuzz_meta', {})
        if not isinstance(_meta, dict):
            _meta = {}
        _funcs[_name] = _meta

_emit({'status': 'ready', 'functions': _funcs})

for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    try:
        _req = json.loads(_line)
    except Exception:
        continue
    _fn = getattr(candidate, _req.get('func'), None)
    if not callable(_fn):
        _emit({'status': 'ok'})
        continue
    try:
        with contextlib.redirect_stdout(sys.stderr):
            _fn(**_req.get('kwargs', {}))
        _emit({'status': 'ok'})
    except BaseException as _exc:
        _emit({'status': 'exc', 'exc_type': type(_exc).__name__, 'exc_msg': str(_exc), 'tb': traceback.format_exc(limit=3)})
"""
    driver_src = _driver.replace('__REPO_ROOT__', repr(repo_root))

    proc = None
    try:
        with open(os.path.join(work_dir, 'candidate.py'), 'w', encoding='utf-8') as _cf:
            _cf.write(module_src)
        with open(os.path.join(work_dir, 'driver.py'), 'w', encoding='utf-8') as _df:
            _df.write(driver_src)

        # Launch a JAILED subprocess when bubblewrap is available. The
        # interpreter MUST be a bare name resolvable from the jail's
        # ro-bound /usr and /bin (NOT sys.executable, whose venv symlink
        # chain is not bound inside the jail); the driver is referenced by
        # basename and the cwd is the writable temp work dir. build_jail_argv
        # appends the inner command itself, so we MUST NOT append it again,
        # and its repo_root/work_dir/state_dir params are keyword-only. A
        # TypeError here would mean a call-site bug and must NOT be swallowed;
        # the only legitimate fallback is FileNotFoundError (bwrap absent),
        # in which case we run the SAME driver unjailed.
        if bwrap_available():
            try:
                argv = build_jail_argv(['python3', 'driver.py'], repo_root=repo_root, work_dir=work_dir, state_dir=state_dir)
            except FileNotFoundError:
                argv = ['python3', 'driver.py']
        else:
            argv = ['python3', 'driver.py']

        proc = subprocess.Popen(
            argv,
            cwd=work_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            encoding='utf-8',
        )

        status_line = proc.stdout.readline()
        if not status_line:
            raise RuntimeError('candidate driver produced no output')
        status = json.loads(status_line)
        if status.get('status') != 'ready':
            # Import/compile failure inside the candidate -> behave like the
            # old in-process exec failure: return None.
            raise RuntimeError('candidate import failed')
        functions = status.get('functions', {})
        if not isinstance(functions, dict):
            functions = {}
    except Exception:
        if proc is not None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(work_dir, ignore_errors=True)
        return None

    namespace = CleanDict()
    namespace['__name__'] = module_name
    namespace._proc = proc
    namespace._work_dir = work_dir
    for _fname, _meta in functions.items():
        namespace[_fname] = ProxyCallable(proc, _fname, _meta)
    return namespace

def _meta_for(fn: Callable[..., Any]) -> dict[str, Any]:
    meta = getattr(fn, '_narrow_fuzz_meta', None)
    return meta if isinstance(meta, dict) else {}

def _fuzz_one(fn: Callable[..., Any], name: str, strategies: dict[str, st.SearchStrategy[Any]], timeout: float) -> str | None:
    captured: dict[str, Any] = {}

    @settings(max_examples=_DEFAULT_INPUT_BUDGET, deadline=int(timeout * 1000), suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture], print_blob=False)
    @given(**strategies)
    def runner(**kwargs: Any) -> None:
        try:
            fn(**kwargs)
        except Exception as exc:
            captured['input'] = kwargs
            captured['exc_type'] = type(exc).__name__
            captured['exc_msg'] = str(exc)
            captured['tb'] = traceback.format_exc(limit=3)
            raise
    try:
        runner()
    except Exception:
        if not captured:
            return f'{name}: narrow-fuzz failed (no captured input)'
        return f'{captured['exc_type']} on {name} with input {captured['input']!r}: {captured['exc_msg']}'
    return None

def fuzz(module_name: str, module_src: str, *, timeout: float=5.0) -> str | None:
    """Narrow-fuzz the candidate's validator-like functions.
    
        See module docstring for design contract; brief §4.1, §11.2, §13
        are the binding spec.
        """
    if should_run_embedded_tests(module_src) and (not _RUN_ALWAYS):
        return None
    validator_names = _discover_validators(module_src)
    if not validator_names:
        return None
    namespace = _exec_module(module_name, module_src)
    if namespace is None:
        return None
    for name in validator_names:
        fn = namespace.get(name)
        if not callable(fn):
            continue
        meta = _meta_for(fn)
        if meta.get('skip'):
            continue
        try:
            sig = extract_function_signature(module_src, name)
        except Exception:
            continue
        if not sig:
            continue
        strategies = _build_strategies(sig)
        if strategies is None:
            continue
        per_timeout = float(meta.get('timeout', timeout))
        err = _fuzz_one(fn, name, strategies, per_timeout)
        if err is not None:
            return err
    return None
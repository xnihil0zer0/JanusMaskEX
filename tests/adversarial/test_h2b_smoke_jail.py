"""H2B oracle: Route harness/sandbox_smoke.py smoke-import subprocess through the
bubblewrap jail (``harness.agent_jail.build_jail_argv``) when ``agent_sandbox.bwrap``
is enabled.

Final repo path: tests/adversarial/test_h2b_smoke_jail.py

RED on HEAD: ``smoke_import`` launches the smoke subprocess unjailed via
``[sys.executable, '-S', '-c', 'import <module>']`` (harness/sandbox_smoke.py:102),
regardless of the sandbox config. ``test_smoke_import_jailed_when_sandbox_enabled``
asserts the dispatched argv is a bwrap *argv list* (argv[0] == the mocked bwrap path,
``--ro-bind`` present, ``python3`` resolved inside the jail, ``sys.base_prefix`` bound)
and FAILS on HEAD (the recorded argv begins with ``sys.executable``).

GREEN after fix: when sandbox is enabled the smoke command is wrapped via
``agent_jail.build_jail_argv`` into a bwrap argv whose argv[0] is the bwrap binary
and that ro-binds the repo + ``sys.base_prefix`` + the venv site-packages. When the
sandbox is disabled, OR when bwrap is absent on the host (``build_jail_argv`` raises
``FileNotFoundError``), the original unjailed ``sys.executable`` command is used.

NON-vacuity / no silent bwrap-skip: the jailed test mocks ``shutil.which`` ->
``/usr/bin/bwrap`` so ``build_jail_argv`` constructs a real argv WITHOUT bwrap being
installed on the host, then inspects the argv STRUCTURALLY (argv[0] == the mocked
bwrap path, ``--ro-bind`` present, ``sys.base_prefix`` bound). There is no
``pytest.skip``; the wrapping/fallback behaviour is asserted directly.

Mock-target notes (load-bearing -- the fixed body re-imports lazily):
  * The fix reads the sandbox config via ``from harness.orchestrator import
    load_config`` INSIDE the body (mirroring the landed H2A pattern, which mocks
    ``harness.orchestrator.load_config``). So the config is injected by patching
    ``harness.orchestrator.load_config`` -- NOT by mocking ``builtins.open``.
  * ``agent_jail`` is imported lazily ``from harness import agent_jail``; its real
    ``sandbox_enabled`` reads the injected dict and its ``build_jail_argv`` calls
    ``shutil.which('bwrap')`` -- patched here to control jail-construction vs
    fallback without bwrap installed on the host.
  * ``subprocess`` is module-level in ``harness.sandbox_smoke`` -- patch
    ``harness.sandbox_smoke.subprocess.run`` to capture the dispatched argv.
"""
import sys
import unittest.mock as mock

from harness.sandbox_smoke import smoke_import


_BWRAP = "/usr/bin/bwrap"


def _capture_smoke_argv(*, bwrap_enabled, which_return, module_name="test_mymod_h2b"):
    """Drive smoke_import once and return the single dispatched subprocess argv.

    ``bwrap_enabled`` sets ``agent_sandbox.bwrap`` in the injected config;
    ``which_return`` is what ``shutil.which`` yields (a path -> bwrap present,
    ``None`` -> bwrap absent so build_jail_argv raises FileNotFoundError).
    """
    run_calls = []

    def mock_run(argv, *args, **kwargs):
        run_calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    cfg = {"agent_sandbox": {"bwrap": bool(bwrap_enabled)}}

    with mock.patch("harness.sandbox_smoke.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("shutil.which", return_value=which_return):
        smoke_import(module_name, "x = 1")

    assert len(run_calls) == 1, f"Expected exactly 1 subprocess run, got {len(run_calls)}: {run_calls!r}"
    return run_calls[0]


def test_smoke_import_jailed_when_sandbox_enabled():
    """Prove the smoke subprocess is jail-wrapped when sandbox is enabled. RED on HEAD."""
    argv = _capture_smoke_argv(bwrap_enabled=True, which_return=_BWRAP,
                               module_name="test_mymod_h2b_jailed")

    assert isinstance(argv, list), f"Expected list argv, got {type(argv).__name__}: {argv!r}"
    assert argv[0] == _BWRAP, f"Expected argv[0] to be the bwrap binary {_BWRAP!r}, got {argv[0]!r}"
    assert "--ro-bind" in argv, f"Expected --ro-bind (load-bearing repo barrier) in argv, got {argv!r}"
    assert "python3" in argv, f"Expected jail-resolvable 'python3' (not sys.executable) in argv, got {argv!r}"
    assert "import test_mymod_h2b_jailed" in " ".join(argv), \
        f"Expected the candidate import statement in argv, got {argv!r}"
    assert sys.base_prefix in argv, \
        f"Expected sys.base_prefix {sys.base_prefix!r} ro-bound in argv, got {argv!r}"


def test_smoke_import_unjailed_when_sandbox_disabled():
    """Regression guard: sandbox off -> original unjailed sys.executable command, no bwrap."""
    argv = _capture_smoke_argv(bwrap_enabled=False, which_return=_BWRAP,
                               module_name="test_mymod_h2b_unjailed")

    assert isinstance(argv, list), f"Expected list argv, got {type(argv).__name__}: {argv!r}"
    assert argv[0] == sys.executable, \
        f"Expected argv[0] to be sys.executable ({sys.executable!r}), got {argv[0]!r}"
    assert "bwrap" not in " ".join(str(a) for a in argv), f"Expected no bwrap in argv, got {argv!r}"


def test_smoke_import_unjailed_fallback_when_bwrap_missing():
    """Fail-closed: sandbox on but bwrap absent -> FileNotFoundError caught, NO
    unjailed fallback. smoke_import returns a non-None rejection string and
    dispatches no subprocess."""
    run_calls = []

    def mock_run(argv, *args, **kwargs):
        run_calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    cfg = {"agent_sandbox": {"bwrap": True}}

    with mock.patch("harness.sandbox_smoke.subprocess.run", side_effect=mock_run), \
         mock.patch("harness.orchestrator.load_config", return_value=cfg), \
         mock.patch("shutil.which", return_value=None):
        result = smoke_import("test_mymod_h2b_fallback", "x = 1")

    assert len(run_calls) == 0, \
        f"Expected NO subprocess dispatched on fail-closed path, got {run_calls!r}"
    assert isinstance(result, str) and result, \
        f"Expected a non-None rejection string, got {result!r}"

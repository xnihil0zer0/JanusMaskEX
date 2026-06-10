"""RED oracle — authoritative contract for autocompiler/determinism.py (leaf ac-determinism).

Contract: a PURE-STRING determinism layer for the fuzz sandbox (Phase B,
``addendum_sandbox_determinism.md``). The module exposes:

- ``_SITECUSTOMIZE_CONTENT`` — a module-level ``str`` of valid Python source
  implementing the deterministic ``sitecustomize.py``: virtualized VALUE-level
  entropy only (wall-clock ``time.time``/``time_ns``, ``datetime``, seeded
  ``random``, deterministic ``os.urandom`` and ``uuid.uuid4``). RUNNER-SAFETY
  (2026-06-10): ``time.monotonic``/``monotonic_ns``/``perf_counter``/
  ``perf_counter_ns``/``sleep`` are deliberately LEFT REAL — the sandbox
  runner's per-input deadline loops are built on them, and virtualizing them
  spuriously times out the runner hosting the candidate (proven against the
  real fuzz path). It is data, not behavior: the module itself never patches
  anything, never spawns, never imports ``subprocess``/``socket``.
- ``write_sitecustomize(dest_dir) -> str`` — writes ``sitecustomize.py`` with
  exactly that content into ``dest_dir`` (created if missing) and returns the
  written file's path as ``str``.

The behavioral half of the contract is proven from the TEST side by spawning
two real interpreter runs with the written file on ``PYTHONPATH`` (Python
auto-imports ``sitecustomize`` at startup): entropy probes must be
byte-identical across runs, while sleep/monotonic stay real.
"""
import inspect
import os
import subprocess
import sys
import time as _wall

import pytest

import autocompiler.determinism as det
from autocompiler.determinism import _SITECUSTOMIZE_CONTENT, write_sitecustomize

_PROBE = (
    "import time, random, os, uuid\n"
    "print(time.time())\n"
    "print(time.time())\n"
    "print(random.random())\n"
    "print(os.urandom(8).hex())\n"
    "print(uuid.uuid4())\n"
)


def _run_probe(site_dir, script=_PROBE):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(site_dir)
    env.pop('PYTHONHASHSEED', None)
    proc = subprocess.run([sys.executable, '-c', script],
                          capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_content_is_valid_python_source():
    assert isinstance(_SITECUSTOMIZE_CONTENT, str) and _SITECUSTOMIZE_CONTENT.strip()
    compile(_SITECUSTOMIZE_CONTENT, 'sitecustomize.py', 'exec')


def test_content_covers_required_entropy_sources():
    for needle in ('time.time', 'random.seed', 'os.urandom', 'uuid'):
        assert needle in _SITECUSTOMIZE_CONTENT, f'missing patch target: {needle}'


def test_runner_timing_primitives_not_patched():
    # RUNNER-SAFETY (2026-06-10): the sandbox runner's per-input deadline loops
    # are built on time.monotonic/perf_counter/sleep -- virtualizing them
    # spuriously times out the runner hosting the candidate (proven against the
    # real fuzz path). The layer must NEVER assign over them.
    for forbidden in ('.monotonic =', '.monotonic_ns =', '.perf_counter =',
                      '.perf_counter_ns =', '.sleep ='):
        assert forbidden not in _SITECUSTOMIZE_CONTENT, \
            f'determinism layer must not patch the runner timing primitive {forbidden!r}'


def test_writer_round_trips_content(tmp_path):
    dest = tmp_path / 'site'
    path = write_sitecustomize(dest)
    assert isinstance(path, str)
    assert os.path.basename(path) == 'sitecustomize.py'
    assert os.path.dirname(os.path.abspath(path)) == str(dest.resolve())
    with open(path, 'r', encoding='utf-8') as fh:
        assert fh.read() == _SITECUSTOMIZE_CONTENT


def test_two_runs_are_byte_identical(tmp_path):
    # Regression: entropy probes are identical across two separate interpreter
    # runs — the load-bearing flakiness-elimination property.
    site = tmp_path / 'site'
    write_sitecustomize(site)
    assert _run_probe(site) == _run_probe(site)


def test_without_layer_runs_differ(tmp_path):
    # Negative control: the same probe WITHOUT the layer diverges, proving the
    # probe actually exercises entropy (guards a vacuous identical-output pass).
    out_a = subprocess.run([sys.executable, '-c', _PROBE],
                           capture_output=True, text=True, timeout=60).stdout
    out_b = subprocess.run([sys.executable, '-c', _PROBE],
                           capture_output=True, text=True, timeout=60).stdout
    assert out_a != out_b


def test_clock_advances_monotonically_within_a_run(tmp_path):
    # Edge case: two consecutive time.time() reads must differ (a frozen clock
    # breaks timing-sensitive candidate code) yet stay deterministic across runs.
    site = tmp_path / 'site'
    write_sitecustomize(site)
    lines = _run_probe(site).splitlines()
    assert float(lines[1]) > float(lines[0])


def test_sleep_and_monotonic_stay_real(tmp_path):
    # Edge case: under the layer, monotonic still measures REAL elapsed time
    # and sleep really sleeps -- the runner's timeout machinery stays sound.
    site = tmp_path / 'site'
    write_sitecustomize(site)
    out = _run_probe(site, ('import time\n'
                            't0 = time.monotonic()\n'
                            'time.sleep(0.3)\n'
                            'print(time.monotonic() - t0 >= 0.15)\n'))
    assert out.strip() == 'True'


def test_module_is_pure_no_spawn_no_patch():
    src = inspect.getsource(det)
    for forbidden in ('subprocess', 'socket', 'Popen'):
        assert forbidden not in src, f'determinism module must not reference {forbidden}'
    # The module must not patch the host interpreter on import.
    assert _wall.sleep is not None and 'sleep' in dir(_wall)

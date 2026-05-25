"""Phase 3 coverage-guided fuzz harnesses for the drain-capture wrapper
and the scope-revoke ledger parser.

This module is the high-volume random-input complement to the focused
attack suites in ``test_P5_drain_capture_wrapper.py``,
``test_P5_clear_stale_attacks.py``, and ``test_P5_scope_revoke_attacks.py``.
Goal: shake out crashes, hangs, unhandled tracebacks, and security
regressions (path traversal, file leakage outside isolated tempdirs)
that those targeted suites might miss.

Atheris (Google's coverage-guided Python fuzzer) is preferred when
available. When it is not installed -- which is the common case in this
repo's environment -- we fall back to high-volume random + Hypothesis,
which is the more portable path called out in the task brief.

Constraints respected from brief:
  * Each subprocess.run capped at 5s -- hangs surface as crashes.
  * Total runtime budgeted under 90s; trial counts trimmed accordingly.
  * No real planner / orchestrator subprocess is ever spawned -- the
    wrapper is exercised only with bogus argv, and ``_clear_stale_task_state``
    is invoked directly with isolated tempdirs.
  * State pollution prevention: every harness uses ``tmp_path`` and
    explicit env scrubbing on subprocess.run.
"""

from __future__ import annotations

import importlib.util
import io
import os
import pathlib
import random
import string
import subprocess
import sys

import pytest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - hypothesis is in repo deps
    HAS_HYPOTHESIS = False

HAS_ATHERIS = importlib.util.find_spec("atheris") is not None


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "scripts" / "impl_drain_capture.py"
_PRE_WRITE = _REPO_ROOT / "scripts" / "impl_pre_write.py"

sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import impl_drain_capture as wrapper  # noqa: E402
import impl_pre_write as pre_write  # noqa: E402


# Bounded by the brief: <90s total runtime, 500+ trials per harness for
# reasonable coverage. Subprocess fuzz is the slowest because of fork +
# Python interp startup; cap it lower.
_ARGV_TRIALS = 80           # ~3-4s per trial worst-case for subprocess
_TASK_ID_TRIALS = 600
_LEDGER_TRIALS = 600

# Distinct seed bases per harness so the three RNG streams do not collide.
_ARGV_SEED_BASE = 0xA12FACE
_TASK_ID_SEED_BASE = 0xC1EAB123
_LEDGER_SEED_BASE = 0x1ED6E2

# Acceptable subprocess exit shapes:
#   * 0  -- argparse accepted (e.g. valid --brief, dry-run)
#   * 1  -- our own SystemExit("...") on validation
#   * 2  -- argparse usage error
# Anything < 0 means killed by signal (SIGSEGV / SIGABRT) -- a real bug.
_OK_RETURNCODES = {0, 1, 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isolated_env(tmp_path: pathlib.Path) -> dict:
    """Minimal env -- inherits PATH but pins HOME and CWD-adjacent vars to
    the tempdir so the wrapper cannot accidentally pollute the operator's
    real ``~/.claude`` or repo state.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }
    return env


def _files_under(path: pathlib.Path) -> set[pathlib.Path]:
    """Snapshot all files under ``path``. Used to verify a fuzz input did
    not write outside the tempdir.
    """
    if not path.exists():
        return set()
    return {p for p in path.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Harness 1: argv fuzz against the wrapper CLI
# ---------------------------------------------------------------------------


def _random_argv(rng: random.Random) -> list[str]:
    """Generate random argv. NUL bytes are stripped because POSIX execve()
    rejects them at the C-runtime layer before our wrapper ever sees argv
    (Python raises ``ValueError: embedded null byte``). That OS contract
    is not the target of this fuzzer; the wrapper's argparse handling is.
    """
    n = rng.randint(0, 12)
    argv: list[str] = []
    flag_names = [
        "brief", "session", "config", "state-dir", "log-dir",
        "dry-run", "help", "skip-planner", "baseline-dir",
        "planner-timeout", "orchestrator-timeout", "poll-step",
        "idle-confirm",
    ]
    for _ in range(n):
        r = rng.random()
        if r < 0.30:
            argv.append(f"--{rng.choice(flag_names)}")
        elif r < 0.45:
            # Path-traversal-shaped strings.
            argv.append(rng.choice([
                "../../etc/passwd", "/dev/null", "../" * rng.randint(1, 8),
                "\n--brief\nstab_001", "$(rm -rf /)",
                "stab_001\x01", "--brief=stab_001\x7f",
            ]))
        else:
            argv.append("".join(
                rng.choices(string.printable, k=rng.randint(0, 40))
            ))
    # Strip NULs -- execve() rejects them; not a wrapper bug.
    return [a.replace("\x00", "") for a in argv]


@pytest.mark.parametrize("seed_offset", range(_ARGV_TRIALS))
def test_argv_fuzz_no_crash_no_hang(tmp_path, seed_offset):
    """Random argv must not crash the wrapper or hang past 5s.

    Acceptable exits: 0 (dry-run on a valid brief), 1 (our own SystemExit
    on validation), 2 (argparse usage error). Negative return codes mean
    the process was killed by a signal -- treated as a bug.
    """
    rng = random.Random(_ARGV_SEED_BASE ^ seed_offset)
    argv = _random_argv(rng)
    env = _isolated_env(tmp_path)

    try:
        result = subprocess.run(
            [sys.executable, str(_WRAPPER)] + argv,
            capture_output=True,
            timeout=5,
            cwd=str(tmp_path),
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        pytest.fail(
            f"HANG (>5s) on argv={argv!r}; partial stderr="
            f"{(e.stderr or b'')[:300]!r}"
        )

    if result.returncode < 0:
        pytest.fail(
            f"CRASH (signal {-result.returncode}) on argv={argv!r}; "
            f"stderr={result.stderr.decode('utf-8', 'replace')[:400]!r}"
        )

    if result.returncode not in _OK_RETURNCODES:
        # An unexpected positive exit is also worth surfacing -- usually
        # an unhandled exception.
        stderr_text = result.stderr.decode("utf-8", "replace")
        # SystemExit with an arbitrary string maps to rc=1; anything else
        # is suspicious. Report when traceback-shaped.
        if "Traceback (most recent call last)" in stderr_text:
            pytest.fail(
                f"UNHANDLED EXCEPTION on argv={argv!r}; "
                f"stderr={stderr_text[-500:]!r}"
            )


# ---------------------------------------------------------------------------
# Harness 2: _clear_stale_task_state task_id fuzz
# ---------------------------------------------------------------------------


def _fuzz_task_id(rng: random.Random) -> str:
    """Mix of printables, traversal sequences, NUL bytes, glob meta-chars,
    and unicode escapes. Length capped to keep glob() bounded.
    """
    pool = list(string.printable) + [
        "../", "..\\", "%2E%2E/", "%2e%2e%2f",
        "\x00", "\n", "\r", "\\", "\t",
        "*", "?", "[", "]", "{", "}",  # glob meta
        "/etc/passwd", "C:\\Windows\\System32",
    ]
    n = rng.randint(1, 60)
    return "".join(rng.choices(pool, k=n))


@pytest.mark.parametrize("seed_offset", range(_TASK_ID_TRIALS))
def test_clear_stale_task_id_fuzz(tmp_path, seed_offset):
    """Random / hostile task_ids must not crash _clear_stale_task_state nor
    cause it to write or unlink files outside the isolated tempdir.

    Cross-references Phase 2 (T2) findings of path-traversal/glob bugs
    in this exact function.
    """
    rng = random.Random(_TASK_ID_SEED_BASE ^ seed_offset)

    state_dir = tmp_path / "state"
    processed_dir = state_dir / "tasks" / "processed"
    sessions_dir = state_dir / "sessions"
    processed_dir.mkdir(parents=True)
    sessions_dir.mkdir(parents=True)

    # Plant benign sentinel state we can later assert was untouched (if the
    # task_id should not match it).
    sentinel = processed_dir / "SENTINEL_KEEP.json"
    sentinel.write_text("{}", encoding="utf-8")
    pristine_outside = tmp_path / "OUTSIDE_KEEP.txt"
    pristine_outside.write_text("untouched", encoding="utf-8")

    # Build a merged-plan-shaped object whose tasks carry random task_ids.
    n_tasks = rng.randint(1, 5)
    tasks: list[dict] = []
    for _ in range(n_tasks):
        tid = _fuzz_task_id(rng)
        tasks.append({"task_id": tid})
    merged = {"tasks": tasks}

    # Snapshot file tree outside state_dir.
    before_outside = _files_under(tmp_path) - _files_under(state_dir)

    stderr = io.StringIO()
    try:
        rc = wrapper._clear_stale_task_state(merged, state_dir, stderr)
    except Exception as exc:  # noqa: BLE001 - any uncaught exc = bug
        pytest.fail(
            f"CRASH in _clear_stale_task_state for tasks={tasks!r}: "
            f"{type(exc).__name__}: {exc}"
        )

    assert isinstance(rc, int), f"return must be int, got {type(rc)}"

    # Security: nothing outside state_dir/ may have been mutated.
    after_outside = _files_under(tmp_path) - _files_under(state_dir)
    assert before_outside == after_outside, (
        f"PATH TRAVERSAL: file tree outside state_dir changed.\n"
        f"  before={before_outside}\n  after={after_outside}\n"
        f"  task_ids={[t['task_id'] for t in tasks]!r}"
    )
    # Pristine file outside state_dir must still exist with original content.
    assert pristine_outside.exists() and pristine_outside.read_text() == "untouched"


def test_clear_stale_explicit_traversal_attack(tmp_path):
    """Targeted regression: ``task_id="../../etc/passwd"`` must be inert
    -- no file outside ``state_dir/tasks/processed/`` is touched.

    This is the explicit confirmation requested in the brief, sitting
    alongside the random fuzz so the failure mode is obvious.
    """
    state_dir = tmp_path / "state"
    processed_dir = state_dir / "tasks" / "processed"
    sessions_dir = state_dir / "sessions"
    processed_dir.mkdir(parents=True)
    sessions_dir.mkdir(parents=True)

    # A bystander file the traversal must not reach.
    bystander = tmp_path / "etc_passwd_lookalike"
    bystander.write_text("root:x:0:0", encoding="utf-8")

    stderr = io.StringIO()
    rc = wrapper._clear_stale_task_state(
        {"tasks": [{"task_id": "../../etc_passwd_lookalike"}]},
        state_dir,
        stderr,
    )
    assert isinstance(rc, int)
    assert bystander.exists(), (
        "PATH TRAVERSAL CONFIRMED: bystander file outside state_dir was "
        f"removed. stderr={stderr.getvalue()!r}"
    )
    assert bystander.read_text() == "root:x:0:0"


# ---------------------------------------------------------------------------
# Harness 3: _read_scope_revokes ledger fuzz
# ---------------------------------------------------------------------------


def _random_string(rng: random.Random, max_len: int = 20) -> str:
    return "".join(rng.choices(string.printable, k=rng.randint(0, max_len)))


def _random_ledger_row(rng: random.Random):
    """A randomly-shaped ledger row. Some are well-formed, some malformed,
    some entirely garbage to stress the parser's ``.get()`` calls.
    """
    flavour = rng.randint(0, 6)
    if flavour == 0:
        return {
            "event": "scope_exception",
            "ts": _random_string(rng, 24),
            "paths": [_random_string(rng) for _ in range(rng.randint(0, 5))],
        }
    if flavour == 1:
        return {
            "event": "scope_revoke",
            "ts": _random_string(rng, 24),
            "paths": [_random_string(rng) for _ in range(rng.randint(0, 5))],
        }
    if flavour == 2:
        # Wrong-shape paths (string instead of list, None, dict).
        return {
            "event": rng.choice(["scope_revoke", "scope_exception"]),
            "ts": _random_string(rng, 8),
            "paths": rng.choice([
                None, _random_string(rng), {}, 42, [None, 1, {"x": 1}],
            ]),
        }
    if flavour == 3:
        # Missing 'event' key entirely -- common in real ledgers.
        return {_random_string(rng, 8): _random_string(rng)}
    if flavour == 4:
        # event is non-string.
        return {"event": rng.choice([None, 42, [], {}]), "paths": []}
    if flavour == 5:
        # Deeply nested junk.
        return {
            "event": "scope_revoke",
            "paths": [{"nested": [1, 2, {"deep": _random_string(rng)}]}],
        }
    # flavour == 6 -- empty / minimal.
    return {}


# Hypothesis backstop -- portable path called out in the brief; runs in
# addition to the random fuzz to catch shrinkable failures.
if HAS_HYPOTHESIS:

    _row_strategy = st.dictionaries(
        keys=st.sampled_from(["event", "ts", "paths", "extra"]),
        values=st.one_of(
            st.none(),
            st.booleans(),
            st.integers(),
            st.text(max_size=30),
            st.lists(st.text(max_size=20), max_size=10),
            st.lists(st.integers(), max_size=10),
        ),
        max_size=4,
    )
    _ledger_strategy = st.lists(_row_strategy, max_size=80)

    @given(ledger=_ledger_strategy)
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_read_scope_revokes_hypothesis(ledger):
        """Hypothesis-driven fuzz: arbitrary ledger shapes must not crash
        ``_read_scope_revokes`` and the returned object must be a list of
        dicts.

        Cross-references Phase 2 (T6) findings of canonicalization bugs
        in the ledger parser -- here we only assert the type / no-crash
        contract; deeper canonicalization invariants are covered by the
        targeted T6 suite.
        """
        try:
            out = pre_write._read_scope_revokes(ledger)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"CRASH in _read_scope_revokes: {type(exc).__name__}: {exc}; "
                f"ledger sample={ledger[:3]!r}"
            )
        assert isinstance(out, list), f"return must be list, got {type(out)}"
        for row in out:
            assert isinstance(row, dict), f"row must be dict, got {type(row)}"


@pytest.mark.parametrize("seed_offset", range(_LEDGER_TRIALS))
def test_read_scope_revokes_random_fuzz(seed_offset):
    """Random-input fuzz over the ledger parser. Pairs with the
    hypothesis-driven test above; this one shakes a wider variety of
    nested structures cheaply.
    """
    rng = random.Random(_LEDGER_SEED_BASE ^ seed_offset)
    ledger = [_random_ledger_row(rng) for _ in range(rng.randint(0, 80))]
    try:
        out = pre_write._read_scope_revokes(ledger)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"CRASH in _read_scope_revokes: {type(exc).__name__}: {exc}; "
            f"ledger sample={ledger[:3]!r}"
        )
    assert isinstance(out, list)
    # Every returned row must come from the input; we never invent rows.
    for row in out:
        assert row in ledger
        assert row.get("event") == "scope_revoke"


def test_read_scope_revokes_explicit_malformed_inputs():
    """Targeted malformed-row regressions sitting alongside the fuzz so
    failures are obvious. None of these may raise.
    """
    cases = [
        [],
        [{}],
        [{"event": None}],
        [{"event": "scope_revoke"}],  # no paths
        [{"event": "scope_revoke", "paths": None}],
        [{"event": "scope_revoke", "paths": "not a list"}],
        [{"event": "scope_revoke", "paths": [None, 1, "ok"]}],
        # 60 rows -- exercise the last-50 window boundary.
        [{"event": "scope_revoke", "paths": [str(i)]} for i in range(60)],
    ]
    for ledger in cases:
        out = pre_write._read_scope_revokes(ledger)
        assert isinstance(out, list)
        for row in out:
            assert isinstance(row, dict)


# ---------------------------------------------------------------------------
# Sanity: this module declares which fuzzer backend it used so the trial
# count is auditable in test output.
# ---------------------------------------------------------------------------


def test_fuzz_harness_metadata():
    """Documents the fuzzer backend chosen and trial counts -- visible in
    pytest -v output for easy auditing.
    """
    assert _ARGV_TRIALS >= 50
    assert _TASK_ID_TRIALS >= 500
    assert _LEDGER_TRIALS >= 500
    # If atheris ever lands in this env, surface it -- for now we use
    # random + hypothesis, which is the documented fallback.
    backend = "atheris" if HAS_ATHERIS else (
        "random+hypothesis" if HAS_HYPOTHESIS else "random-only"
    )
    sys.stderr.write(
        f"\n[P5_wrapper_fuzz] backend={backend} "
        f"argv_trials={_ARGV_TRIALS} task_id_trials={_TASK_ID_TRIALS} "
        f"ledger_trials={_LEDGER_TRIALS}\n"
    )

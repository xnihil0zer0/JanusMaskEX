"""Phase-3 mutation testing for the persist-time AST gate (Blocker #8).

Method: hand-craft 20-30 mutations of the three target files, apply each,
run the existing P2 persist-gate test suite, record kill/survive, revert.
Surviving mutants reveal test-suite gaps.

Targets:
  - harness/hooks/rpc/submit_code.py::ensure_valid + AstValidationError
  - harness/hooks/claude/post_tool.py::_persist_submission gate logic
  - harness/hooks/gemini/post_tool.py::_persist_submission gate logic

Existing suite under evaluation:
  - tests/adversarial/test_P2_rpc_submit_persist_gate.py (16 tests)
  - tests/adversarial/test_P2_persist_gate_attacks.py (37 tests)

Each test below applies exactly one mutation, runs the suite as a sub-
process, and asserts that the suite FAILS (killed mutant). A passing
suite under mutation = surviving mutant = test gap.

Safety contract:
  * try/finally ALWAYS restores the original source even on KeyboardInterrupt
  * fingerprint check before mutation: original_text == current_text
    (aborts if another agent edited concurrently)
  * cleanup-sentinel test asserts files are byte-identical on teardown
  * F5 crash-recovery hardening (see module-bottom pytest_sessionstart
    / pytest_sessionfinish hooks + _install_crash_recovery()):
      - At session start, snapshot the twin post_tool.py bytes to an
        on-disk JSON sidecar keyed by PID. If a stale sidecar from a
        previous crashed run exists AND the on-disk hooks differ from
        that snapshot, restore from it (handles SIGKILL -- we can't
        catch SIGKILL, but the NEXT pytest invocation cleans up).
      - ``atexit.register()`` + SIGTERM/SIGINT handlers restore the
        snapshot on normal process teardown and catchable signals.
      - ``pytest_sessionfinish`` deletes the sidecar on clean exit.
    SIGKILL cannot be caught -- the on-disk sidecar is the only path
    that covers it. Limitation explicitly acknowledged here.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
from typing import Callable

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBMIT_PATH = REPO_ROOT / "harness" / "hooks" / "rpc" / "submit_code.py"
CLAUDE_PATH = REPO_ROOT / "harness" / "hooks" / "claude" / "post_tool.py"
GEMINI_PATH = REPO_ROOT / "harness" / "hooks" / "gemini" / "post_tool.py"

EVAL_SUITES = [
    "tests/adversarial/test_P2_rpc_submit_persist_gate.py",
    "tests/adversarial/test_P2_persist_gate_attacks.py",
]

# Module-level lock to guarantee serial mutation application (prevents
# two tests in this file mutating the same file simultaneously, which
# would break the snapshot-restore contract).
_MUTATION_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# F5 crash-recovery hardening
# ---------------------------------------------------------------------------
#
# Prior incident (ledger 2026-04-20T14:58:00Z, drain #6): a crashed pytest
# process left harness/hooks/claude/post_tool.py and harness/hooks/gemini/
# post_tool.py with mid-mutation payloads ("mutated_reason_g", inverted
# severity filter, etc.), contaminating subsequent drains and CI.
#
# Strategy: hybrid Option A + Option C (session-scoped).
#   1. At session start, snapshot the twin post_tool.py bytes to a JSON
#      sidecar under state/hooks/, keyed by PID. The sidecar also stores
#      the submit_code.py bytes for defence-in-depth (it's in the same
#      mutation path, though corruption there hasn't been observed).
#   2. Register ``atexit.register`` + SIGTERM / SIGINT handlers that
#      restore from the in-memory snapshot and delete the sidecar.
#      SIGKILL is explicitly NOT catchable: see man 7 signal.
#   3. ``pytest_sessionfinish`` does the same + deletes the sidecar.
#   4. At session start ALSO: scan for stale sidecars from a previous
#      crashed run (including SIGKILL). If a sidecar exists whose snapshot
#      differs from the current on-disk hook bytes, that's evidence that
#      the previous run died mid-mutation; restore from the stale
#      sidecar. This gives us SIGKILL coverage at the cost of one-run
#      delay (cleanup happens at the NEXT pytest invocation).
#
# Scoped strictly to the three files tracked by this test. No git
# operations -- in-memory byte snapshot only, so we cannot clobber
# unrelated operator edits outside harness/hooks/.

_SIDECAR_DIR = REPO_ROOT / "state" / "hooks"
_SIDECAR_PREFIX = "mutation_kill_snapshot_"
_TRACKED_FILES: list[pathlib.Path] = [SUBMIT_PATH, CLAUDE_PATH, GEMINI_PATH]

# Populated by _install_crash_recovery(); kept at module scope so the
# atexit / signal handlers can close over it.
_CRASH_RECOVERY_SNAPSHOT: dict[str, str] = {}
_CRASH_RECOVERY_SIDECAR: pathlib.Path | None = None
_CRASH_RECOVERY_INSTALLED = False
# Preserve any previously-registered SIGTERM / SIGINT handler so we chain
# to it after restoring (rather than clobbering operator instrumentation).
_PRIOR_SIGTERM_HANDLER = None
_PRIOR_SIGINT_HANDLER = None


def _sidecar_path_for_pid(pid: int) -> pathlib.Path:
    return _SIDECAR_DIR / f"{_SIDECAR_PREFIX}{pid}.json"


def _write_sidecar(path: pathlib.Path, snapshot: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "snapshot": snapshot}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _restore_from_bytes(snapshot: dict[str, str]) -> None:
    """Best-effort restore. Never raises; the crash-recovery path must
    not itself contribute to state corruption.

    Hardening (2026-04-21, ref closeout defects 2/9/13):
      * HIGH: repo-root ancestry guard — refuse to write outside REPO_ROOT
        even if the sidecar snapshot key is a traversal payload
        (``../../../tmp/...``) or an absolute path.
      * MED: symlink-escape defence — refuse to write through a symlink
        at the target path (``is_symlink`` pre-check + ``O_NOFOLLOW`` on
        the low-level open so a TOCTOU symlink swap still fails with
        ``ELOOP``).
      * LOW: ``parent.mkdir(parents=True, exist_ok=True)`` so a missing
        parent dir (e.g. operator did ``rm -rf harness/hooks/claude/``)
        doesn't silently swallow the restore.
    """
    repo_root_resolved = REPO_ROOT.resolve()
    for rel, text in snapshot.items():
        abs_path = REPO_ROOT / rel
        # HIGH: resolve (strict=False -- target may not yet exist) and
        # assert containment under REPO_ROOT before doing ANY fs op.
        try:
            target_resolved = abs_path.resolve(strict=False)
        except OSError:
            sys.stderr.write(
                f"[F5 crash-recovery] cannot resolve sidecar target "
                f"{abs_path!r}; skipping restore.\n"
            )
            continue
        if not target_resolved.is_relative_to(repo_root_resolved):
            sys.stderr.write(
                f"[F5 crash-recovery] sidecar target {target_resolved} "
                f"escapes REPO_ROOT {repo_root_resolved}; skipping "
                f"restore (rel={rel!r}).\n"
            )
            continue
        # MED (pre-check): symlink at the hook-file location is itself
        # anomalous -- refuse to silently overwrite it via the symlink.
        if abs_path.is_symlink():
            sys.stderr.write(
                f"[F5 crash-recovery] sidecar target {abs_path} is a "
                f"symlink; refusing to follow — skipping restore.\n"
            )
            continue
        try:
            current = abs_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            current = None
        if current == text:
            continue
        # LOW: ensure parent dir exists so write doesn't silently OSError.
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            sys.stderr.write(
                f"[F5 crash-recovery] cannot mkdir parents for {abs_path}; "
                f"sidecar remains for next-run cleanup.\n"
            )
            continue
        # MED (defence-in-depth): low-level open with O_NOFOLLOW defeats a
        # TOCTOU symlink race between the is_symlink pre-check and the
        # write. ELOOP => OSError, swallowed below.
        try:
            fd = os.open(
                str(abs_path),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o644,
            )
        except OSError:
            sys.stderr.write(
                f"[F5 crash-recovery] failed to open {abs_path} with "
                f"O_NOFOLLOW; sidecar remains for next-run cleanup.\n"
            )
            continue
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(text.encode("utf-8"))
        except OSError:
            sys.stderr.write(
                f"[F5 crash-recovery] failed to restore {abs_path}; "
                f"sidecar remains for next-run cleanup.\n"
            )


def _delete_sidecar(path: pathlib.Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except (FileNotFoundError, OSError):
        pass


def _sweep_stale_sidecars() -> None:
    """Restore from any sidecar left behind by a previous crashed run.

    A sidecar is "stale" if:
      - its PID no longer corresponds to a live pytest process, AND
      - at least one tracked file on disk differs from the sidecar's
        snapshot (evidence of mid-mutation crash).

    Detecting "live pytest" across processes is brittle; we instead use
    the simpler rule: any sidecar whose PID != os.getpid() is treated as
    stale, because this sweep runs at session start BEFORE we create our
    own sidecar. If two concurrent pytest runs race, the second will pick
    up the first's sidecar; that's acceptable because the snapshot is
    the *original* HEAD content either way -- restoring it only undoes
    mid-mutation corruption.

    Hardening (2026-04-21): repo-root ancestry guard filters out-of-repo
    snapshot keys BEFORE the drift-probe read, so a malicious sidecar
    with a traversal key can't cause a spurious drift signal that would
    invoke _restore_from_bytes on attacker-chosen paths. Defence in
    depth: _restore_from_bytes also enforces the guard.
    """
    if not _SIDECAR_DIR.exists():
        return
    repo_root_resolved = REPO_ROOT.resolve()
    for sidecar in _SIDECAR_DIR.glob(f"{_SIDECAR_PREFIX}*.json"):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Malformed sidecar -- delete it; we can't trust its snapshot.
            _delete_sidecar(sidecar)
            continue
        snap = payload.get("snapshot") or {}
        if not isinstance(snap, dict):
            _delete_sidecar(sidecar)
            continue
        sidecar_pid = payload.get("pid")
        if sidecar_pid == os.getpid():
            # Shouldn't happen (we haven't created ours yet), but be safe.
            continue
        # HIGH (2026-04-21): filter snapshot entries whose target path
        # escapes REPO_ROOT. Spurious drift on out-of-repo reads would
        # otherwise invoke _restore_from_bytes on attacker-chosen keys.
        safe_snap: dict[str, str] = {}
        for rel, text in snap.items():
            if not isinstance(text, str):
                continue
            abs_path = REPO_ROOT / rel
            try:
                target_resolved = abs_path.resolve(strict=False)
            except OSError:
                continue
            if not target_resolved.is_relative_to(repo_root_resolved):
                sys.stderr.write(
                    f"[F5 crash-recovery] stale sidecar {sidecar.name} "
                    f"contains out-of-repo key {rel!r}; skipping.\n"
                )
                continue
            safe_snap[rel] = text
        # Did the previous run leave any file corrupted?
        any_drift = False
        for rel, text in safe_snap.items():
            abs_path = REPO_ROOT / rel
            try:
                current = abs_path.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                continue
            if current != text:
                any_drift = True
                break
        if any_drift:
            sys.stderr.write(
                f"[F5 crash-recovery] stale sidecar {sidecar.name} detected "
                f"mid-mutation drift in tracked hook files; restoring.\n"
            )
            _restore_from_bytes(safe_snap)
        _delete_sidecar(sidecar)


def _crash_recovery_atexit() -> None:
    if _CRASH_RECOVERY_SNAPSHOT:
        _restore_from_bytes(_CRASH_RECOVERY_SNAPSHOT)
    _delete_sidecar(_CRASH_RECOVERY_SIDECAR)


def _crash_recovery_signal(signum, frame):  # type: ignore[no-untyped-def]
    _crash_recovery_atexit()
    # Chain to any prior handler, then re-raise the default so the
    # process still exits. KeyboardInterrupt for SIGINT; for SIGTERM we
    # just sys.exit since no Python-level exception is idiomatic.
    prior = _PRIOR_SIGINT_HANDLER if signum == signal.SIGINT else _PRIOR_SIGTERM_HANDLER
    if callable(prior) and prior not in (signal.SIG_DFL, signal.SIG_IGN):
        try:
            prior(signum, frame)
            return
        except BaseException:
            pass
    # Reset to default and re-deliver so the parent observes normal
    # termination semantics (exit code 128+signum).
    try:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    except OSError:
        sys.exit(128 + signum)


def _install_crash_recovery() -> None:
    """Idempotent installer. Safe to call multiple times (pytest may
    call pytest_sessionstart once, but the module-import path also
    installs so plain ``python tests/...`` usage is covered)."""
    global _CRASH_RECOVERY_SNAPSHOT, _CRASH_RECOVERY_SIDECAR
    global _CRASH_RECOVERY_INSTALLED
    global _PRIOR_SIGTERM_HANDLER, _PRIOR_SIGINT_HANDLER
    if _CRASH_RECOVERY_INSTALLED:
        return
    _CRASH_RECOVERY_INSTALLED = True

    # First: sweep any stale sidecar from a previous crashed run.
    _sweep_stale_sidecars()

    # Then: take our own snapshot keyed by rel path (so sidecar payload
    # is portable if repo root moves).
    snapshot: dict[str, str] = {}
    for p in _TRACKED_FILES:
        try:
            rel = p.relative_to(REPO_ROOT).as_posix()
            snapshot[rel] = p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
    _CRASH_RECOVERY_SNAPSHOT = snapshot
    _CRASH_RECOVERY_SIDECAR = _sidecar_path_for_pid(os.getpid())
    try:
        _write_sidecar(_CRASH_RECOVERY_SIDECAR, snapshot)
    except OSError:
        # Non-fatal: we still have the in-memory snapshot + atexit.
        _CRASH_RECOVERY_SIDECAR = None

    atexit.register(_crash_recovery_atexit)
    # Install signal handlers only on main thread (signal.signal raises
    # ValueError from non-main threads). Pytest's main-thread guarantee
    # makes this safe at sessionstart; guard anyway for robustness.
    try:
        _PRIOR_SIGTERM_HANDLER = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _crash_recovery_signal)
    except (ValueError, OSError):
        pass
    try:
        _PRIOR_SIGINT_HANDLER = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _crash_recovery_signal)
    except (ValueError, OSError):
        pass


# Install at module import time so crash recovery is active even if
# pytest hooks below fail to fire (e.g. collection error before
# sessionstart). Idempotent.
_install_crash_recovery()


def pytest_sessionstart(session):  # type: ignore[no-untyped-def]
    """Pytest hook: ensure crash-recovery is installed for this session."""
    _install_crash_recovery()


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    """Pytest hook: clean exit -- restore from snapshot (defence-in-depth
    in case any test left drift) and remove the sidecar."""
    if _CRASH_RECOVERY_SNAPSHOT:
        _restore_from_bytes(_CRASH_RECOVERY_SNAPSHOT)
    _delete_sidecar(_CRASH_RECOVERY_SIDECAR)


def _snapshot(paths: list[pathlib.Path]) -> dict[pathlib.Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in paths}


def _verify_snapshot(snap: dict[pathlib.Path, str]) -> None:
    """Abort the mutation if any tracked file has changed since snapshot.

    Concurrent-agent safety: if another agent edited the file between
    the snapshot and now, restoring our snapshot would clobber their
    work. Refuse to mutate.
    """
    for p, text in snap.items():
        current = p.read_text(encoding="utf-8")
        if current != text:
            raise RuntimeError(
                f"concurrent edit detected on {p}; refusing to mutate. "
                f"Re-run when no other agent is editing."
            )


def _restore_snapshot(snap: dict[pathlib.Path, str]) -> None:
    for p, text in snap.items():
        # Only rewrite if changed, to minimise inode churn.
        if p.read_text(encoding="utf-8") != text:
            p.write_text(text, encoding="utf-8")


def _run_eval_suite() -> subprocess.CompletedProcess:
    """Run the persist-gate suites in a fresh subprocess (no module
    cache pollution from this process). Return the CompletedProcess so
    callers can inspect returncode."""
    cmd = [sys.executable, "-m", "pytest", *EVAL_SUITES, "-x", "--tb=no", "-q",
           "--no-header"]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _apply_and_check_killed(
    mutator: Callable[[dict[pathlib.Path, str]], dict[pathlib.Path, str]],
) -> tuple[bool, str]:
    """Apply one mutation across all tracked files, run the suite, restore.

    Returns (killed: bool, summary: str).
    A mutation is "killed" if the eval suite returns non-zero.
    """
    with _MUTATION_LOCK:
        tracked = [SUBMIT_PATH, CLAUDE_PATH, GEMINI_PATH]
        snap = _snapshot(tracked)
        try:
            _verify_snapshot(snap)
            mutated = mutator(snap)
            for p, new_text in mutated.items():
                if new_text == snap[p]:
                    raise AssertionError(
                        f"mutation produced identical text for {p}; "
                        "would be a false positive"
                    )
                p.write_text(new_text, encoding="utf-8")
            result = _run_eval_suite()
            killed = result.returncode != 0
            tail = (result.stdout or b"").decode(errors="replace")[-400:]
            return killed, tail
        finally:
            _restore_snapshot(snap)
            # Defence-in-depth: assert restoration succeeded.
            for p, text in snap.items():
                final = p.read_text(encoding="utf-8")
                assert final == text, (
                    f"FATAL: failed to restore {p} after mutation; "
                    f"original sha={hashlib.sha256(text.encode()).hexdigest()[:8]}, "
                    f"current sha={hashlib.sha256(final.encode()).hexdigest()[:8]}"
                )


# ---------------------------------------------------------------------------
# Sentinel: confirm the harness itself round-trips cleanly.
# ---------------------------------------------------------------------------


class TestZeroSentinel:
    """Run FIRST. Confirms snapshot/restore works and the baseline suite
    passes before we trust any mutation result."""

    def test_aaa_baseline_suite_passes_unmutated(self) -> None:
        result = _run_eval_suite()
        assert result.returncode == 0, (
            f"baseline P2 suite failed before any mutation; "
            f"refusing to interpret kill/survive results.\n"
            f"stdout tail: {(result.stdout or b'').decode()[-400:]}"
        )

    def test_aab_snapshot_restore_idempotent(self) -> None:
        snap = _snapshot([SUBMIT_PATH, CLAUDE_PATH, GEMINI_PATH])
        # Mutate then restore via the harness — verify identical bytes.
        try:
            for p in snap:
                p.write_text(snap[p] + "\n# noise\n", encoding="utf-8")
        finally:
            _restore_snapshot(snap)
        for p, text in snap.items():
            assert p.read_text(encoding="utf-8") == text

    def test_aac_crash_recovery_sidecar_present(self) -> None:
        """The F5 crash-recovery sidecar must exist for this pid after
        import; it is our SIGKILL safety net. If absent (e.g. read-only
        state/hooks/ on CI), the in-memory atexit path still fires but
        SIGKILL coverage is lost -- surface the regression loudly."""
        assert _CRASH_RECOVERY_INSTALLED, "crash-recovery installer did not run"
        if _CRASH_RECOVERY_SIDECAR is None:
            pytest.skip(
                "sidecar path unavailable (likely read-only state/hooks/); "
                "in-memory atexit restore still active but SIGKILL recovery "
                "limited."
            )
        assert _CRASH_RECOVERY_SIDECAR.exists(), (
            f"crash-recovery sidecar missing at {_CRASH_RECOVERY_SIDECAR}; "
            "SIGKILL/SIGSEGV would leave hook files corrupted."
        )


# ---------------------------------------------------------------------------
# Mutation operators
#
# Each test = ONE mutation. Test PASSES => mutant killed (good).
# Test FAILS => surviving mutant = test-suite gap.
# ---------------------------------------------------------------------------


# ---- ensure_valid mutations -----------------------------------------------


class TestEnsureValidMutations:

    def test_m01_remove_raise_on_error(self) -> None:
        """Statement deletion: remove the `raise AstValidationError` —
        gate becomes a no-op. Suite MUST detect."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                'if any(getattr(v, "severity", "") == "error" for v in violations):\n'
                '        raise AstValidationError(violations)\n',
                'if any(getattr(v, "severity", "") == "error" for v in violations):\n'
                '        pass\n',
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m01 (raise->pass): {tail}"

    def test_m02_invert_severity_check(self) -> None:
        """Conditional inversion: `== 'error'` -> `!= 'error'`. Suite MUST detect."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                'if any(getattr(v, "severity", "") == "error" for v in violations):',
                'if any(getattr(v, "severity", "") != "error" for v in violations):',
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m02 (== -> !=): {tail}"

    def test_m03_severity_compare_warning(self) -> None:
        """Constant mutation: 'error' -> 'warning'."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                'if any(getattr(v, "severity", "") == "error" for v in violations):',
                'if any(getattr(v, "severity", "") == "warning" for v in violations):',
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m03 (severity 'error'->'warning'): {tail}"

    def test_m04_invert_allow_nondeterminism(self) -> None:
        """Allow-nondet flip in ensure_valid signature — invert default."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            # Flip BOTH validate() and ensure_valid() defaults so the
            # call inside ensure_valid still composes coherently.
            new = txt.replace(
                "def ensure_valid(\n    code: str, allow_nondeterminism: bool = False, relax_external_constructs: bool = False\n) -> list[Violation]:",
                "def ensure_valid(\n    code: str, allow_nondeterminism: bool = True, relax_external_constructs: bool = False\n) -> list[Violation]:",
            )
            assert new != txt
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m04 (allow_nondet default False->True): {tail}"

    def test_m05_remove_defensive_copy(self) -> None:
        """Defensive copy removal: `list(violations)` -> alias."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "self.violations: list[Violation] = list(violations)",
                "self.violations: list[Violation] = violations",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m05 (defensive copy aliased): {tail}"

    def test_m06_return_empty_instead_of_violations(self) -> None:
        """Return value mutation: `return violations` -> `return []`.
        On the warning-only path this swallows warnings."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            # Target the trailing "return violations" of ensure_valid
            # specifically (not the fall-through of validate()).
            new = txt.replace(
                "        raise AstValidationError(violations)\n    return violations",
                "        raise AstValidationError(violations)\n    return []",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m06 (return violations -> return []): {tail}"

    def test_m07_swap_exception_class(self) -> None:
        """Exception swap: AstValidationError -> ValueError. Callers
        catching the specific class would not see the mutated raise."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "raise AstValidationError(violations)",
                "raise ValueError('boom')",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m07 (AstValidationError -> ValueError): {tail}"

    def test_m08_format_message_off_by_one(self) -> None:
        """Off-by-one in the preview slice."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "if not errors:",
                "if errors:",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m08 (format msg invert errors check): {tail}"

    def test_m09_validate_pass_allow_nondet_inverted(self) -> None:
        """Inside ensure_valid, the call to validate_code passes
        allow_nondeterminism=allow_nondeterminism. Mutate to
        `not allow_nondeterminism`."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "violations = validate_code(\n        code,\n        allow_nondeterminism=allow_nondeterminism,\n        relax_external_constructs=relax_external_constructs,\n    )",
                "violations = validate_code(\n        code,\n        allow_nondeterminism=not allow_nondeterminism,\n        relax_external_constructs=relax_external_constructs,\n    )",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m09 (validate_code allow_nondet inverted): {tail}"

    def test_m10_violations_attr_init_to_empty(self) -> None:
        """AstValidationError.__init__ stores [] regardless of input."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "self.violations: list[Violation] = list(violations)",
                "self.violations: list[Violation] = []",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m10 (violations init -> []): {tail}"


# ---- claude/post_tool _persist_submission mutations -----------------------


class TestClaudePersistSubmissionMutations:

    def test_m11_remove_ensure_valid_call(self) -> None:
        """Statement deletion: comment out ensure_valid call. Then
        the `except AstValidationError` is dead code — unconditional persist."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                "        rpc_submit_code.ensure_valid(content, allow_nondeterminism=allow_nondet)\n"
                "    except rpc_submit_code.AstValidationError as exc:",
                "        pass  # MUTATED: ensure_valid removed\n"
                "    except rpc_submit_code.AstValidationError as exc:",
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m11 (claude ensure_valid removed): {tail}"

    def test_m12_invert_allow_nondet_derivation(self) -> None:
        """`is False` -> `is True` in claude post_tool — mirrors the bug
        where allow_nondet would only enable when constraints already
        say deterministic=True (impossible).

        NOTE (F5): payload refreshed post-cd0125d. The malformed-constraints
        guard pulled the `task.get("constraints", {})` expression into a
        local `constraints = ...` binding (with an isinstance guard) so the
        old chained-get form no longer exists verbatim in source. We now
        target the current binding.
        """
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                'allow_nondet = constraints.get("deterministic") is False',
                'allow_nondet = constraints.get("deterministic") is True',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m12 (claude allow_nondet derivation flipped): {tail}"

    def test_m13_hardcode_allow_nondet_true(self) -> None:
        """Hardcode allow_nondet=True. Bypasses nondet rule entirely.

        NOTE (F5): payload refreshed post-cd0125d (same reason as m12).
        """
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                'allow_nondet = constraints.get("deterministic") is False',
                'allow_nondet = True',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m13 (claude allow_nondet hardcoded True): {tail}"

    def test_m14_remove_return_after_deny(self) -> None:
        """Statement deletion: drop the early `return` in the except block,
        causing the persist code to run AFTER the deny row."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            # Find the 'return' just below the stderr write, inside the
            # claude AstValidationError handler. The text is unique enough.
            old = (
                'sys.stderr.write(f"PostToolUse persist-time AST gate denied submission: {exc}\\n")\n'
                '        return\n'
            )
            new_block = (
                'sys.stderr.write(f"PostToolUse persist-time AST gate denied submission: {exc}\\n")\n'
                '        # MUTATED: return removed\n'
            )
            new = txt.replace(old, new_block)
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m14 (claude return after deny removed): {tail}"

    def test_m15_skip_ledger_emit_on_deny(self) -> None:
        """Comment out the `_ledger.append_hook_event(...)` call inside the
        deny path — deny row is silently swallowed."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            # Replace the call with a no-op, leaving structure intact.
            new = txt.replace(
                "        _ledger.append_hook_event(\n"
                "            session_id,\n"
                "            agent,\n"
                '            "submit_code",\n'
                '            "deny",',
                "        _NOOP = (\n"
                "            session_id,\n"
                "            agent,\n"
                '            "submit_code",\n'
                '            "deny",',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m15 (claude deny ledger row swallowed): {tail}"

    def test_m16_change_reason_string(self) -> None:
        """`'persist_time_ast_gate'` -> `'mutated_reason'`. Tests that
        explicitly assert this string MUST detect."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                '"reason": "persist_time_ast_gate",',
                '"reason": "mutated_reason",',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m16 (claude reason string mutated): {tail}"

    def test_m17_error_count_off_by_one(self) -> None:
        """`error_count: len(errors)` -> `len(errors) - 1`."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                '"error_count": len(errors),',
                '"error_count": len(errors) - 1,',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m17 (claude error_count off-by-one): {tail}"

    def test_m18_severity_filter_inverted_in_persist(self) -> None:
        """Inside _persist_submission the `errors = [v for v in
        exc.violations if v.severity == 'error']` becomes `!= 'error'`."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                'errors = [v for v in exc.violations if getattr(v, "severity", "") == "error"]',
                'errors = [v for v in exc.violations if getattr(v, "severity", "") != "error"]',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m18 (claude severity filter inverted): {tail}"

    def test_m19_violations_payload_truncated(self) -> None:
        """Loop bounds: `for v in errors` -> `for v in errors[:0]`
        (drops all violation dicts from the deny payload)."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                "violation_dicts = [\n"
                '            {"rule": v.rule, "severity": v.severity, "line": v.line, "message": v.message}\n'
                "            for v in errors\n"
                "        ]",
                "violation_dicts = [\n"
                '            {"rule": v.rule, "severity": v.severity, "line": v.line, "message": v.message}\n'
                "            for v in errors[:0]\n"
                "        ]",
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m19 (claude violation_dicts emptied): {tail}"

    def test_m20_swap_outcome_to_allow_in_deny_path(self) -> None:
        """Constant mutation: in the deny ledger row, "deny" -> "allow"."""
        def mutate(snap):
            txt = snap[CLAUDE_PATH]
            new = txt.replace(
                "        _ledger.append_hook_event(\n"
                "            session_id,\n"
                "            agent,\n"
                '            "submit_code",\n'
                '            "deny",',
                "        _ledger.append_hook_event(\n"
                "            session_id,\n"
                "            agent,\n"
                '            "submit_code",\n'
                '            "allow",',
            )
            return {CLAUDE_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m20 (claude deny->allow outcome): {tail}"


# ---- gemini/post_tool _persist_submission mutations -----------------------


class TestGeminiPersistSubmissionMutations:

    def test_m21_remove_ensure_valid_call(self) -> None:
        def mutate(snap):
            txt = snap[GEMINI_PATH]
            new = txt.replace(
                "        rpc_submit_code.ensure_valid(content, allow_nondeterminism=allow_nondet)\n"
                "    except rpc_submit_code.AstValidationError as exc:",
                "        pass  # MUTATED: ensure_valid removed\n"
                "    except rpc_submit_code.AstValidationError as exc:",
            )
            return {GEMINI_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m21 (gemini ensure_valid removed): {tail}"

    def test_m22_invert_allow_nondet_derivation(self) -> None:
        """NOTE (F5): payload refreshed post-cd0125d. The cd0125d
        malformed-constraints guard introduced a `constraints = ...`
        local binding in gemini/post_tool.py (mirroring the claude twin),
        so the previous chained-get pattern no longer appears in source."""
        def mutate(snap):
            txt = snap[GEMINI_PATH]
            new = txt.replace(
                'allow_nondet = constraints.get("deterministic") is False',
                'allow_nondet = constraints.get("deterministic") is True',
            )
            return {GEMINI_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m22 (gemini allow_nondet derivation flipped): {tail}"

    def test_m23_remove_return_after_deny(self) -> None:
        def mutate(snap):
            txt = snap[GEMINI_PATH]
            old = (
                '        sys.stderr.write(\n'
                '            f"AfterTool(gemini) persist-time AST gate denied submission: {exc}\\n"\n'
                '        )\n'
                '        return\n'
            )
            new_block = (
                '        sys.stderr.write(\n'
                '            f"AfterTool(gemini) persist-time AST gate denied submission: {exc}\\n"\n'
                '        )\n'
                '        # MUTATED: return removed\n'
            )
            new = txt.replace(old, new_block)
            return {GEMINI_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m23 (gemini return after deny removed): {tail}"

    def test_m24_change_reason_string(self) -> None:
        def mutate(snap):
            txt = snap[GEMINI_PATH]
            new = txt.replace(
                '"reason": "persist_time_ast_gate",',
                '"reason": "mutated_reason_g",',
            )
            return {GEMINI_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m24 (gemini reason string mutated): {tail}"

    def test_m25_error_count_off_by_one(self) -> None:
        def mutate(snap):
            txt = snap[GEMINI_PATH]
            new = txt.replace(
                '"error_count": len(errors),',
                '"error_count": len(errors) + 1,',
            )
            return {GEMINI_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        assert killed, f"SURVIVED m25 (gemini error_count off-by-one): {tail}"


# ---- cross-cutting mutations ----------------------------------------------


class TestCrossCuttingMutations:

    def test_m26_validate_default_flipped(self) -> None:
        """validate() default: allow_nondeterminism False -> True."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "def validate(code: str, *, allow_nondeterminism: bool = False, relax_external_constructs: bool = False) -> list[Violation]:",
                "def validate(code: str, *, allow_nondeterminism: bool = True, relax_external_constructs: bool = False) -> list[Violation]:",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        # validate() is not directly invoked by ensure_valid (which uses
        # validate_code), so this mutant may legitimately survive — but
        # we still record it as a documented gap in case a future caller
        # leans on the default.
        if not killed:
            pytest.xfail(
                "documented gap: validate() default flip survives because "
                "ensure_valid uses validate_code, not validate(). No persist-"
                "gate test exercises validate() directly. Recommended new "
                "test: assert rpc_submit_code.validate(UUID_CODE) raises on "
                "default."
            )

    def test_m27_format_message_drop_suffix(self) -> None:
        """Drop the `(+N more)` suffix; pin that some test relies on it.
        Likely to SURVIVE — recorded as gap if so."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                'suffix = "" if len(errors) <= 5 else f" (+{len(errors) - 5} more)"',
                'suffix = ""',
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        if not killed:
            pytest.xfail(
                "gap: no test asserts the '(+N more)' suffix appears for "
                ">5 violations. Recommended: in TestPathologicalViolations, "
                "assert '(+' in str(exc_info.value) for the 1000-uuid case."
            )

    def test_m28_preview_slice_size(self) -> None:
        """`errors[:5]` -> `errors[:1]`. Reduces preview detail."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "previews = [f\"[{v.rule}] {v.message} @L{v.line}\" for v in errors[:5]]",
                "previews = [f\"[{v.rule}] {v.message} @L{v.line}\" for v in errors[:1]]",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        if not killed:
            pytest.xfail(
                "gap: no test pins that the format_message preview shows up "
                "to 5 errors. Recommended: assert len(re.findall(r'@L', "
                "msg)) == min(5, error_count) in TestPathologicalViolations."
            )

    def test_m29_warnings_from_violations_filter_inverted(self) -> None:
        """warnings_from_violations: severity == 'warning' -> != 'warning'."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                'if getattr(v, "severity", "") == "warning"',
                'if getattr(v, "severity", "") != "warning"',
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        if not killed:
            pytest.xfail(
                "gap: warnings_from_violations is not exercised by the "
                "persist-gate suite. Recommended: a unit test asserting "
                "warnings_from_violations(mixed_list) returns only "
                "warning-severity entries."
            )

    def test_m30_rejected_payload_max_show_zero(self) -> None:
        """rejected_payload max_show: default 50 -> 0."""
        def mutate(snap):
            txt = snap[SUBMIT_PATH]
            new = txt.replace(
                "def rejected_payload(\n    violations: list[Violation], *, max_show: int = 50\n)",
                "def rejected_payload(\n    violations: list[Violation], *, max_show: int = 0\n)",
            )
            return {SUBMIT_PATH: new}
        killed, tail = _apply_and_check_killed(mutate)
        if not killed:
            pytest.xfail(
                "gap: rejected_payload is not exercised by the persist-gate "
                "suite. Recommended: a unit test asserting "
                "rejected_payload(violations)['violations'] returns up to "
                "max_show entries with a 'truncated' suffix in message."
            )


# ---------------------------------------------------------------------------
# Final cleanup sentinel
# ---------------------------------------------------------------------------


class TestZzzCleanupSentinel:
    """Run LAST. Confirms the three target files are byte-identical to
    their pre-mutation snapshots. If this fails, a previous test
    failed to restore — STOP and inspect immediately."""

    # Capture the originals at import time so this final assertion compares
    # against the same baseline the harness used.
    _originals = {
        SUBMIT_PATH: SUBMIT_PATH.read_text(encoding="utf-8"),
        CLAUDE_PATH: CLAUDE_PATH.read_text(encoding="utf-8"),
        GEMINI_PATH: GEMINI_PATH.read_text(encoding="utf-8"),
    }

    def test_zzz_files_restored_to_originals(self) -> None:
        for p, original in self._originals.items():
            current = p.read_text(encoding="utf-8")
            assert current == original, (
                f"FATAL: {p} not restored after mutation run. "
                f"orig sha={hashlib.sha256(original.encode()).hexdigest()[:8]}, "
                f"cur sha={hashlib.sha256(current.encode()).hexdigest()[:8]}"
            )

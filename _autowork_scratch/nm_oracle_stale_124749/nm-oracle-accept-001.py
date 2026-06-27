__JANUSMASK_PATCHES__ = [
    {'file': 'harness/orchestrator.py', 'kind': 'symbol', 'name': '_auto_commit_accepted', 'code': r'''def _auto_commit_accepted(state_dir: Path, task: dict[str, Any], task_id: str) -> bool:
    """Copy accepted output to its target and create a scoped git commit.

    Delegates AST merge + git operations to
    :func:`harness.git_integration.commit_accepted_output` (ported W66 from
    this file's former inline implementation, pinned by the adversarial
    battery in ``tests/adversarial/test_git_integration_acceptance_adversarial.py``
    and ``tests/adversarial/test_ast_merge_regression_adversarial.py``).

    STAGING_REROOT: EXTERNAL tasks (``not _target_is_self(working_dir)``) now
    re-root their staging worktree under the JanusMask-owned external staging
    root: ``worktree_root`` is derived via
    ``harness.paths.effective_target_root(working_dir)`` and ``staging_path`` via
    ``harness.target_bootstrap.external_staging_root() / f'{worktree_root.name}_{task_id}'``
    (both helpers imported lazily in-body). The SELF path (when
    ``_target_is_self(working_dir)`` is True) resolves ``worktree_root`` /
    ``staging_path`` exactly as before, byte-identical to its pre-reroot form.

    Resolves ``files_touched`` via the task/parent chain and constructs an
    absolute target path rooted at the worktree top-level before calling the
    module -- the module resolves its ``target_file`` argument against CWD, so
    passing a bare relative path would escape the tmp worktree used by tests.

    F3: the prior ``.py``-only short-circuit is split into two guards. A
    non-string ``target_rel`` still early-returns ``False`` (preserves the
    None / missing-key behaviour). A non-``.py`` string falls through to
    :func:`commit_accepted_output`, which already routes those through its
    direct-copy branch per commit 3b29687.

    G19b: when ``len(files_touched) > 1`` and the manifest sidecar at
    ``state_dir/'output'/f'{task_id}.files.json'`` is absent, emit a
    ``multi_file_missing_sidecar`` warning + ledger row (best-effort;
    ``OSError`` on the row write is caught and logged) and fall through
    to the singular commit path. The agent was supposed to emit
    ``__JANUSMASK_MANIFEST__`` per the G19a-1 prompt extension; absence
    indicates a regression. The fallback is the pre-G19a behavior: commit
    ``files_touched[0] // commit is reverted via ``git reset --hard HEAD~1``
    ``files_touched[0]`` only.

    U3: after a successful commit, if ``task.get('verification_command')`` is
    a non-empty string, run it under ``shell=True`` in the worktree root with
    a 600s timeout. On non-zero exit (or ``subprocess.TimeoutExpired``), the
    commit is reverted via ``git reset --hard HEAD~1``, a ``verification_failed``
    row is appended to ``state_dir/'impl_progress.jsonl'`` (with the tails of
    stdout/stderr truncated to the last 2000 chars), a ``logger.warning`` is
    emitted, and the function returns ``False`` -- closing the silent-failure
    class that let F2's commit d419ed4 land as a no-op AST merge.

    V2: after a successful commit, if ``task.get('verification_command')`` is
    missing, None, empty, whitespace-only, or non-string, the commit is
    reverted via ``git reset --hard HEAD~1``, a ``verification_missing`` row
    is appended to ``state_dir/'impl_progress.jsonl'``, a ``logger.warning`` is
    emitted, and the function returns ``False`` -- closes the
    design-time-missing half of the U1 silent-NOOP class as defense-in-depth
    when a task bypasses the planner-side V1 enforcement.

    G3a: the vcmd subprocess.run now receives ``env=_vcmd_scrubbed_env()`` so
    JANUSMASK_* identity vars don't leak from the orchestrator's environment
    into a child pytest that imports ``harness.orchestrator``. Only the vcmd
    shell=True call is scrubbed -- the git rev-parse / reset --hard calls
    still inherit full os.environ since git relies on standard env (HOME,
    PATH, etc.).

    AW3: the ``git_integration.commit_accepted_output`` call (which
    internally runs git add/commit/rev-parse-HEAD) is wrapped in an
    ``fcntl.flock(LOCK_EX)`` over
    ``state_dir/'control'/'autowork'/'git_commit.lock'`` so concurrent
    orchestrator_worker processes (autowork daemon, Task 2) and racing
    operator-driven META commits cannot interleave git writes. Lock is
    released in a ``finally`` so any exception inside the commit call
    still releases (no permanent deadlock). Lock file is opened in 'a'
    mode (mirrors ``harness/state.py:locked_read_modify_write`` lines
    139-146) so multiple processes can share the inode reference. Lock
    is held ONLY around the commit critical section -- the verification
    subprocess and any rollback can run unlocked per the brief's
    directive (verification is parallelism-safe; git-writes are not).

    G25: the vcmd subprocess.run is now invoked under ``/bin/bash`` with the
    command string wrapped as ``set -o pipefail; {vcmd}`` so a failing
    left-hand-side of a pipeline (e.g. ``pytest ... | tail -20``)
    propagates a non-zero exit through the tail and triggers the V2
    rollback. /bin/sh on Linux is dash, which does not support
    ``set -o pipefail``, so ``executable='/bin/bash'`` is required for the
    prefix to have any effect.

    H2A (JAIL_VERIFY_MUTANT): when ``agent_jail.sandbox_enabled(load_config())``
    is True, the verify run, the mutant ``apply`` run, and the mutant rerun
    are each wrapped via ``agent_jail.build_jail_argv`` into a bubblewrap argv
    list and executed WITHOUT ``shell=True`` (the inner ``/bin/bash -c`` carries
    the ``set -o pipefail; ...`` wrapper). Each jailed call passes
    ``extra_ro=[sys.base_prefix, sys.prefix]`` so the real interpreter tree
    (miniconda) AND the active environment prefix -- which the staging
    ``.venv/bin/python`` symlinks into and which may live outside ``repo_root``
    + every ``_SYSTEM_RO`` dir -- are mounted into the jail. Without
    ``sys.base_prefix`` the jailed verify exits 127 (``python: command not
    found``); adding ``sys.prefix`` (SEC-2) keeps the verify resolvable even
    when the venv lives outside the repository root (base_prefix == prefix is a
    harmless duplicate). The vcmd interpreter token stays byte-identical (bare
    ``python -m pytest ...``); the jail resolves it from the bound prefix bin
    still on PATH (``_vcmd_scrubbed_env`` preserves PATH). When sandboxing is
    disabled, all three runs fall back to the ORIGINAL ``shell=True`` /
    ``executable='/bin/bash'`` behavior byte-for-byte.

    CRED-EXFIL (EXECUTE PATH): all four sandboxed ``build_jail_argv`` calls
    here (verify, baseline-in-copy, mutant-apply, mutant rerun) run on the
    EXECUTE path and now pass ``bind_credentials=False`` -- the jail drops the
    ~/.gemini / ~/.claude credential surface (dir binds, ~/.claude.json copy,
    project-memory + global-config overlays) and unshares the network/IPC
    namespaces so any residual credential cannot be exfiltrated off-host. The
    SEC-1 dbus_proxy_socket= kwarg, the proxied_session_bus() try/except, and
    the fail-close raise are untouched.

    SEC-3 (FAIL_CLOSED_VERIFY): the verify try/except previously caught only
    ``subprocess.TimeoutExpired``, so when sandboxing is ENABLED but bwrap is
    ABSENT the ``build_jail_argv`` / ``subprocess.run`` raised
    ``FileNotFoundError`` that escaped UNCAUGHT and crashed the worker. The
    verify run now ALSO catches ``FileNotFoundError`` (only when
    ``agent_jail.sandbox_enabled(load_config())`` is True): it logs a clear
    ``verification_sandbox_error`` warning, rolls back the staging commit via
    ``_rollback_rejected_commit``, removes the staging worktree via
    ``git_integration.remove_staging_worktree``, writes a rejected ledger row,
    and returns ``False`` CLEANLY -- it NEVER re-raises and NEVER falls through
    to an unjailed run. When sandboxing is DISABLED a FileNotFoundError is
    re-raised so the historical (no-handler) behavior of the unjailed
    shell=True branch is preserved byte-for-byte.

    SEC-1 (FAILCLOSED_VERIFY_ORCHACC): each of the four sandboxed
    ``subprocess.run`` sites (verify, baseline-in-copy, mutant-apply, mutant
    rerun) now narrows its try/except to the ``proxied_session_bus()`` CONTEXT
    ENTRY ONLY, captures the socket, and runs ``subprocess.run`` OUTSIDE that
    try (so an unrelated subprocess.run exception -- FileNotFoundError /
    TimeoutExpired -- is NOT swallowed by the proxy-entry handler and reaches
    the correct verification-stage handling). If the proxy context entry
    raises while ``agent_jail.sandbox_enabled(load_config())`` is True AND
    ``shutil.which('xdg-dbus-proxy')`` resolves a binary on PATH, the runner
    FAILS CLOSED: it raises ``RuntimeError`` (message contains 'fail-closed')
    and refuses to spawn the verify/mutant child on the unfiltered host session
    bus (which would re-expose systemd1 StartTransientUnit -- a sandbox
    escape). When ``xdg-dbus-proxy`` is simply NOT installed
    (``shutil.which`` returns None), the prior graceful degrade to
    ``dbus_proxy_socket=None`` is preserved. The proxy ExitStack is reaped in a
    ``finally`` around the synchronous ``subprocess.run`` so the filtered bus
    is torn down on every exit path.

    SEC-5c (VERIFY_EXTRA_BINDS): on top of the SEC-2 prefix binds, every jailed
    ``build_jail_argv`` call now widens ``extra_ro`` with the config-driven
    ``agent_sandbox.verify_extra_ro`` allowlist and gains an ``extra_rw`` from
    ``agent_sandbox.verify_extra_rw`` (the keyword-only param added in
    PHASE_SEC5A_JAIL_RW_AND_EMBEDDED). Both lists are read once via the
    already-available ``load_config`` using safe ``.get(..., [])`` defaults so
    configs that omit the keys remain backward compatible (empty allowlists
    leave ``extra_ro == [sys.base_prefix, sys.prefix]`` and ``extra_rw == []``
    at every site). The ``[sys.base_prefix, sys.prefix]`` SEC-2 prefix is
    NEVER dropped -- ``verify_extra_ro`` is appended after it.

    G3_VENV (VENV_JAIL): for EXTERNAL tasks the four jailed verify/mutant runs
    are pinned to the TARGET repository's own virtualenv. A local
    ``_ext_venv_ro`` list binds ``<worktree_root>/.venv`` read-only into every
    jail (appended after the SEC-2 prefix + SEC-5c allowlist so neither is
    dropped) and a nested ``_venv_jail_env()`` helper returns the
    ``_vcmd_scrubbed_env()`` copy with ``<worktree_root>/.venv/bin`` PREFIXED
    onto PATH so the verification_command resolves the TARGET interpreter, not
    whatever python the harness environment happens to expose. The helper FAILS
    CLOSED: if the EXTERNAL target's ``.venv/bin/python`` is absent it raises a
    ``RuntimeError`` rather than silently inheriting the harness python. SELF
    tasks are byte-identical to the pre-G3_VENV behavior -- ``_ext_venv_ro`` is
    empty and ``_venv_jail_env()`` returns the scrubbed env unmodified (no PATH
    mutation, default interpreter), and ``bind_credentials=False`` plus the
    net/ipc namespace unshare are preserved at every site.

    ROLLBACK_WORKTREE_CHECKOUT: both ``git reset --hard HEAD~1`` rollback
    sites (verification_missing and verification_failed) are followed by a
    best-effort ``git checkout HEAD -- <target_rel>`` to scrub any stray
    working-copy drift left over from the rejected commit. The checkout is
    wrapped in the same ``(subprocess.TimeoutExpired, FileNotFoundError,
    OSError)`` try/except as the reset and logs at ERROR on failure; it
    does not change the function's return value or affect the ledger emit.

    ROLLBACK_COMPLETENESS: the non-``no_diff:`` err branch now scrubs staged +
    tracked-worktree drift. ``commit_accepted_output`` writes the merged
    file(s) and ``git add``-stages them BEFORE the failing git step, so a
    generic-exception failure (index.lock contention, commit timeout) leaves
    staged content with NO commit to ``reset --hard HEAD~1``. The branch now
    iterates the resolved ``files_touched`` list and runs a best-effort,
    non-destructive ``git reset -q -- <rel>`` + ``git checkout HEAD -- <rel>``
    per string path, wrapped in a single ``(subprocess.TimeoutExpired,
    FileNotFoundError, OSError)`` try/except that logs at ERROR and never
    raises. ``no_diff:`` is self-cleaning (staged == HEAD) and is NOT
    scrubbed. Brand-new untracked files are intentionally left for operator
    review (no ``git clean``). The branch still returns False.

    H1 (MUTATION_GATE_HARDENING): the Phase-B mutation-gate body is now wrapped
    in a try/except so any unexpected exception (copytree ENOSPC/PermissionError,
    git failure, mutant application crash) is caught fail-closed: the staging
    commit is rolled back via ``_rollback_rejected_commit`` +
    ``git_integration.remove_staging_worktree``, a ``mutation_gate_error``
    rejected ledger row is written, and the function returns ``False`` without
    re-raising. ``mutation_target`` (and any per-mutant ``stub_target``) is
    validated and normalized to a bare dotted module name BEFORE a path is built
    from it -- a value containing ``/``, ``..``, ending in ``.py``, or not a
    bare dotted module name is rejected fail-closed (same rollback +
    ``mutation_gate_error`` row) instead of crashing path operations. The
    throwaway-copy ``shutil.copytree`` ignore set is widened to also skip
    ``state``, ``samples``, ``.pytest_cache``, and ``*.egg-info``.

    MUT-MASK (MUTANT_INFRA_VS_ASSERTION): a mutant rerun can exit NON-ZERO for
    an INFRA reason rather than a genuine assertion failure -- the
    verification_command may touch a path the throwaway ``copytree`` DROPPED
    (e.g. ``samples/`` or ``state/`` per the H1-widened ignore set). The bare
    ``_mvacuous = (_mproc.returncode == 0)`` interpretation would MISREAD that
    infra fluke as 'mutant caught' and silently ACCEPT a vacuous test. To
    distinguish infra-fail from genuine assertion-fail, a BASELINE-IN-COPY
    guard (Option A, prep-validated) re-runs the UNMUTATED ``vcmd`` inside the
    fresh ``_mcopy`` -- through the SAME jail/shell discipline, pipefail
    wrapper, ``cwd``, ``extra_ro``, and scrubbed env as the mutant rerun --
    immediately after the ``copytree`` and BEFORE the mutant is applied. If
    that baseline-in-copy run exits NON-ZERO the copy is structurally unable to
    run the unmutated verify (a path dropped by the ignore set), so the mutant
    rerun cannot be trusted: a ``RuntimeError`` is raised, caught by the
    existing H1 try/except, rolled back, and recorded as
    ``mutation_gate_error`` -- it is NEVER credited as a mutant catch. When the
    baseline-in-copy passes (exit 0), behavior is byte-identical to before:
    the mutant is applied and ``_mvacuous = (_mproc.returncode == 0)`` still
    decides catch-vs-vacuous.

    ROLLB-A (TASK-SCOPED STAGING): the staging worktree path is now scoped by
    ``task_id`` -- ``worktree_root.parent / f"{worktree_root.name}_{task_id}_staging"``
    -- so concurrent pipeline runs on distinct task IDs derive distinct
    staging directories and can no longer collide on a single shared
    ``{name}_staging`` worktree. The path stays a sibling of the parent
    worktree root (under ``worktree_root.parent``) so the
    ``git_integration.create_staging_worktree`` sibling-placement constraint
    still holds, and every downstream lifecycle usage (create, .venv symlink,
    commit, verify, mutation-gate copy, rollback, merge, cleanup) operates on
    the same task-scoped ``staging_path``.

    INV9 (CONTENT_GATE): when (and only when) the apply is granted via the
    auto-approve consult (``_granted_via_auto_approve`` True) -- never on the
    operator-decision path -- the staged artifact bytes that
    ``commit_accepted_output`` will actually apply are first run through the
    pure ``_auto_approve_content_safe`` capability gate. The gate inspects the
    SAME artifact resolved in the SAME precedence the commit uses
    (.patches.json > .files.json > .py) and refuses dangerous dynamic-execution
    / shell capabilities. On a refusal both ``_approval_ok`` AND
    ``_granted_via_auto_approve`` are reset to False so the sensitive apply is
    blocked AND the ceiling counter below is NOT incremented (fail-closed). The
    operator-approval path and the flag-off path are UNTOUCHED.

    INV5 (TOCTOU_PIN): the eligibility + content gates above run BEFORE the
    ``git_commit.lock`` flock, opening a TOCTOU window in which the staged
    artifact bytes (or the parent HEAD) could be tampered between the checks
    and the actual git write. To close it, once an auto-approve grant is
    FINALIZED (after the content gate) we PIN ``_pinned_artifact_sha`` (sha256
    of the staged artifact resolved .patches.json > .files.json > .py, first
    that exists) and ``_pinned_parent_head`` (``git rev-parse HEAD`` in
    ``worktree_root``). Then INSIDE the flock, IMMEDIATELY before
    ``commit_accepted_output``, the artifact sha + parent HEAD are re-read and
    compared; on ANY mismatch the auto-approve commit is ABORTED -- the commit
    is NOT performed, ``_approval_ok`` and ``_granted_via_auto_approve`` are
    dropped to False, a telemetry line is emitted, and an error result is
    synthesized so the not-committed handler scrubs staging and returns False
    (the ceiling counter is NOT incremented). hashlib is imported lazily
    in-body (no module-level import). The operator-approval path and the
    flag-off path are UNTOUCHED -- neither pins nor compares.

    Never raises (except the SEC-1 fail-closed RuntimeError above). Returns
    True only if a new commit was produced and the required verification
    command exited zero.
    """
    from harness import agent_jail
    from harness.dbus_proxy import proxied_session_bus
    from harness import git_integration
    from harness._journal import write_jsonl_row
    from harness.orchestrator import _resolve_files_touched, _resolve_verification_command, _vcmd_scrubbed_env, logger
    import contextlib
    import fcntl
    import shutil
    import subprocess
    import sys
    import time
    _sandbox_cfg = load_config().get('agent_sandbox', {})
    verify_extra_ro = _sandbox_cfg.get('verify_extra_ro', [])
    verify_extra_rw = _sandbox_cfg.get('verify_extra_rw', [])
    from harness.paths import _target_is_self
    working_dir = task.get('working_dir')
    files_touched = _resolve_files_touched(state_dir, task, task_id)
    if not files_touched:
        logger.info('auto-commit: skipped %s (no files_touched resolved)', task_id)
        return False
    target_rel = files_touched[0]
    if not isinstance(target_rel, str):
        logger.info('auto-commit: skipped %s (target %r is not a string path)', task_id, target_rel)
        return False
    sidecar_path = state_dir / 'output' / f'{task_id}.files.json'
    if len(files_touched) > 1 and (not sidecar_path.exists()):
        logger.warning('auto-commit: multi-file task %s has %d files_touched but no sidecar at %s; agent failed to emit __JANUSMASK_MANIFEST__; falling back to singular commit of files_touched[0]=%s', task_id, len(files_touched), sidecar_path, target_rel)
        try:
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'auto_commit', 'task_id': task_id, 'event': 'multi_file_missing_sidecar', 'reason': 'agent_did_not_emit_manifest', 'files': files_touched, 'exit': 0})
        except OSError as exc:
            logger.warning('multi_file_missing_sidecar: ledger append failed for %s: %s', task_id, exc)
    if not target_rel.endswith('.py'):
        logger.info('auto-commit: target %s is non-py; delegating to git_integration.commit_accepted_output (direct-copy path)', task_id)
    if not _target_is_self(working_dir):
        from harness.paths import effective_target_root
        from harness.target_bootstrap import external_staging_root
        worktree_root = Path(effective_target_root(working_dir)).resolve()
        staging_path = Path(external_staging_root()) / f'{worktree_root.name}_{task_id}'
    else:
        try:
            rev = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True, timeout=10, cwd=str(state_dir.parent))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning('auto-commit: git rev-parse failed for %s: %s', task_id, exc)
            return False
        worktree_root = Path(rev.stdout.strip()).resolve()
        staging_path = worktree_root.parent / f'{worktree_root.name}_{task_id}_staging'
    logger.info('auto-commit: using staging worktree at %s for task %s', staging_path, task_id)
    _ext_venv_ro = [str(worktree_root / '.venv')] if not _target_is_self(working_dir) else []

    def _venv_jail_env() -> dict[str, str]:
        _env = _vcmd_scrubbed_env()
        if _target_is_self(working_dir):
            return _env
        _venv_bin = worktree_root / '.venv' / 'bin'
        if not (_venv_bin / 'python').exists():
            raise RuntimeError('G3_VENV: refusing to run the verification_command for an EXTERNAL target whose virtualenv is missing (%s is absent); the orchestrator will NOT silently inherit the harness environment python (no-venv refusal, fail-closed). Create the target .venv and retry.' % (_venv_bin / 'python',))
        _path = _env.get('PATH', '')
        _env['PATH'] = str(_venv_bin) + (os.pathsep + _path if _path else '')
        return _env
    if not _target_is_self(working_dir):
        _dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=str(worktree_root), capture_output=True, text=True)
        if _dirty.returncode == 0 and _dirty.stdout.strip():
            raise RuntimeError('EXTERNAL_DIRTY_GATE (REV23 §3-2): refusing to stage/commit an EXTERNAL target whose repository has a dirty working tree; JanusMask never auto-stages or stashes a user repo (working_dir=%r is outside the JanusMask tree). Commit or stash the external working tree and retry.' % (working_dir,))
    try:
        git_integration.create_staging_worktree(str(staging_path), parent_root=worktree_root)
    except Exception as e:
        logger.error('Failed to create staging worktree for %s: %s', task_id, e)
        return False
    try:
        parent_venv = worktree_root / '.venv'
        staging_venv = staging_path / '.venv'
        if parent_venv.exists() and (not staging_venv.exists()):
            try:
                os.symlink(parent_venv.resolve(), staging_venv)
            except Exception as sym_exc:
                logger.warning('Failed to symlink .venv to staging: %s', sym_exc)
        target_abs = str((worktree_root / target_rel).resolve())
        _mtt = task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')
        _approval_ok = _apply_approval_granted(state_dir, task_id)
        _granted_via_auto_approve = False
        if not _approval_ok:
            _approval_ok = _auto_approve_sensitive_eligible(state_dir, task, task_id, files_touched, load_config(), repo_root=worktree_root)
            _granted_via_auto_approve = _approval_ok
        if _granted_via_auto_approve and (not _auto_approve_content_safe(state_dir, task_id)):
            _approval_ok = False
            _granted_via_auto_approve = False

        def _inv5_artifact_sha() -> str | None:
            import hashlib
            _odir = Path(state_dir) / 'output'
            for _aname in (f'{task_id}.patches.json', f'{task_id}.files.json', f'{task_id}.py'):
                _apath = _odir / _aname
                if _apath.exists():
                    try:
                        return hashlib.sha256(_apath.read_bytes()).hexdigest()
                    except OSError:
                        return None
            return None

        def _inv5_parent_head() -> str | None:
            try:
                _rp = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(worktree_root), timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return None
            return _rp.stdout.strip() if _rp.returncode == 0 else None
        _pinned_artifact_sha = _inv5_artifact_sha() if _granted_via_auto_approve else None
        _pinned_parent_head = _inv5_parent_head() if _granted_via_auto_approve else None
        _ro_gate_cfg = load_config()
        _ro_gate_on = bool(isinstance(_ro_gate_cfg, dict) and isinstance(_ro_gate_cfg.get('autowork'), dict) and _ro_gate_cfg['autowork'].get('auto_approve_ro_gate'))
        if _granted_via_auto_approve and _ro_gate_on and (not git_integration._verify_from_ro_parent(worktree_root, _pinned_parent_head, staging_path, _RO_GATE_TESTS)):
            _approval_ok = False
            _granted_via_auto_approve = False
            logger.warning('auto_approve_ro_gate_failed: aborting auto-approve commit for %s -- the RO-parent verification gate refused the staged candidate (git_integration._verify_from_ro_parent returned False against pinned parent HEAD %s); treating as refused apply', task_id, _pinned_parent_head)
            try:
                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'auto_approve_ro_gate_failed', 'commit_sha': None, 'files': files_touched, 'reason': 'RO-parent verification gate refused the staged candidate'})
            except OSError as _exc:
                logger.warning('auto_approve_ro_gate_failed: ledger append failed for %s: %s', task_id, _exc)
        lock_dir = state_dir / 'control' / 'autowork'
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / 'git_commit.lock'
        with open(lock_path, 'a') as lock_fd:
            _lock_acquired = _acquire_git_commit_lock_bounded(lock_fd)
            try:
                if not _lock_acquired:
                    logger.warning('git_commit_lock_timeout: failing commit attempt for %s -- git_commit.lock still held by a live process after %.0fs; routing to auto_commit_failed instead of blocking', task_id, _GIT_COMMIT_LOCK_DEADLINE_SEC)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'git_commit_lock_timeout', 'commit_sha': None, 'files': files_touched, 'reason': 'git_commit.lock held by a live process past the acquisition deadline'})
                    except OSError as _exc:
                        logger.warning('git_commit_lock_timeout: ledger append failed for %s: %s', task_id, _exc)
                    result = {'committed': False, 'error': 'git_commit_lock_timeout: git_commit.lock held by a live process past the acquisition deadline'}
                _inv5_abort = False
                if _lock_acquired and _granted_via_auto_approve:
                    _now_artifact_sha = _inv5_artifact_sha()
                    _now_parent_head = _inv5_parent_head()
                    if _now_artifact_sha != _pinned_artifact_sha or _now_parent_head != _pinned_parent_head:
                        _inv5_abort = True
                        _approval_ok = False
                        _granted_via_auto_approve = False
                        logger.warning('INV5 TOCTOU_PIN: aborting auto-approve commit for %s -- staged artifact or parent HEAD changed between pin and commit (artifact sha pinned=%s now=%s, parent HEAD pinned=%s now=%s); treating as refused apply', task_id, _pinned_artifact_sha, _now_artifact_sha, _pinned_parent_head, _now_parent_head)
                        try:
                            write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'auto_approve_toctou_pin_mismatch', 'commit_sha': None, 'files': files_touched, 'reason': 'staged artifact bytes or parent HEAD changed between pin and commit'})
                        except OSError as _exc:
                            logger.warning('auto_approve_toctou_pin_mismatch: ledger append failed for %s: %s', task_id, _exc)
                        result = {'committed': False, 'error': 'auto_approve_toctou_pin_mismatch: staged artifact bytes or parent HEAD changed between pin and commit'}
                if _lock_acquired and (not _inv5_abort):
                    result = git_integration.commit_accepted_output(task_id, target_abs, state_dir, worktree_root=staging_path, allowed_files=set(files_touched), meta_task_type=_mtt, approval_ok=_approval_ok, working_dir=working_dir, widened_auto_approve=_granted_via_auto_approve)
                    if _granted_via_auto_approve and result.get('committed'):
                        _count_path = Path(state_dir) / 'control' / 'autowork' / 'auto_approve_count.json'
                        _n = 0
                        try:
                            _cdata = json.loads(_count_path.read_text(encoding='utf-8', errors='replace'))
                            if isinstance(_cdata, dict) and isinstance(_cdata.get('count'), int) and (not isinstance(_cdata.get('count'), bool)):
                                _n = _cdata['count']
                            elif isinstance(_cdata, int) and (not isinstance(_cdata, bool)):
                                _n = _cdata
                        except Exception:
                            _n = 0
                        _count_path.write_text(json.dumps({'count': _n + 1}), encoding='utf-8')
            finally:
                if _lock_acquired:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if result.get('committed'):
            vcmd = _resolve_verification_command(state_dir, task, task_id)
            if not (isinstance(vcmd, str) and vcmd.strip()):
                logger.warning('verification_missing: task=%s -- staging rolled back; tasks must carry a non-empty verification_command', task_id)
                _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_missing')
                git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_missing', 'commit_sha': result.get('sha'), 'files': [target_rel], 'reason': 'verification_command missing, empty, or non-string'})
                except OSError as exc:
                    logger.warning('verification_missing: ledger append failed for %s: %s', task_id, exc)
                return False

            def _is_unscoped_pytest(cmd_str: str) -> bool:
                if 'pytest' not in cmd_str:
                    return False
                import shlex
                try:
                    parts = shlex.split(cmd_str)
                except Exception:
                    parts = cmd_str.split()
                idx = -1
                for i, part in enumerate(parts):
                    if part == 'pytest' or part.endswith('/pytest'):
                        idx = i
                        break
                if idx == -1:
                    return False
                args = parts[idx + 1:]
                options_with_args = {'-k', '-m', '-o', '-c', '-p', '--tb', '--import-mode', '--color', '--durations', '--maxfail', '--lf', '--last-failed', '--ff', '--failed-first', '--nf', '--new-first', '--cache-clear', '--rootdir', '--override-ini', '--show-capture'}
                has_target = False
                skip_next = False
                for arg in args:
                    if skip_next:
                        skip_next = False
                        continue
                    if arg.startswith('-'):
                        if arg in options_with_args:
                            skip_next = True
                        continue
                    has_target = True
                    break
                return not has_target
            if _is_unscoped_pytest(vcmd):
                from harness.test_scoper import get_relevant_test_files
                relevant_tests = get_relevant_test_files(staging_path, files_touched)
                existing_tests = [t for t in relevant_tests if (staging_path / t).exists()]
                if not existing_tests:
                    existing_tests = ['tests/test_import.py']
                vcmd = vcmd.rstrip() + ' ' + ' '.join(existing_tests)
                logger.info('Rewrote unscoped pytest command for task %s to: %s', task_id, vcmd)
            verify_exit: int | None = None
            verify_stdout = ''
            verify_stderr = ''
            timed_out = False
            try:
                _vcfg = load_config().get('synthesis', {}) or {}
                verification_timeout = int(_vcfg.get('verification_timeout_seconds', max(900, int(_vcfg.get('timeout_seconds', 600)))))
            except Exception:
                verification_timeout = 600
            try:
                _vfull = f'set -o pipefail; {vcmd}'
                if agent_jail.sandbox_enabled(load_config()):
                    _dbus_stack = contextlib.ExitStack()
                    try:
                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                    except Exception:
                        if shutil.which('xdg-dbus-proxy') is not None:
                            _dbus_stack.close()
                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                        _sock = None
                    try:
                        vproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _vfull], repo_root=worktree_root, work_dir=staging_path, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=str(staging_path), capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                    finally:
                        _dbus_stack.close()
                else:
                    if not _target_is_self(working_dir):
                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    vproc = subprocess.run(_vfull, shell=True, cwd=str(staging_path), capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                verify_exit = vproc.returncode
                verify_stdout = vproc.stdout or ''
                verify_stderr = vproc.stderr or ''
            except subprocess.TimeoutExpired as texc:
                timed_out = True
                verify_exit = 124
                partial_out = texc.stdout
                partial_err = texc.stderr
                if isinstance(partial_out, (bytes, bytearray)):
                    verify_stdout = partial_out.decode('utf-8', 'replace')
                elif isinstance(partial_out, str):
                    verify_stdout = partial_out
                if isinstance(partial_err, (bytes, bytearray)):
                    verify_stderr = partial_err.decode('utf-8', 'replace')
                elif isinstance(partial_err, str):
                    verify_stderr = partial_err
                verify_stderr = (verify_stderr + '\n' if verify_stderr else '') + f'[verification_command timed out after {verification_timeout}s: {texc!r}]'
            except FileNotFoundError as fnf:
                if agent_jail.sandbox_enabled(load_config()):
                    logger.warning('verification_sandbox_error: task=%s -- sandbox enabled but bwrap/jail unavailable (%r); staging rolled back fail-closed (never run unjailed)', task_id, fnf)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_sandbox_error')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_sandbox_error', 'commit_sha': result.get('sha'), 'files': [target_rel], 'reason': str(fnf)})
                    except OSError as exc:
                        logger.warning('verification_sandbox_error: ledger append failed for %s: %s', task_id, exc)
                    return False
                raise
            _nm_oracle = _new_module_red_by_absence(task, worktree_root, verify_exit, (verify_stdout or '') + '\n' + (verify_stderr or ''))
            if verify_exit != 0 and not _nm_oracle:
                cmd_preview = vcmd if len(vcmd) <= 200 else vcmd[:200] + '...(truncated)'
                logger.warning('verification_failed: task=%s exit=%s timeout=%s cmd=%s', task_id, verify_exit, timed_out, cmd_preview)
                _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'verification_failed')
                git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                stdout_tail = verify_stdout[-2000:] if verify_stdout else ''
                stderr_tail = verify_stderr[-2000:] if verify_stderr else ''
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'verification_failed', 'exit': verify_exit, 'stdout_tail': stdout_tail, 'stderr_tail': stderr_tail, 'commit_sha': result.get('sha'), 'files': [target_rel], 'timed_out': timed_out})
                except OSError as exc:
                    logger.warning('verification_failed: ledger append failed for %s: %s', task_id, exc)
                return False
            logger.info('auto-commit: SUCCESS in staging for %s -> %s (sha=%s)', task_id, target_rel, result.get('sha'))
            _mut_specs = list(task.get('mutations') or [])
            _mut_target = task.get('mutation_target')
            if (_mtt == 'test_authoring' or _mut_specs or _mut_target) and not _nm_oracle:
                if not _mut_specs and (not _mut_target):
                    logger.warning('mutation_gate_missing: task=%s declares no mutant -- rejected fail-closed', task_id)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_missing')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_missing', 'commit_sha': result.get('sha'), 'files': files_touched, 'reason': 'test_authoring task must declare mutation_target or mutations[]'})
                    except OSError as _exc:
                        logger.warning('mutation_gate_missing: ledger append failed for %s: %s', task_id, _exc)
                    return False
                try:
                    import re as _re
                    import tempfile

                    def _valid_mut_module(_v: object) -> bool:
                        if not isinstance(_v, str) or not _v:
                            return False
                        if '/' in _v or '\\' in _v or '..' in _v or _v.endswith('.py'):
                            return False
                        return _re.fullmatch('[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*', _v) is not None
                    _mut_all = list(_mut_specs)
                    if _mut_target:
                        if not _valid_mut_module(_mut_target):
                            raise ValueError(f'malformed mutation_target {_mut_target!r}: not a bare dotted module name')
                        _mut_all.append({'stub_target': _mut_target})
                    for _mi, _mut in enumerate(_mut_all):
                        _mtmp = tempfile.mkdtemp(prefix='jm_mutgate_')
                        _mvacuous = True
                        try:
                            _mcopy = os.path.join(_mtmp, 'staging')
                            shutil.copytree(str(staging_path), _mcopy, symlinks=True, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc', 'state', 'samples', '.pytest_cache', '*.egg-info'))
                            _bfull = f'set -o pipefail; {vcmd}'
                            if agent_jail.sandbox_enabled(load_config()):
                                _dbus_stack = contextlib.ExitStack()
                                try:
                                    _sock = _dbus_stack.enter_context(proxied_session_bus())
                                except Exception:
                                    if shutil.which('xdg-dbus-proxy') is not None:
                                        _dbus_stack.close()
                                        raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                    _sock = None
                                try:
                                    _bproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _bfull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                finally:
                                    _dbus_stack.close()
                            else:
                                if not _target_is_self(working_dir):
                                    raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                _bproc = subprocess.run(_bfull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                            if _bproc.returncode != 0:
                                raise RuntimeError(f'mutation_gate baseline-in-copy failed for mutant #{_mi}: the unmutated verification_command exits {_bproc.returncode} inside the mutant copy (a path dropped by the copytree ignore set); the mutant rerun cannot be trusted as a catch')
                            _applied = True
                            if _mut.get('stub_target'):
                                _st = _mut.get('stub_target')
                                if not _valid_mut_module(_st):
                                    raise ValueError(f'malformed stub_target {_st!r}: not a bare dotted module name')
                                from harness import test_author
                                _sf = os.path.join(_mcopy, _st.replace('.', '/') + '.py')
                                with open(_sf, 'r', encoding='utf-8') as _rf:
                                    _osrc = _rf.read()
                                with open(_sf, 'w', encoding='utf-8') as _wf:
                                    _wf.write(test_author.stub_for(_osrc))
                            elif _mut.get('apply'):
                                _afull = f'set -o pipefail; {_mut['apply']}'
                                if agent_jail.sandbox_enabled(load_config()):
                                    _dbus_stack = contextlib.ExitStack()
                                    try:
                                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                                    except Exception:
                                        if shutil.which('xdg-dbus-proxy') is not None:
                                            _dbus_stack.close()
                                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                        _sock = None
                                    try:
                                        _ap = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _afull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                    finally:
                                        _dbus_stack.close()
                                else:
                                    if not _target_is_self(working_dir):
                                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                    _ap = subprocess.run(_afull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                                _applied = _ap.returncode == 0
                            else:
                                _applied = False
                            if _applied:
                                _rfull = f'set -o pipefail; {vcmd}'
                                if agent_jail.sandbox_enabled(load_config()):
                                    _dbus_stack = contextlib.ExitStack()
                                    try:
                                        _sock = _dbus_stack.enter_context(proxied_session_bus())
                                    except Exception:
                                        if shutil.which('xdg-dbus-proxy') is not None:
                                            _dbus_stack.close()
                                            raise RuntimeError('agent_sandbox is enabled and xdg-dbus-proxy is present but the filtered D-Bus proxy failed to start; refusing to spawn an agent on the unfiltered host bus (fail-closed).')
                                        _sock = None
                                    try:
                                        _mproc = subprocess.run(agent_jail.build_jail_argv(['/bin/bash', '-c', _rfull], repo_root=worktree_root, work_dir=_mcopy, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw), dbus_proxy_socket=_sock, bind_credentials=False), cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_venv_jail_env())
                                    finally:
                                        _dbus_stack.close()
                                else:
                                    if not _target_is_self(working_dir):
                                        raise RuntimeError('FLAG2_ORCH (REV22 §3): refusing to run the verification_command UNJAILED via shell=True on the host because agent_sandbox is disabled and the target is EXTERNAL (working_dir=%r is outside the JanusMask tree). An external verify/baseline/mutant spawn MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                                    _mproc = subprocess.run(_rfull, shell=True, cwd=_mcopy, capture_output=True, text=True, timeout=verification_timeout, env=_vcmd_scrubbed_env(), executable='/bin/bash')
                                _mvacuous = _mproc.returncode == 0
                        finally:
                            shutil.rmtree(_mtmp, ignore_errors=True)
                        if _mvacuous:
                            logger.warning('mutation_gate_failed: task=%s mutant #%d did not break verification (vacuous test) -- staging rolled back', task_id, _mi)
                            _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_failed')
                            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                            try:
                                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_failed', 'commit_sha': result.get('sha'), 'files': files_touched, 'mutant_index': _mi})
                            except OSError as _exc:
                                logger.warning('mutation_gate_failed: ledger append failed for %s: %s', task_id, _exc)
                            return False
                    logger.info('mutation_gate: task=%s passed %d mutant(s)', task_id, len(_mut_all))
                except Exception as _gate_exc:
                    logger.error('mutation_gate_error: task=%s unexpected exception in mutation gate -- staging rolled back fail-closed: %s', task_id, _gate_exc)
                    _rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'mutation_gate_error')
                    git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'mutation_gate_error', 'commit_sha': result.get('sha'), 'files': files_touched, 'reason': str(_gate_exc)})
                    except OSError as _exc:
                        logger.warning('mutation_gate_error: ledger append failed for %s: %s', task_id, _exc)
                    return False
            if _wire_up_gate_enabled(state_dir):
                if _run_wire_up_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir):
                    return False
            try:
                write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'accepted', 'task_id': task_id, 'event': 'auto_commit', 'commit_sha': result.get('sha'), 'files': files_touched, 'exit': 0})
            except OSError as exc:
                logger.warning('auto-commit: ledger append failed for %s: %s', task_id, exc)
            try:
                git_integration.merge_staging_to_parent(staging_path, worktree_root, working_dir=working_dir)
                logger.info('Merged staging commit back to parent repository.')
            except Exception as merge_err:
                logger.error('Failed to merge staging changes: %s', merge_err)
                _mark_blocked(state_dir, task_id, outcome='merge_failed')
                return False
            _mark_processed(state_dir, task_id)
            if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
                logger.info('Test environment detected. Skipping os.execv process handover.')
                return True
            perform_process_handover(state_dir)
            return True
        err = result.get('error')
        if err:
            logger.warning('auto-commit: FAILED %s: %s', task_id, err)
            if isinstance(err, str) and err.startswith('no_diff:'):
                try:
                    marker = state_dir / 'output' / f'{task_id}.no_diff'
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text('1', encoding='utf-8')
                except OSError as exc:
                    logger.warning('no_diff: marker write failed for %s: %s', task_id, exc)
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'rejected', 'task_id': task_id, 'event': 'no_diff', 'commit_sha': None, 'files': [target_rel], 'reason': err})
                except OSError as exc:
                    logger.warning('no_diff: ledger append failed for %s: %s', task_id, exc)
            else:
                for _rel in files_touched:
                    if not isinstance(_rel, str):
                        continue
                    try:
                        subprocess.run(['git', 'reset', '-q', '--', _rel], cwd=str(staging_path), check=False, timeout=30)
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as rexc:
                        logger.error('commit_failed scrub: git reset -q -- %s failed for %s: %s; worktree may be in inconsistent state', _rel, task_id, rexc)
                    try:
                        subprocess.run(['git', 'checkout', 'HEAD', '--', _rel], cwd=str(staging_path), check=False, timeout=30)
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as cexc:
                        logger.error('commit_failed scrub: git checkout HEAD -- %s failed for %s: %s; worktree may be in inconsistent state', _rel, task_id, cexc)
            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
        return False
    finally:
        try:
            git_integration.remove_staging_worktree(str(staging_path), parent_root=worktree_root)
        except Exception as _cleanup_exc:
            logger.error('ROLLB-D staging cleanup failed for %s: %s', task_id, _cleanup_exc)
'''},
    {'file': 'harness/orchestrator.py', 'kind': 'symbol', 'name': '_join_stream_threads', 'code': r'''def _new_module_red_by_absence(task, worktree_root, verify_exit, verify_out) -> bool:
    """G-NEW-MODULE-ORACLE: accept a RED-by-absence ``test_authoring`` oracle.

    Returns True iff ALL hold:
      (a) the task is ``test_authoring`` (``meta_task_type`` at top level OR
          under ``constraints``);
      (b) ``mutation_target`` is a non-empty BARE dotted module name (no ``/``,
          no ``..``, no trailing ``.py``);
      (c) the target module file is ABSENT under ``worktree_root``;
      (d) verification actually failed (``verify_exit`` is not None and != 0);
      (e) the failure is absence-of-target -- ``verify_out`` contains one of
          ModuleNotFoundError / ImportError / AttributeError AND names the
          target's top-level package.

    Such an oracle is RED purely by construction: it imports a module that does
    not exist yet, so neither the vcmd-exit-0 gate nor the mutant non-vacuity
    gate is applicable (you cannot make a test pass against, nor mutate, an
    absent module). The non-vacuity is established by construction. When this
    returns True the caller bypasses both rejection points and accepts. It is
    NARROW: an existing module (c fails), a failure that never imports the
    target (e fails), or a passing/None verify (d fails) all return False.

    Fail-closed: ANY unexpected error returns False; the helper NEVER raises.
    """
    try:
        import re as _re
        _mtt = task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')
        if _mtt != 'test_authoring':
            return False
        mt = task.get('mutation_target')
        if not isinstance(mt, str) or not mt:
            return False
        if '/' in mt or '\\' in mt or '..' in mt or mt.endswith('.py'):
            return False
        if _re.fullmatch('[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*', mt) is None:
            return False
        target_file = Path(worktree_root) / (mt.replace('.', '/') + '.py')
        if target_file.exists():
            return False
        if verify_exit is None or verify_exit == 0:
            return False
        if isinstance(verify_out, str):
            text = verify_out
        elif verify_out is None:
            text = ''
        else:
            text = str(verify_out)
        if not any((_e in text for _e in ('ModuleNotFoundError', 'ImportError', 'AttributeError'))):
            return False
        _top = mt.split('.')[0]
        if _top not in text:
            return False
        return True
    except Exception:
        return False

def _join_stream_threads(proc: subprocess.Popen, timeout: float=2.0) -> None:
    """Join the stdout/stderr stream threads if they exist."""
    threads = getattr(proc, '_stream_threads', None)
    if threads:
        for t in threads:
            t.join(timeout=timeout)
'''},
]

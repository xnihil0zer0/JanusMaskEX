---
complexity_score: 4
dependencies:
  - "drive-backup-hook-runner"
interfaces: "tools/drive_backup/install_hooks.py: SENTINEL ('# >>> janusmask-drive-backup >>>'); JANUSMASK_ROOT default; DEFAULT_REPOS (['/home/xnihil0zer0/JanusMaskJR', '/home/xnihil0zer0/NobleGreedv2']); render_shim(janusmask_root, *, chained_hook=None) -> str; InstallResult dataclass{repo, hook_path, action, ok}; install(repo_roots=DEFAULT_REPOS, *, fs, janusmask_root=JANUSMASK_ROOT, dry_run=False) -> list[InstallResult]; main(argv=None, *, fs=None) -> int."
---

# Title

Drive-backup installer: idempotently write a thin, marker-guarded `pre-push` shim into BOTH repos' `.git/hooks/pre-push` (JanusMaskJR and NobleGreedv2) that execs `python -m tools.drive_backup.hook_runner` and always exits 0, preserving any pre-existing non-managed pre-push hook by chaining to it.

# Scope

Build a NEW single-file, whole-file, stdlib-only module `tools/drive_backup/install_hooks.py`, IMPL-only against its pre-committed RED oracle.

- `render_shim(janusmask_root, *, chained_hook=None)` returns the `#!/usr/bin/env bash` shim text bounded by the `SENTINEL` marker. The shim: (a) reads the pushed refs from stdin into a temp var; (b) if `chained_hook` is set, first runs the saved original hook with the SAME stdin and arguments, preserving ITS exit code only if it is the original gate (the drive-backup step itself never affects exit); (c) `cd`s to `janusmask_root` and pipes the stdin into `python -m tools.drive_backup.hook_runner "$@"`; (d) `exit 0` unconditionally for the backup step. The `janusmask_root` is embedded as an ABSOLUTE path so the hook in NobleGreedv2 still finds the JanusMask module.
- `install(repo_roots=DEFAULT_REPOS, *, fs, janusmask_root, dry_run=False)`: for each repo, targets `<repo>/.git/hooks/pre-push` via the injected `fs` seam. If no hook exists → write the shim (action `created`). If a JanusMask-managed shim already exists (detected by `SENTINEL`) → rewrite in place (action `updated`, idempotent). If a foreign non-managed hook exists → move it to `pre-push.pre-janusmask` and write a shim that CHAINS to it (action `chained`). `dry_run=True` computes the action and target without writing (action suffixed `:dry`). Marks the written file executable (mode 0o755) via the `fs` seam. Returns a `list[InstallResult]`.
- `main(argv=None, *, fs=None)`: CLI shim (`--dry-run`, optional repo overrides) defaulting `fs` to a real filesystem adapter at runtime; returns 0 on success.
- `DEFAULT_REPOS = ['/home/xnihil0zer0/JanusMaskJR', '/home/xnihil0zer0/NobleGreedv2']`.

# Non-Goals

No real `.git/hooks/pre-push` writes in any tested path — `fs` is an injected seam (fake filesystem) and tests assert: shim text shape (sentinel present, absolute janusmask_root, `python -m tools.drive_backup.hook_runner`, unconditional `exit 0`), the created/updated/chained/dry branches, idempotency (managed→updated, never duplicated), foreign-hook preservation+chaining, and executable-bit setting. No execution of git, push, or the hook itself. No archive/upload/credential logic. No `rclone config` / login (user-setup doc). No edits to any existing tracked file in either repo — the ONLY runtime write is `.git/hooks/pre-push` (untracked git infrastructure, not repo source). No edits to any `_NEVER_AUTO_APPROVE` file. No third-party imports (stdlib only). Does NOT author its own oracle — `tests/drive_backup/test_install_hooks.py` is the hand-authored RED precondition and is authoritative if a pinned name differs.

# Inputs

The git hooks layout (`<repo>/.git/hooks/pre-push`, must be executable, receives refs on stdin). The module path it execs: `python -m tools.drive_backup.hook_runner` from drive-backup-hook-runner. The two install targets: `/home/xnihil0zer0/JanusMaskJR` and `/home/xnihil0zer0/NobleGreedv2`. Per-leaf contract: the committed `tests/drive_backup/test_install_hooks.py` oracle. (The actual install run + the one-time `rclone config` are USER steps documented in `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md`.)

# Required plan shape

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY TWO tasks. One new `.py` module is created at `tools/drive_backup/install_hooks.py` (NOT a sensitive apply-glob), so the impl task uses a normal non-test type (`cli_tooling`). Live integration (actually writing `.git/hooks/pre-push` in either repo) is genuinely DEFERRED to the user-run install step, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals` (the install branches are exercised by unit tests against an injected fake `fs` seam). The created module is proven by a paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to the impl's `.py` (the auto-authored, mutation-gated oracle IS the wiring/contract proof; an impl-first DAG makes a `*_wired` verification_command structurally impossible, which is expected).

Emit these tasks verbatim in shape:

1. `task_id: "installer-impl"`
   - `meta_task_type: "cli_tooling"` (one NEW single-file stdlib-only module; NOT `refactor` — this is a new-module creation, not an edit of an existing file).
   - `spec_author: null` (REQUIRED field — emit exactly `null`, never omit it).
   - `priority: "high"`, `estimated_complexity: "medium"`.
   - `files_touched: ["tools/drive_backup/install_hooks.py"]`
   - `dependencies: []`  (the built sibling drive-backup-hook-runner leaf is NOT a task dependency)
   - `verification_command: "python -m pytest tests/drive_backup/test_install_hooks.py -q"`  (NO leading/embedded `cd `)
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Live integration — actually writing .git/hooks/pre-push in either repo — is OUT OF SCOPE here; deferred to the user-run install step. The created/updated/chained/dry branches are exercised against an injected fake fs seam only."

TEST-SPEC BALANCE for `installer-impl` (planner gates, all severity=error — satisfy ALL; the committed RED oracle `tests/drive_backup/test_install_hooks.py` (8 tests) is authoritative and already pins these):
- `spec.functional_requirements`: a TIGHT list of EXACTLY 6: (1) `DEFAULT_REPOS == ['/home/xnihil0zer0/JanusMaskJR', '/home/xnihil0zer0/NobleGreedv2']` and `SENTINEL` marker is defined; (2) `render_shim(janusmask_root)` returns a `#!/usr/bin/env bash` shim bounded by `SENTINEL`, embedding the ABSOLUTE `janusmask_root`, `python -m tools.drive_backup.hook_runner`, and an unconditional `exit 0`; (3) `render_shim(..., chained_hook=...)` runs the saved original hook with the same stdin before the backup step; (4) `install` writes the shim when no hook exists (action `created`) and sets mode 0o755 via the `fs` seam; (5) `install` rewrites in place when a `SENTINEL`-managed shim exists (action `updated`, idempotent — never duplicated); (6) `install` moves a foreign non-managed hook to `pre-push.pre-janusmask` and chains to it (action `chained`), and `dry_run=True` computes the action/target without writing (action suffixed `:dry`).
- `test_spec.unit_tests`: at least 6 entries (`len(unit_tests) >= len(functional_requirements)`) — ONE mapping each requirement above.
- `test_spec.edge_cases`: ≥2 entries, EACH mirrored in `regression_tests` OR `property_tests`: (a) re-running `install` on a managed shim is IDEMPOTENT (action `updated`, sentinel never duplicated); (b) a pre-existing FOREIGN hook is PRESERVED (moved to `pre-push.pre-janusmask`) and chained, never destroyed.
- `test_spec.integration_tests`: MAY be empty ONLY because the gate is excused via the **integration** line in `spec.non_goals`.
- `test_spec.minimum_test_count`: >= 9 (>= `1.5 * len(functional_requirements)`).
- `token_budget_ratio.test_tokens` MUST be >= `1.5 * token_budget_ratio.implementation_tokens`.

2. `task_id: "installer-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "tools.drive_backup.install_hooks"`
   - `files_touched: ["tests/drive_backup/test_install_hooks.py"]`
   - `dependencies: ["installer-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/drive_backup/test_install_hooks.py -q"`

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `tools.drive_backup.install_hooks` resolves to `tools/drive_backup/install_hooks.py`, which is in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption.

`check_wired` is satisfied orphan-by-design via the committed static manifest `config/drive_backup_modules.yaml` (this module is reached from the git pre-push hook / user-run install step, not from a Python `LIVE_ROOT`; wiring is proven by the manifest, NOT by a `*_wired` verification_command). Do NOT add a `*_wired` command to any task in this plan.

# Deliverables

One GREEN NEW module verified by `python -m pytest tests/drive_backup/test_install_hooks.py -q`. Frozen surfaces: `install_hooks.SENTINEL`, `install_hooks.DEFAULT_REPOS` (`['/home/xnihil0zer0/JanusMaskJR', '/home/xnihil0zer0/NobleGreedv2']`), `install_hooks.render_shim(janusmask_root, *, chained_hook=None) -> str`, `install_hooks.InstallResult` (fields `repo, hook_path, action, ok`), `install_hooks.install(repo_roots=DEFAULT_REPOS, *, fs, janusmask_root, dry_run=False) -> list[InstallResult]`, `install_hooks.main(argv=None, *, fs=None) -> int`. After the user runs `python -m tools.drive_backup.install_hooks`, both repos fire the backup on every `git push` without ever blocking it.

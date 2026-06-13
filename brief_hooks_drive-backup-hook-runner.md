---
complexity_score: 4
dependencies:
  - "drive-backup-archiver"
  - "drive-backup-uploader"
interfaces: "tools/drive_backup/hook_runner.py: parse_push_refs(stdin_text) -> list[PushRef{local_ref, local_sha, remote_ref, remote_sha}]; pushed_shas(refs) -> list[str]; run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int (ALWAYS 0); main(argv=None, *, stdin=None, repo_root=None, build_deps=None) -> int (ALWAYS 0)."
---

# Title

Drive-backup hook runner: the git `pre-push` entrypoint that parses pushed refs from stdin, orchestrates archiver → uploader → ledger.record for the pushed commit, logs all failures loudly, and ALWAYS returns 0 so a push is never blocked by backup activity.

# Scope

Build a NEW single-file, whole-file, stdlib-only module `tools/drive_backup/hook_runner.py`, IMPL-only against its pre-committed RED oracle.

- `parse_push_refs(stdin_text)` parses git's pre-push stdin lines (`<local_ref> <local_sha> <remote_ref> <remote_sha>`) into `PushRef` records; tolerates blank lines and the deletion sentinel (all-zero local_sha) by skipping it.
- `pushed_shas(refs)` returns the deduped list of non-deletion `local_sha` values to back up.
- `run_backup(repo_root, refs, *, archiver, uploader, ledger, log)`: for the pushed sha(s), reads `ledger.last_backed_up_sha()` as `base_sha`, calls the injected `archiver` to build the artifact, calls the injected `uploader` to upload (or queue) it, then `ledger.record(sha, archive_name, uploaded)`. EVERY exception from archiver/uploader/ledger is caught and reported via the injected `log` seam (structured line). The ledger is recorded only after a successful archive. Returns `0` ALWAYS — success, partial failure, or total failure all return 0.
- `main(argv=None, *, stdin=None, repo_root=None, build_deps=None)`: the CLI/`python -m` shim — reads refs from the injected `stdin` (defaults to `sys.stdin` at runtime), resolves `repo_root` (defaults to the git toplevel at runtime), builds real archiver/uploader/ledger/log via `build_deps` (an injected factory; defaults to real wiring at runtime), delegates to `run_backup`, and returns its result. ALWAYS returns 0; any top-level exception is swallowed-and-logged then 0 is returned.

# Non-Goals

No real archive/upload/git/network in any tested path — `archiver`, `uploader`, `ledger`, `log`, `stdin`, `build_deps` are injected seams; tests use fakes/spies and assert: ref parsing (including deletion-skip and blank lines), base_sha wiring from the ledger, the orchestration order, that EVERY failure path still returns 0, and that failures are logged. No subprocess spawning in the module itself (delegated to the injected archiver/uploader runner seams). No hook installation (that is drive-backup-installer). No edits to any existing file (module is NEW). No edits to any `_NEVER_AUTO_APPROVE` file. No third-party imports (stdlib only). Does NOT author its own oracle — `tests/drive_backup/test_hook_runner.py` is the hand-authored RED precondition and is authoritative if a pinned name differs.

# Inputs

Git's `pre-push` hook contract: refs arrive on STDIN as `<local_ref> <local_sha> <remote_ref> <remote_sha>` lines; a nonzero hook exit ABORTS the push (hence the absolute exit-0 contract). Consumes `archiver.build_archive(...) -> ArchiveResult` and `archiver.ledger.BackupLedger` from drive-backup-archiver, and `uploader.upload(...) -> UploadResult` from drive-backup-uploader (all as injected seams in tests). Per-leaf contract: the committed `tests/drive_backup/test_hook_runner.py` oracle.

# Required plan shape

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY TWO tasks. One new `.py` module is created at `tools/drive_backup/hook_runner.py` (NOT a sensitive apply-glob), so the impl task uses a normal non-test type (`io_adapter`). Live integration (installing/firing the real pre-push hook) is genuinely DEFERRED to the dependent `drive-backup-installer` leaf and the user-run install step, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals` (orchestration of the injected archiver/uploader/ledger seams is exercised by unit tests with fakes/spies). The created module is proven by a paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to the impl's `.py` (the auto-authored, mutation-gated oracle IS the wiring/contract proof; an impl-first DAG makes a `*_wired` verification_command structurally impossible, which is expected).

Emit these tasks verbatim in shape:

1. `task_id: "hook-runner-impl"`
   - `meta_task_type: "io_adapter"` (one NEW single-file stdlib-only module; NOT `refactor` — this is a new-module creation, not an edit of an existing file).
   - `spec_author: null` (REQUIRED field — emit exactly `null`, never omit it).
   - `priority: "high"`, `estimated_complexity: "medium"`.
   - `files_touched: ["tools/drive_backup/hook_runner.py"]`
   - `dependencies: []`  (the built sibling drive-backup-archiver/uploader leaves are NOT task dependencies)
   - `verification_command: "python -m pytest tests/drive_backup/test_hook_runner.py -q"`  (NO leading/embedded `cd `)
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Live integration — installing and firing the real .git/hooks/pre-push hook — is OUT OF SCOPE here; deferred to the dependent drive-backup-installer leaf and the user-run install step. All archiver/uploader/ledger collaborators are injected seams exercised with fakes."

TEST-SPEC BALANCE for `hook-runner-impl` (planner gates, all severity=error — satisfy ALL; the committed RED oracle `tests/drive_backup/test_hook_runner.py` (9 tests) is authoritative and already pins these):
- `spec.functional_requirements`: a TIGHT list of EXACTLY 6: (1) `parse_push_refs(stdin_text)` parses `<local_ref> <local_sha> <remote_ref> <remote_sha>` lines into `PushRef` records, tolerating blank lines and SKIPPING the all-zero deletion sentinel; (2) `pushed_shas(refs)` returns the deduped non-deletion `local_sha` list; (3) `run_backup` reads `ledger.last_backed_up_sha()` as `base_sha`, calls injected `archiver`→`uploader`→`ledger.record` in order; (4) `run_backup` returns `0` ALWAYS and catches+logs EVERY exception from archiver/uploader/ledger via the `log` seam; (5) the ledger is recorded only after a successful archive (records uploaded-vs-queued); (6) `main(argv=None, *, stdin, repo_root, build_deps)` reads injected stdin, delegates to `run_backup`, returns `0` ALWAYS and swallows+logs any top-level exception (including `build_deps` raising).
- `test_spec.unit_tests`: at least 6 entries (`len(unit_tests) >= len(functional_requirements)`) — ONE mapping each requirement above.
- `test_spec.edge_cases`: ≥2 entries, EACH mirrored in `regression_tests` OR `property_tests`: (a) `run_backup` STILL returns 0 when the archiver, uploader, OR ledger.record raises; (b) `parse_push_refs` SKIPS blank lines and the all-zero deletion sentinel.
- `test_spec.integration_tests`: MAY be empty ONLY because the gate is excused via the **integration** line in `spec.non_goals`.
- `test_spec.minimum_test_count`: >= 9 (>= `1.5 * len(functional_requirements)`).
- `token_budget_ratio.test_tokens` MUST be >= `1.5 * token_budget_ratio.implementation_tokens`.

2. `task_id: "hook-runner-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "tools.drive_backup.hook_runner"`
   - `files_touched: ["tests/drive_backup/test_hook_runner.py"]`
   - `dependencies: ["hook-runner-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/drive_backup/test_hook_runner.py -q"`

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `tools.drive_backup.hook_runner` resolves to `tools/drive_backup/hook_runner.py`, which is in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption.

`check_wired` is satisfied orphan-by-design via the committed static manifest `config/drive_backup_modules.yaml` (this module is reached from the git pre-push hook, not from a Python `LIVE_ROOT`; wiring is proven by the manifest + the dependent installer leaf, NOT by a `*_wired` verification_command). Do NOT add a `*_wired` command to any task in this plan.

# Deliverables

One GREEN NEW module verified by `python -m pytest tests/drive_backup/test_hook_runner.py -q`. Frozen surfaces: `hook_runner.parse_push_refs(stdin_text) -> list[PushRef]` (fields `local_ref, local_sha, remote_ref, remote_sha`), `hook_runner.pushed_shas(refs) -> list[str]`, `hook_runner.run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int` (ALWAYS 0, never raises), `hook_runner.main(argv=None, *, stdin=None, repo_root=None, build_deps=None) -> int` (ALWAYS 0). This is the module the installed pre-push shim execs via `python -m tools.drive_backup.hook_runner`.

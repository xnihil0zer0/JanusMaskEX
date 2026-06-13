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

# Deliverables

One GREEN NEW module verified by `python -m pytest tests/drive_backup/test_hook_runner.py -q`. Frozen surfaces: `hook_runner.parse_push_refs(stdin_text) -> list[PushRef]` (fields `local_ref, local_sha, remote_ref, remote_sha`), `hook_runner.pushed_shas(refs) -> list[str]`, `hook_runner.run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int` (ALWAYS 0, never raises), `hook_runner.main(argv=None, *, stdin=None, repo_root=None, build_deps=None) -> int` (ALWAYS 0). This is the module the installed pre-push shim execs via `python -m tools.drive_backup.hook_runner`.

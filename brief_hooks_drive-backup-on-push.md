---
epic: true
complexity_score: 7
dependencies:
  - "drive-backup-archiver"
  - "drive-backup-uploader"
  - "drive-backup-hook-runner"
  - "drive-backup-installer"
interfaces: "tools/drive_backup/archiver.py: build_archive(repo_root, sha, *, runner, now, exclude=DEFAULT_EXCLUDES) -> ArchiveResult{archive_path, diff_path, base_sha, manifest}. tools/drive_backup/uploader.py: upload(archive_result, *, remote, runner, queue_dir, now) -> UploadResult{uploaded: bool, queued: bool, remote_path, error}. drive_backup_drain(queue_dir, *, remote, runner) -> list[UploadResult]. tools/drive_backup/hook_runner.py: run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int (ALWAYS 0). tools/drive_backup/ledger.py: BackupLedger(path seam): last_backed_up_sha(); record(sha, archive_name, uploaded). tools/drive_backup/install_hooks.py: install(repo_roots, *, fs, dry_run=False) -> list[InstallResult]."
---

# Title

On every git push of NobleGreedv2 and JanusMaskJR, capture a whole-project-directory backup (tar.zst snapshot + git diff vs last-backed-up commit) and upload it to the user's Google Drive via an rclone `gdrive:` remote — driven by a local git `pre-push` hook that NEVER blocks the push.

# Scope

Build the deterministic Drive-backup-on-push subsystem as NEW single-file, whole-file, stdlib-only modules under `tools/drive_backup/`, each IMPL-only against its pre-committed RED oracle. All external effects (subprocess `tar`/`zstd`/`git`, the `rclone` upload, filesystem writes, wall clock) are INJECTED SEAMS so every oracle is hermetic. Four leaves compose this epic:

1. **drive-backup-archiver** (`tools/drive_backup/archiver.py` + `tools/drive_backup/ledger.py`) — produce the backup artifact for a pushed commit: a timestamped `tar.zst` of the WHOLE working tree at the pushed `sha` PLUS a `git diff base_sha..sha` text, where `base_sha` is read from a local ledger of the last-backed-up commit. Artifacts named `<repo>_<sha7>_<utc_iso_compact>` (archive `.tar.zst`, diff `.diff`). Honors "whole project directory" but applies DEFAULT_EXCLUDES for caches (`node_modules`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `*.pyc`, `state/output`, `_autowork_archive`) and records the exclude list into the artifact manifest so what was dropped is explicit. The `.git` directory is INCLUDED by default (whole-dir honored) but exclusion is configurable. All tar/zstd/git calls go through an injected `runner` seam; `now` is an injected clock.

2. **drive-backup-uploader** (`tools/drive_backup/uploader.py`) — push the archive+diff to a Google-Drive rclone remote (default remote name `gdrive:`, target subfolder `repo-push-backups/<repo>/`). Fail LOUDLY (structured error) but NON-BLOCKING: on any rclone failure, copy the artifacts into a local `queue_dir` and mark `queued=True`, never raise. Expose `drive_backup_drain(queue_dir, ...)` that re-attempts queued uploads idempotently (skip already-present remote names). All rclone invocations go through the injected `runner` seam.

3. **drive-backup-hook-runner** (`tools/drive_backup/hook_runner.py`) — the entrypoint the git hook calls: `run_backup(repo_root, refs, *, archiver, uploader, ledger, log)` orchestrates archiver→uploader→ledger.record and ALWAYS returns 0 (a push is NEVER blocked by backup failure). Catches every exception from the injected archiver/uploader, logs it via the injected `log` seam, and still returns 0. Updates the ledger only after a successful archive (records whether upload succeeded or was queued).

4. **drive-backup-installer** (`tools/drive_backup/install_hooks.py`) — idempotently install a thin `pre-push` shim into BOTH repos' `.git/hooks/pre-push` (JanusMaskJR + NobleGreedv2). The shim is a small `#!/usr/bin/env bash` script that resolves the JanusMaskJR `tools/drive_backup` entry module by absolute path and execs `python -m tools.drive_backup.hook_runner` with the pushed refs on stdin, then ALWAYS `exit 0`. Install is idempotent (re-running detects the existing JanusMask-managed shim by a sentinel marker and rewrites in place), preserves any pre-existing non-managed pre-push hook by chaining to it, and supports `dry_run`. Filesystem ops go through an injected `fs` seam.

# Wiring prerequisite (CONFIG_WIRED manifest)

The four `tools/drive_backup/*.py` modules (5 files) are orphan-by-design: they are driven by a runtime git pre-push hook (`python -m tools.drive_backup.hook_runner`), NOT by a static import edge from a JM live root. The prior `archiver-impl` build was rejected with `orphan_unwired` for exactly this reason. The fix is a CONFIG_WIRED registration: `config/drive_backup_modules.yaml` lists each module as an explicit `.py` path (one per line), which `harness/wire_up.py::_grep_config` recognizes (clause `(?<![\w.])<stem>\.py\b`). That manifest is already created on disk. Because it lives under `config/**` (a sensitive glob), any FACTORY-driven (re)creation of it MUST be a `meta_task_type: harness_self_fix` task with its own RED oracle + decision file. As a static data file with no code, the cleanest path is the already-hand-created manifest (verified live against `_grep_config`); the factory does not need to author it.

# Non-Goals

No real subprocess, real `rclone` call, real network, or real `tar`/`git` execution in ANY tested path — `runner`, `fs`, `log`, `now`, archiver/uploader/ledger are injected seams. No `rclone` install and no `rclone config` performed by code — that is a one-time USER action documented in `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md` (the uploader only assumes a configured `gdrive:` remote exists and surfaces a clear error if it does not). No secrets, tokens, or credentials committed to either repo — the rclone credential lives in `~/.config/rclone/rclone.conf` (or an env-pointed path) OUTSIDE both repos. No git post-push hook (none exists client-side; pre-push is the mechanism). The hook MUST NOT block, slow-fail, or abort a push under any circumstance. No edits to any existing file in either repo except creating `.git/hooks/pre-push` via the installer. No edits to any `_NEVER_AUTO_APPROVE` file. No new network-exposed surface. Does NOT author its own oracles — the per-leaf RED oracles under `tests/drive_backup/` are hand-authored preconditions and are authoritative where a pinned name differs.

# Inputs

The JanusMaskJR repo (self-build, modules live here) and the sibling NobleGreedv2 repo at `/home/xnihil0zer0/NobleGreedv2` (second pre-push install target). Reusable knowledge (NOT edited): git's `pre-push` hook contract (refs arrive on stdin as `<local_ref> <local_sha> <remote_ref> <remote_sha>` lines; hook runs LOCALLY before the push proceeds; a nonzero exit aborts the push — so the runner forces exit 0). The `zstd` binary at `/home/xnihil0zer0/miniconda3/bin/zstd` and system `tar` at `/usr/bin/tar` (invoked only via the injected runner at runtime; tests do not call them). rclone is NOT yet installed — its one-time setup is the user-setup doc, consumed at runtime only. Per-leaf contracts are the committed `tests/drive_backup/test_<leaf>.py` oracles.

# Deliverables

Four GREEN leaves (decomposed children), each verified per-leaf (not globbed):
- `tools/drive_backup/archiver.py` + `tools/drive_backup/ledger.py` — `python -m pytest tests/drive_backup/test_archiver.py tests/drive_backup/test_ledger.py -q`
- `tools/drive_backup/uploader.py` — `python -m pytest tests/drive_backup/test_uploader.py -q`
- `tools/drive_backup/hook_runner.py` — `python -m pytest tests/drive_backup/test_hook_runner.py -q`
- `tools/drive_backup/install_hooks.py` — `python -m pytest tests/drive_backup/test_install_hooks.py -q`

Frozen public surfaces: `archiver.build_archive(repo_root, sha, *, runner, now, exclude) -> ArchiveResult`; `ledger.BackupLedger(path).last_backed_up_sha()/record(...)`; `uploader.upload(archive_result, *, remote, runner, queue_dir, now) -> UploadResult` and `uploader.drive_backup_drain(queue_dir, *, remote, runner)`; `hook_runner.run_backup(repo_root, refs, *, archiver, uploader, ledger, log) -> int` (ALWAYS 0); `install_hooks.install(repo_roots, *, fs, dry_run=False) -> list[InstallResult]`. Acceptance: the pre-push shim, once installed by the user into both repos, produces on each push a `<repo>_<sha7>_<ts>.tar.zst` + `.diff` uploaded to `gdrive:repo-push-backups/<repo>/` (or queued locally on Drive outage) WITHOUT ever blocking the push. The exact one-time user login/install steps are in `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md`.

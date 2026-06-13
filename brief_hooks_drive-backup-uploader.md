---
complexity_score: 4
dependencies:
  - "drive-backup-archiver"
interfaces: "tools/drive_backup/uploader.py: DEFAULT_REMOTE ('gdrive:'); remote_dir_for(repo, *, remote=DEFAULT_REMOTE) -> str; UploadResult dataclass{uploaded: bool, queued: bool, remote_path, error}; upload(archive_result, *, remote=DEFAULT_REMOTE, runner, queue_dir, now) -> UploadResult; drive_backup_drain(queue_dir, *, remote=DEFAULT_REMOTE, runner) -> list[UploadResult]."
---

# Title

Drive-backup uploader: copy the `tar.zst` archive + `.diff` to a Google-Drive rclone remote (`gdrive:repo-push-backups/<repo>/`), failing LOUDLY but NON-BLOCKING — on any rclone error, queue the artifacts locally and retry-drain idempotently — never raising.

# Scope

Build a NEW single-file, whole-file, stdlib-only module `tools/drive_backup/uploader.py`, IMPL-only against its pre-committed RED oracle.

`upload(archive_result, *, remote=DEFAULT_REMOTE, runner, queue_dir, now)`:
- Resolves the remote target via `remote_dir_for(repo, remote)` → `"<remote>repo-push-backups/<repo>/"` (default remote `"gdrive:"`).
- Invokes, through the injected `runner` seam, `rclone copyto <archive_path> <remote_path>/<name>` for BOTH the archive and the diff (argv constructed and asserted by tests; no real rclone run).
- On runner success → `UploadResult(uploaded=True, queued=False, remote_path=..., error=None)`.
- On ANY failure (nonzero rc, runner raising, rclone-not-found): copies BOTH artifacts into `queue_dir/<name>` (filesystem copy via stdlib `shutil`), writes a small sidecar `<name>.queued.json` recording the intended remote_path + error + `now()`, and returns `UploadResult(uploaded=False, queued=True, remote_path=..., error=<structured str>)`. NEVER raises.

`drive_backup_drain(queue_dir, *, remote=DEFAULT_REMOTE, runner)`:
- Scans `queue_dir` for queued artifacts, re-attempts `rclone copyto` for each via the runner, and on success removes the local copy + its sidecar (idempotent: a name already absent is a no-op). Returns a `list[UploadResult]`. Failures stay queued; the drain itself never raises.

`remote_dir_for(repo, *, remote=DEFAULT_REMOTE)` is the pure path helper. `DEFAULT_REMOTE = "gdrive:"`. All rclone calls go through the injected `runner`; `now()` is the injected clock.

# Non-Goals

No real `rclone` invocation, no network, no Google-Drive API, no credential reading/writing in any tested path — `runner` is the injected seam; tests assert argv shape, remote-path construction, the success→uploaded and failure→queued branches, the never-raise contract, and drain idempotency. No `rclone config` / login performed by code (that is the user-setup doc). No secrets in the repo (the credential lives in `~/.config/rclone/rclone.conf` outside both repos; this module only references the remote NAME). No archive building (consumes an `ArchiveResult` from drive-backup-archiver). No edits to any existing file (module is NEW). No edits to any `_NEVER_AUTO_APPROVE` file. No third-party imports (stdlib only). Does NOT author its own oracle — `tests/drive_backup/test_uploader.py` is the hand-authored RED precondition and is authoritative if a pinned name differs.

# Resource hygiene (BUILD-BLOCKING — sibling archiver-impl died `auto_commit_failed_r1`)

The uploader copies artifacts into `queue_dir` and writes `.queued.json` sidecars; it MUST keep the staging worktree removable:
- NEVER default `queue_dir` (or any write path) to a location inside the repo/working tree — it is a caller-supplied seam; default destinations MUST NOT be `.`, `os.getcwd()`, or `__file__`'s dir. Any scratch space uses `tempfile` under the system temp dir.
- Close EVERY file handle deterministically (context managers / `try/finally`); leave no open handles, `.lock`/`-wal`/`-shm` sidecars, or temp dirs inside the repo so `git worktree remove -f` exits 0.
- NEVER create a nested `.git/` and NEVER spawn a real subprocess/network call in any tested path (rclone is the injected `runner` seam only).

# Inputs

Consumes `archiver.ArchiveResult` (fields `archive_path, diff_path, base_sha, manifest`) from drive-backup-archiver. The rclone `copyto` CLI shape (`rclone copyto <src> <remote>:<path>`) and the convention that a configured Google-Drive remote is named `gdrive:` (documented in `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md`). Per-leaf contract: the committed `tests/drive_backup/test_uploader.py` oracle.

# Required plan shape

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY TWO tasks. One new `.py` module is created at `tools/drive_backup/uploader.py` (NOT a sensitive apply-glob), so the impl task uses a normal non-test type (`io_adapter`). Integration wiring (the pre-push hook orchestration) is genuinely DEFERRED to the dependent `drive-backup-hook-runner` / `drive-backup-installer` leaves, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals`. The created module is proven by a paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to the impl's `.py` (the auto-authored, mutation-gated oracle IS the wiring/contract proof; an impl-first DAG makes a `*_wired` verification_command structurally impossible, which is expected).

Emit these tasks verbatim in shape:

1. `task_id: "uploader-impl"`
   - `meta_task_type: "io_adapter"`
   - `files_touched: ["tools/drive_backup/uploader.py"]`
   - `dependencies: []`
   - `verification_command: "python -m pytest tests/drive_backup/test_uploader.py -q"`  (NO leading/embedded `cd `)
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Integration wiring into the pre-push hook orchestration is OUT OF SCOPE here — deferred to the dependent drive-backup-hook-runner and drive-backup-installer leaves; this leaf only builds the uploader seam."

2. `task_id: "uploader-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "tools.drive_backup.uploader"`
   - `files_touched: ["tests/drive_backup/test_uploader.py"]`
   - `dependencies: ["uploader-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/drive_backup/test_uploader.py -q"`

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `tools.drive_backup.uploader` resolves to `tools/drive_backup/uploader.py`, which is in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption.

# Deliverables

One GREEN NEW module verified by `python -m pytest tests/drive_backup/test_uploader.py -q`. Frozen surfaces: `uploader.DEFAULT_REMOTE` (`"gdrive:"`), `uploader.remote_dir_for(repo, *, remote=DEFAULT_REMOTE) -> str`, `uploader.UploadResult` (fields `uploaded, queued, remote_path, error`), `uploader.upload(archive_result, *, remote=DEFAULT_REMOTE, runner, queue_dir, now) -> UploadResult` (never raises; success→uploaded, failure→queued), `uploader.drive_backup_drain(queue_dir, *, remote=DEFAULT_REMOTE, runner) -> list[UploadResult]` (idempotent retry).

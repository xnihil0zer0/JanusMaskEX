---
complexity_score: 4
interfaces: "tools/drive_backup/archiver.py: DEFAULT_EXCLUDES (frozenset); ArchiveResult dataclass{archive_path, diff_path, base_sha, manifest}; build_archive(repo_root, sha, *, runner, now, out_dir, exclude=DEFAULT_EXCLUDES, base_sha=None) -> ArchiveResult. tools/drive_backup/ledger.py: BackupLedger(path); last_backed_up_sha() -> str|None; record(sha, archive_name, uploaded: bool) -> None; entries() -> list[dict]."
---

# Title

Drive-backup archiver + ledger: build a timestamped whole-tree `tar.zst` snapshot plus a `git diff` against the last-backed-up commit, named by repo + commit sha + UTC timestamp, with caches excluded and a manifest of what was dropped.

# Scope

Build TWO NEW single-file, whole-file, stdlib-only modules under `tools/drive_backup/`, each IMPL-only against its pre-committed RED oracle.

(1) `tools/drive_backup/ledger.py` — `BackupLedger(path)` where `path` is an EXPLICIT seam (no implicit default in tested surface) to a newline-delimited JSON ledger of prior backups. `last_backed_up_sha()` returns the sha of the most recent recorded entry or `None` if empty/missing. `record(sha, archive_name, uploaded)` appends `{ts?, sha, archive_name, uploaded}` atomically (write-temp-then-rename). `entries()` returns the parsed rows in order. Corrupt/partial trailing lines are skipped, not fatal.

(2) `tools/drive_backup/archiver.py` — `build_archive(repo_root, sha, *, runner, now, out_dir, exclude=DEFAULT_EXCLUDES, base_sha=None)`:
- Computes the artifact stem `<repo_basename>_<sha[:7]>_<now-as-compact-UTC-iso>` (e.g. `JanusMaskJR_a1b2c3d_20260612T231500Z`).
- Builds the WHOLE-working-tree archive at `out_dir/<stem>.tar.zst` by invoking, through the injected `runner` seam, a `tar` create piped to `zstd` (the actual argv is constructed and returned in the manifest; tests assert argv shape and seam usage, NOT real execution). `exclude` (DEFAULT_EXCLUDES) is materialized as `--exclude` args; `.git` is INCLUDED by default (whole-dir honored) unless explicitly listed.
- Builds `out_dir/<stem>.diff` by invoking `git -C repo_root diff <base_sha>..<sha>` through the runner; if `base_sha` is None (first-ever backup), the diff is the empty-base form `git diff <sha>` (full vs empty tree) — recorded as such in the manifest.
- Returns `ArchiveResult(archive_path, diff_path, base_sha, manifest)` where `manifest` is a JSON-able dict capturing `{repo, sha, base_sha, stem, excludes, archive_argv, diff_argv, created_at}`.
- `DEFAULT_EXCLUDES` is a frozenset: `node_modules`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `*.pyc`, `state/output`, `_autowork_archive`.

The injected `runner(argv, **kw) -> CompletedProcess-like` is the ONLY way subprocesses are touched; `now()` is the injected clock (returns a tz-aware UTC datetime).

# Non-Goals

No real `tar`, `zstd`, or `git` execution in any tested path — `runner` and `now` are injected seams; tests assert argv construction, naming, exclude materialization, manifest contents, and ledger round-trip only. No upload logic (that is drive-backup-uploader). No reading of git hook stdin (that is drive-backup-hook-runner). No implicit ledger path default in the tested surface (explicit seam). No edits to any existing file (both modules are NEW). No edits to any `_NEVER_AUTO_APPROVE` file. No third-party imports (stdlib only). Does NOT author its own oracles — `tests/drive_backup/test_archiver.py` and `tests/drive_backup/test_ledger.py` are hand-authored RED preconditions and are authoritative if a pinned name differs.

# Resource hygiene (BUILD-BLOCKING — prior run died `auto_commit_failed_r1`)

The prior `archiver-impl` build applied cleanly but the staging worktree could not be removed (`git worktree remove -f` → exit 128), so it was rejected. Both modules MUST:
- NEVER write archives, ledger DB/state, temp dirs, lock files, or logs into the repo/working tree; all output goes to a caller-supplied path or a `tempfile.mkdtemp()`/`NamedTemporaryFile` area OUTSIDE the repo. Default destinations MUST NOT be `.`, `os.getcwd()`, or `__file__`'s dir.
- NEVER run `git init`/`git clone` or copy a tree containing a nested `.git/` into the worktree.
- Close EVERY file handle / DB connection / lock deterministically (context managers or `try/finally`) — no module-global open handles, no leftover `.lock`/`-wal`/`-shm` sidecars — so the staging worktree removes cleanly with exit 0.

# Inputs

The JanusMaskJR repo (self-build). Git diff semantics for `base_sha..sha` and the empty-base full-diff form. The `tar | zstd` pipeline shape (`tar --use-compress-program=zstd` or explicit pipe — the impl picks one and records the chosen argv in the manifest). Per-leaf contract: the committed `tests/drive_backup/test_archiver.py` and `tests/drive_backup/test_ledger.py` oracles.

# Required plan shape

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY THREE tasks. Two new `.py` modules are created under `tools/drive_backup/` (NOT a sensitive apply-glob), so the impl task uses a normal non-test type (`io_adapter`). Integration wiring (the pre-push hook orchestration) is genuinely DEFERRED to the dependent `drive-backup-hook-runner` / `drive-backup-installer` leaves, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals`. EACH created module is proven by its OWN paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to that module's `.py` (the auto-authored, mutation-gated oracle IS the wiring/contract proof; an impl-first DAG makes a `*_wired` verification_command structurally impossible, which is expected). A leaf creating TWO modules needs TWO paired test_authoring tasks — one per module.

Emit these tasks verbatim in shape:

1. `task_id: "archiver-impl"`
   - `meta_task_type: "io_adapter"` (two NEW single-file stdlib-only modules; NOT `refactor` — these are new-module creations, not edits of existing files).
   - `spec_author: null` (REQUIRED field — emit exactly `null`, never omit it).
   - `priority: "high"`, `estimated_complexity: "medium"`.
   - `files_touched: ["tools/drive_backup/archiver.py", "tools/drive_backup/ledger.py"]`
   - `dependencies: []`
   - `verification_command: "python -m pytest tests/drive_backup/test_archiver.py tests/drive_backup/test_ledger.py -q"`  (NO leading/embedded `cd `)
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Integration wiring into the pre-push hook orchestration is OUT OF SCOPE here — deferred to the dependent drive-backup-hook-runner and drive-backup-installer leaves; this leaf only builds the archiver + ledger seams."

TEST-SPEC BALANCE for `archiver-impl` (planner gates, all severity=error — satisfy ALL; the committed RED oracles `tests/drive_backup/test_archiver.py` (7 tests) + `tests/drive_backup/test_ledger.py` (5 tests) are authoritative and already pin these):
- `spec.functional_requirements`: a TIGHT list of EXACTLY 8 spanning BOTH modules: (1) `archiver.DEFAULT_EXCLUDES` is a frozenset containing the cache dirs; (2) artifact stem is `<repo_basename>_<sha7>_<compactUTC>`; (3) `runner` is the ONLY subprocess seam and the archive argv shape is `tar`→`zstd`; (4) `exclude` entries are materialized as `--exclude` args with `.git` included by default; (5) first-ever backup (`base_sha=None`) uses the empty-base full-diff form; (6) `manifest` is JSON-able and complete (`repo, sha, base_sha, stem, excludes, archive_argv, diff_argv, created_at`); (7) `BackupLedger.record` then `last_backed_up_sha()` returns the most recent sha and round-trips via `entries()`; (8) `last_backed_up_sha()` returns `None` for empty/missing ledger.
- `test_spec.unit_tests`: at least 8 entries (`len(unit_tests) >= len(functional_requirements)`) — ONE mapping each requirement above.
- `test_spec.edge_cases`: ≥2 entries, EACH mirrored in `regression_tests` OR `property_tests`: (a) a corrupt/partial trailing ledger line is SKIPPED, not fatal; (b) recorded entries are DURABLE across separate `BackupLedger` instances (atomic write-temp-then-rename).
- `test_spec.integration_tests`: MAY be empty ONLY because the gate is excused via the **integration** line in `spec.non_goals`.
- `test_spec.minimum_test_count`: >= 12 (>= `1.5 * len(functional_requirements)`).
- `token_budget_ratio.test_tokens` MUST be >= `1.5 * token_budget_ratio.implementation_tokens`.

2. `task_id: "archiver-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "tools.drive_backup.archiver"`
   - `files_touched: ["tests/drive_backup/test_archiver.py"]`
   - `dependencies: ["archiver-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/drive_backup/test_archiver.py -q"`

3. `task_id: "ledger-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "tools.drive_backup.ledger"`
   - `files_touched: ["tests/drive_backup/test_ledger.py"]`
   - `dependencies: ["archiver-impl"]`
   - `verification_command: "python -m pytest tests/drive_backup/test_ledger.py -q"`

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `tools.drive_backup.archiver` resolves to `tools/drive_backup/archiver.py` and `tools.drive_backup.ledger` to `tools/drive_backup/ledger.py`, both in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption for each created module.

`check_wired` is satisfied orphan-by-design via the committed static manifest `config/drive_backup_modules.yaml` (these modules are reached from the git pre-push hook, not from a Python `LIVE_ROOT`; wiring is proven by the manifest + the dependent hook-runner/installer leaves, NOT by a `*_wired` verification_command). Do NOT add a `*_wired` command to any task in this plan.

# Deliverables

Two GREEN NEW modules verified by `python -m pytest tests/drive_backup/test_archiver.py tests/drive_backup/test_ledger.py -q`. Frozen surfaces: `archiver.DEFAULT_EXCLUDES` (frozenset), `archiver.ArchiveResult` (fields `archive_path, diff_path, base_sha, manifest`), `archiver.build_archive(repo_root, sha, *, runner, now, out_dir, exclude=DEFAULT_EXCLUDES, base_sha=None) -> ArchiveResult`; `ledger.BackupLedger(path)` with `last_backed_up_sha() -> str|None`, `record(sha, archive_name, uploaded) -> None`, `entries() -> list[dict]`. Artifact naming is `<repo_basename>_<sha7>_<compactUTC>` with `.tar.zst` and `.diff` siblings.

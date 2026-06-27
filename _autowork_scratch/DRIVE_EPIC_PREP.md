# Drive-backup-on-push epic — factory build prep (2026-06-12)

## Two root-cause fixes applied
1. **orphan_unwired** (archiver-impl at ACCEPTANCE) → CONFIG_WIRED manifest created:
   `config/drive_backup_modules.yaml`. The 5 modules are orphan-by-design (driven by a
   runtime pre-push hook, no static importer from a JM LIVE_ROOT).
2. **auto_commit_failed_r1** (staging worktree un-removable, git exit 128) → resource-hygiene
   constraint blocks added to archiver + uploader briefs (ledger covered by archiver brief).

## CONFIG_WIRED format (LIVE-VERIFIED via harness.wire_up._grep_config)
- `check_wired(...)` for an unreachable module falls back to `_grep_config(repo_root, stem)`
  where stem = Path(rel).stem (e.g. "archiver").
- `_grep_config` pattern (wire_up.py line 302), first clause:  `(?<![\w.])<stem>\.py\b`
- Each module registered as an EXPLICIT `.py` path, ONE PER LINE:
    tools/drive_backup/archiver.py   (leading `/` is not [\w.] → clause matches)
    tools/drive_backup/ledger.py
    tools/drive_backup/uploader.py
    tools/drive_backup/hook_runner.py
    tools/drive_backup/install_hooks.py
- Live check result: all 5 stems → config/drive_backup_modules.yaml. No cross-stem false match.
- A `-m tools.drive_backup.hook_runner` dotted token registers only ONE stem; explicit per-module
  .py paths are required to register all five. Manifest is static data, hand-created (verified) —
  factory does NOT need a harness_self_fix task to author it. If it must be (re)built by the
  factory, that task MUST be meta_task_type: harness_self_fix (config/** is sensitive).

## Plan-shape compliance (all 4 leaf briefs PASS)
- archiver: io_adapter impl + 2 test_authoring oracles (archiver, ledger dotted targets), "integration" in non_goals.
- uploader: io_adapter impl + 1 test_authoring (uploader), "integration" in non_goals.
- hook-runner: io_adapter impl + 1 test_authoring (hook_runner), "integration" in non_goals.
- installer: cli_tooling impl + 1 test_authoring (install_hooks), "integration" in non_goals.
- All headings present; all mutation_targets bare-dotted resolving to files_touched .py. None sensitive (tools/**).

## Wave plan + DAG + allowlist
- MANIFEST: already on disk (config/drive_backup_modules.yaml). No build task. Owner: keep committed BEFORE Wave A so the wire_up accept gate sees it.
- Wave A (deps none): drive-backup-archiver  → builds archiver.py + ledger.py
    allowlist slug: drive-backup-archiver
- Wave B (deps archiver/ledger): drive-backup-uploader
    allowlist slug: drive-backup-uploader
- Wave C (deps uploader): drive-backup-hook-runner
    allowlist slug: drive-backup-hook-runner
- Wave D (deps hook-runner): drive-backup-installer
    allowlist slug: drive-backup-installer
- Daemon auto-plans 1 brief/iter by newest mtime; allowlist alone != build. Dispatch wave-by-wave (owner-supervised).
- rclone gdrive: OAuth is an OWNER one-time step (DRIVE_BACKUP_USER_SETUP.md). Modules BUILD without it;
  oracles make NO live network/subprocess calls (rclone/tar/git/fs all injected seams). Only full live
  verification of uploader/installer needs the configured remote.

## NOT done (per instructions): no commit, no dispatch.

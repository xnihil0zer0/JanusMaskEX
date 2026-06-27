# Drive-backup Waves B/C/D readiness (2026-06-13)

Reference recipe (Wave A archiver, commit 31e7d06): stage planned impl task →
edit verification_command to the REAL committed pytest oracle → inject committed
oracle SOURCE into spec.implementation_notes → run worker dual-agent. check_wired
satisfied orphan-by-design via committed `config/drive_backup_modules.yaml`.

All committed oracles VERIFIED present via `git ls-files tests/drive_backup/`:
test_archiver.py, test_ledger.py, test_uploader.py, test_hook_runner.py, test_install_hooks.py
Committed impls present: tools/drive_backup/{archiver,ledger}.py (Wave A done).

## Wave B — uploader  (brief_hooks_drive-backup-uploader.md)
- impl task_id:   `uploader-impl`  (meta_task_type io_adapter)
- oracle task_id: `uploader-oracle` (mutation_target tools.drive_backup.uploader)
- committed oracle: tests/drive_backup/test_uploader.py  (8 tests)
- files_touched:  ["tools/drive_backup/uploader.py"]  → SINGLE-FILE
- verification_command: python -m pytest tests/drive_backup/test_uploader.py -q
- TEST-SPEC BALANCE block: ADDED (FR=6, unit>=6, edge>=2, min_test_count>=9, test_tokens>=1.5x impl)
- check_wired note + spec_author:null: ADDED
- STATUS: READY

## Wave C — hook-runner  (brief_hooks_drive-backup-hook-runner.md)
- impl task_id:   `hook-runner-impl`  (meta_task_type io_adapter)
- oracle task_id: `hook-runner-oracle` (mutation_target tools.drive_backup.hook_runner)
- committed oracle: tests/drive_backup/test_hook_runner.py  (9 tests)
- files_touched:  ["tools/drive_backup/hook_runner.py"]  → SINGLE-FILE
- verification_command: python -m pytest tests/drive_backup/test_hook_runner.py -q
- TEST-SPEC BALANCE block: ADDED (FR=6, unit>=6, edge>=2, min_test_count>=9, test_tokens>=1.5x impl)
- check_wired note + spec_author:null: ADDED
- STATUS: READY

## Wave D — installer  (brief_hooks_drive-backup-installer.md)
- impl task_id:   `installer-impl`  (meta_task_type cli_tooling)
- oracle task_id: `installer-oracle` (mutation_target tools.drive_backup.install_hooks)
- committed oracle: tests/drive_backup/test_install_hooks.py  (8 tests)
- files_touched:  ["tools/drive_backup/install_hooks.py"]  → SINGLE-FILE
- verification_command: python -m pytest tests/drive_backup/test_install_hooks.py -q
- TEST-SPEC BALANCE block: ADDED (FR=6, unit>=6, edge>=2, min_test_count>=9, test_tokens>=1.5x impl)
- check_wired note + spec_author:null: ADDED
- STATUS: READY

## Integration leaf — on-push  (brief_hooks_drive-backup-on-push.md)
- frontmatter `epic: true`; deps = all 4 leaves. NO `# Required plan shape` / NO impl task.
- This is the EPIC PARENT / pure integration-verification spec (Deliverables = the 4
  per-leaf green pytest commands + the user-run install acceptance). NOT a drivable leaf.
- STATUS: N/A — pure-integration-verification (no impl). Nothing to plan/drive; satisfied
  once B/C/D land green (A already green). NO oracle of its own.

## Blockers
- NONE. All 5 referenced oracles exist; no fabricated paths. No missing-oracle blocker.

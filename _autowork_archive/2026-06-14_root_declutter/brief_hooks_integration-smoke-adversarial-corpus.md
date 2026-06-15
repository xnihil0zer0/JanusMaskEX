---
dependencies:
  - "integration_smoke_classifiers"
interfaces: "consumes is_io_bound(...) -> IoBoundResult(io_bound, signals, reason) and has_executing_integration_oracle(...) -> SmokeOracleResult(present, oracle_files, reason, fix_hint) plus BOUNDARY_SIGNALS, ENTRYPOINT_NAMES, BOUNDARY_MOCK_ALLOWLIST from harness/integration_smoke.py"
---

# Title

Adversarial acceptance corpus (Layer 3, test-only)

# Scope

Build the committed adversarial corpus `tests/harness/test_integration_smoke_adversarial.py` (a `test_authoring` corpus leaf) that concentrates the attack/evasion fixtures the gate MUST get right, pinning both true-positives (catches the bug) and true-negatives (no false friction) against the substrate classifiers. Required fixtures: Evasion 1 — import-OK / call-raises module with an import-only oracle ⇒ REJECT (the drive_backup ImportError-in-factory shape); Evasion 2 — fake integration oracle that `monkeypatch.setattr`s the entrypoint or passes a fake `build_deps` ⇒ classified HERMETIC ⇒ REJECT (the exact pattern that hid the original bug); Evasion 3 — boundary-only mock (real entrypoint called, only `subprocess.run`/`socket` mocked) ⇒ EXECUTING ⇒ PASS; false-positive guard — pure-logic module with only unit tests ⇒ NOT I/O-bound ⇒ PASS with no oracle required; the full I/O-signal coverage matrix (one fixture per signal: subprocess, socket, urllib, file write, os.system, shutil, `__main__`, tool-argv git/tar/rclone) each classified I/O-bound; the drive_backup regression — the fixed `hook_runner`/`archiver` + their executing oracles ⇒ PASS, the pre-fix adapter shape + hermetic-only oracle ⇒ REJECT; and idempotency/purity — classifiers are deep-copy-pure and deterministic across repeated calls.

# Non-Goals

Do NOT modify production code — this child is test-only. Do NOT modify or re-fix `tools/drive_backup/hook_runner.py`, `tools/drive_backup/archiver.py`, or their tests (already fixed by hand; reference their shapes only). Do NOT spawn processes or make network/model calls; fixtures are in-memory source strings fed to the pure classifiers. Do NOT re-implement the classifiers — import them. Do NOT claim assertion-adequacy coverage the AST cannot deliver.

# Inputs

Consumes from `integration_smoke_classifiers`: `is_io_bound(module_rel, module_src, *, signals=BOUNDARY_SIGNALS) -> IoBoundResult(io_bound, signals, reason)` and `has_executing_integration_oracle(module_rel, test_srcs, *, entrypoints=ENTRYPOINT_NAMES) -> SmokeOracleResult(present, oracle_files, reason, fix_hint)` from `harness/integration_smoke.py`, plus the constants `BOUNDARY_SIGNALS`, `ENTRYPOINT_NAMES`, `BOUNDARY_MOCK_ALLOWLIST`. References the regression shapes in `tools/drive_backup/hook_runner.py`, `tools/drive_backup/archiver.py`, `tests/drive_backup/test_hook_runner_production_deps.py`, `tests/drive_backup/test_archiver.py` (read-only).

# Deliverables

`tests/harness/test_integration_smoke_adversarial.py` — the committed adversarial fixture set: Evasion 1 (import-OK/call-raises ⇒ REJECT), Evasion 2 (fake/monkeypatched-entrypoint oracle ⇒ REJECT), Evasion 3 (boundary-only mock ⇒ PASS), false-positive guard (pure-logic ⇒ PASS, no oracle), the full I/O-signal matrix, the drive_backup regression (fixed ⇒ PASS / pre-fix ⇒ REJECT), and idempotency/purity checks.

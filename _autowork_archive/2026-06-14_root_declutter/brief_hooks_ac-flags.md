---
interfaces: "exposes `ac_enabled(key: str, state_dir=None) -> bool` (fail-closed False on any missing key / config error; never raises)"
---

# Title

Autocompiler fail-closed flag reader (autocompiler/flags.py)

# Scope

Build the NEW whole-file module `autocompiler/flags.py` exposing the pure, stdlib-only flag reader `ac_enabled(key, state_dir=None) -> bool`. It reads the (not-yet-existent) `autocompiler:` config subtree via plain filesystem reads under an injected/optional `state_dir`, returning a boolean for a dotted flag key. It is the fail-closed gate idiom cloned from `harness/orchestrator.py::_wire_up_gate_enabled` (`:2022`) and `_reap_spent_briefs_safe` (`:45`), so EVERY error path (missing config file, missing key, malformed yaml, any raised exception) collapses to `False`. meta_task_type=`config_schema`. verification_command: `python -m pytest tests/autocompiler/test_flags.py tests/autocompiler/test_flags_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=config_schema; >=2 edge_cases mirrored in regression/property tests (e.g. (a) config subtree absent => False, (b) key present-but-non-bool / malformed yaml => False, (c) any internal exception swallowed => False). Module dotted path is pre-registered in `config/autocompiler.yaml` so the ON `wire_up_gate` returns wired=True(config).

# Non-Goals

Does NOT flip any runtime flag or create the `autocompiler:` config subtree (so `ac_enabled` is fail-closed False everywhere this run). Does NOT touch any `harness/**`, `config/**`, `scripts/**`, `services/**`, or `_NEVER_AUTO_APPROVE` file. Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT author new tests (oracles pre-committed at e567269). Pure/stdlib-only.

# Inputs

Fixed seams (reuse, do not reimplement): the fail-closed flag idiom `harness/orchestrator.py::_wire_up_gate_enabled` (`:2022`) + the `_reap_spent_briefs_safe` try/except bridge (`:45`); `harness/config.yaml` + `harness/config_loader.py` as the flag-tree home pattern. Pre-committed RED oracles `tests/autocompiler/test_flags.py` + `tests/autocompiler/test_flags_wired.py` (e567269) ARE the authoritative contract; the wiring oracle asserts `check_wired(repo_root, 'autocompiler/flags.py').wired`.

# Deliverables

NEW whole-file `autocompiler/flags.py`. Exposes `ac_enabled(key: str, state_dir=None) -> bool` — fail-closed `False` on any missing key, missing/malformed config, or internal error; never raises. Turns `tests/autocompiler/test_flags.py` and `tests/autocompiler/test_flags_wired.py` GREEN.

---
interfaces: "in-place EDIT of harness/rebuild/task.py — inside build_unit_task, shlex.quote every value spliced into the oracle verification_command (module_rel, oracle_original_path, unit.name, and the parent_root-derived oracle.py + config paths), adding a function-local `import shlex`. NO signature change; NO other line of build_unit_task changes; the test_cmd branch and spec_dict are byte-identical."
---

# Title

shlex.quote the shell-interpolated values in build_unit_task's oracle verification_command (harness/rebuild/task.py EDIT — harness_self_fix, CWE-78)

# Scope

EDIT `harness/rebuild/task.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-rebuild-shell-quote.json` authorizes the commit).

THE BUG (CWE-78 OS command injection; found AND live-confirmed by the NobleGreed detonation pipeline 2026-06-11): `build_unit_task` constructs `oracle_cmd` by f-string-interpolating `module_rel`, `oracle_original_path`, `unit.name`, and the `parent_root`-derived oracle.py + `config_abs` paths DIRECTLY into a shell command string. That string becomes the task's `verification_command`, which the harness later runs under `shell=True` (`harness/rebuild/loop.py:1330` & `:1347`, `harness/orchestrator.py:3142`, `executable='/bin/bash'`). NONE of the interpolated values are `shlex.quote`'d. `module_rel` is a target-repo-relative module path; a target whose module path is `m.py; touch pwned #` injects an arbitrary shell command that executes whenever the harness runs the verification_command. A live PoC against the REAL `build_unit_task` (importing it, calling it with the malicious `module_rel`, then running the emitted command exactly as `loop.py` does) printed `VULNERABLE` and dropped `pwned_by_module_rel.txt` inside a bubblewrap detonation; the spine session reached `done` with `verdict=confirmed`.

THE CURRENT vulnerable block (harness/rebuild/task.py, inside `build_unit_task`, the `else:` arm of the `if oracle_skip:` branch, ~lines 613-618 at HEAD) is, byte-for-byte:

```python
        oracle_cmd = (
            f'python {parent_root}/harness/rebuild/oracle.py '
            f'--target {module_rel} --original {oracle_original_path} '
            f'--unit {unit.name} --config {config_abs}'
            + (' --str-ascii' if fuzz_str_ascii else '')
        )
```

THE FIX (verified-diff: built in a /tmp clean worktree 2026-06-11 and proven the RED oracle goes 4/4 GREEN with 35/35 rebuild regression tests still green): replace ONLY that block with the `shlex.quote`'d form, adding a function-LOCAL `import shlex` immediately above it (a local import keeps the change to the SINGLE symbol `build_unit_task` — a module-top import would require a second, separate patch and is NOT wanted):

```python
        import shlex
        oracle_cmd = (
            f'python {shlex.quote(f"{parent_root}/harness/rebuild/oracle.py")} '
            f'--target {shlex.quote(module_rel)} --original {shlex.quote(oracle_original_path)} '
            f'--unit {shlex.quote(unit.name)} --config {shlex.quote(config_abs)}'
            + (' --str-ascii' if fuzz_str_ascii else '')
        )
```

Quoting the whole `f"{parent_root}/harness/rebuild/oracle.py"` (not `parent_root` alone) keeps the path one shell token; each `--target`/`--original`/`--unit`/`--config` argument value is independently quoted so no metacharacter in any of them can break out of its argument. The `--str-ascii` suffix is unchanged (a literal flag, no interpolation). For a benign module path the emitted command is byte-equivalent except for the (harmless) shell quoting, so all existing rebuild oracle/test behavior is preserved.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/rebuild/task.py` is a LARGE file; this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry, kind `'symbol'`, name `'build_unit_task'`, whose `code` is the FULL `def build_unit_task(...) -> dict:` reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/rebuild/task.py`, changing ONLY the `oracle_cmd` block shown above (add the local `import shlex` line + wrap the four interpolations in `shlex.quote`). `build_unit_task` spans lines 445-670 at HEAD (~226 lines). KNOWN GOTCHA — LARGE-SYMBOL TRUNCATION: agents have deterministically truncated large symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted `build_unit_task` must START with `def build_unit_task(` and END with `    return spec_dict`, and must still contain the `if oracle_skip:` branch, the `test_cmd` construction, and the `spec_dict = {` literal — all byte-identical except the one `oracle_cmd` block. If your draft dropped any of those, you truncated — re-read the staged target and re-emit. Do NOT add a module-top import, do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT add any new top-level symbol (no R-anchor — the change is wholly inside `build_unit_task` via a function-local import), do NOT touch `_build_spec`, `_k_expr`, `_module_test_files`, or any other symbol.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-rebuild-shell-quote`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/rebuild/task.py"]` ONLY. partial_edit semantics (single `__JANUSMASK_PATCHES__` list with ONE `'symbol'` entry for `build_unit_task`, per the LOUD DISPATCH DIRECTIVE). verification_command: `python -m pytest tests/test_rebuild_task_shell_quote_wired.py tests/adversarial/test_rebuild_engine.py tests/adversarial/test_rebuild_no_pathless_pytest.py tests/adversarial/test_rebuild_kexpr_method_scoping.py tests/adversarial/test_rebuild_eg3_module_scope.py tests/adversarial/test_rebuild_partial_edit_largefile.py -q`. The pre-committed RED oracle `tests/test_rebuild_task_shell_quote_wired.py` (committed at f95aa66 on JM master) is the authoritative contract — make it 4/4 green; do NOT author new tests. The five `tests/adversarial/test_rebuild_*.py` paths are the pre-existing drift guards (35/35 green at HEAD) and must stay green.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. module_rel carrying a shell-injection payload (`m.py; touch X #`) is emitted as a SINGLE `--target` argument token (shlex.split yields the literal payload), with no surviving `;`/`touch` shell token.
  2. a benign module path (`pkg/mod.py`) still yields a well-formed command: `--target` followed by exactly `pkg/mod.py`, with `--original`/`--unit`/`--config` present (no behavioral change for legitimate inputs).
A third (oracle_original_path / unit.name injection neutralized the same way) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT change `build_unit_task`'s signature, its docstring, the `task_id` computation, the `_build_spec` call, the `if oracle_skip:` control flow, the `test_cmd` construction, the `spec_dict` literal, or any other line of the function — ONLY the `oracle_cmd` block (local `import shlex` + four `shlex.quote` wraps).
- Does NOT add a module-top `import shlex` (the local import keeps the change to one symbol); does NOT touch any other symbol in `harness/rebuild/task.py`.
- Does NOT harden the separate `test_cmd` interpolations (test-file paths / `_k_expr`) — `_k_expr` is already single-quoted; the test-file-path vector is a related follow-up tracked separately, out of scope here.
- Does NOT modify `harness/rebuild/loop.py`, `harness/orchestrator.py`, `harness/rebuild/oracle.py`, or any caller — only the command-STRING construction is fixed.
- Does NOT touch any file other than `harness/rebuild/task.py`.
- Out of scope: integration testing of the end-to-end worker/daemon rebuild flow beyond the six listed pytest files; this leaf is a behavior-only unit fix verified by the pre-committed oracle plus the existing rebuild regression batteries.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_rebuild_task_shell_quote_wired.py` (JM master commit f95aa66). Confirmed RED 2026-06-11: 3 failed (module_rel / oracle_original_path / unit.name injection leak as separate shell tokens) / 1 passed (benign well-formed). After the fix it is 4/4 GREEN.
- Drift guards (pre-existing, all green at HEAD): `tests/adversarial/test_rebuild_engine.py`, `tests/adversarial/test_rebuild_no_pathless_pytest.py`, `tests/adversarial/test_rebuild_kexpr_method_scoping.py`, `tests/adversarial/test_rebuild_eg3_module_scope.py`, `tests/adversarial/test_rebuild_partial_edit_largefile.py` — 35/35 at HEAD; must stay green (catch any faithful-reproduction drift in the 226-line `build_unit_task`).
- VERIFIED DIFF (2026-06-11, two /tmp clean-worktree builds): with ONLY the `oracle_cmd` block changed (function-local `import shlex` + four `shlex.quote` wraps), the RED oracle is 4/4 GREEN and the rebuild regression set stays 35/35; the INV9 capability gate passes (the function builds a STRING; it contains no `subprocess(..., shell=True)`/eval/exec/os.system Call node, so the staged symbol is capability-clean).
- The verbatim CURRENT `oracle_cmd` block and its exact corrected form are embedded in `# Scope`; the staged read-only target is at `{WORK_DIR}/inbox/targets/harness/rebuild/task.py` (`build_unit_task` spans lines 445-670 at HEAD).

# Deliverables

`harness/rebuild/task.py` with `build_unit_task`'s `oracle_cmd` block changed to add a function-local `import shlex` and wrap each shell-interpolated value (`parent_root`-derived oracle.py path, `module_rel`, `oracle_original_path`, `unit.name`, `config_abs`) in `shlex.quote`, so a malicious target module path can no longer inject a command into the `shell=True` verification_command. Turns `tests/test_rebuild_task_shell_quote_wired.py` 4/4 GREEN while the five `tests/adversarial/test_rebuild_*.py` drift guards stay green (35/35). Every other line of `build_unit_task` and of `harness/rebuild/task.py` is byte-identical; benign rebuild verification commands are unchanged in behavior.

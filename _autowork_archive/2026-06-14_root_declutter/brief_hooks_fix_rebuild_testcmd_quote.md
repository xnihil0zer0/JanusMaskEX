---
interfaces: "in-place EDIT of harness/rebuild/task.py — inside build_unit_task, shlex.quote every TARGET-REPO test-file path spliced into the test_cmd / sel_args of the verification_command (the _gate_tfs joined into whole_file_args), adding a function-local `import shlex` immediately above the join. NO signature change; NO other line of build_unit_task changes; the oracle_cmd block (already quoted in f3a7320), the _k_expr selection (already single-quoted), the if oracle_skip branch, and the spec_dict literal are byte-identical."
---

# Title

shlex.quote the test-file paths spliced into build_unit_task's test_cmd verification_command (harness/rebuild/task.py EDIT — harness_self_fix, CWE-78)

# Scope

EDIT `harness/rebuild/task.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-rebuild-testcmd-quote.json` authorizes the commit).

THE BUG (CWE-78 OS command injection; verified by a live PoC against the real `build_unit_task` 2026-06-11): the companion `oracle_cmd` vector was fixed in f3a7320, but `build_unit_task` ALSO builds the scoped `test_cmd` half of the `verification_command` from TARGET-REPO test-file paths WITHOUT `shlex.quote`. It computes `whole_file_args = ' '.join(_gate_tfs)` where `_gate_tfs` is `_module_test_files(descriptor, module_rel)` or, as a fallback, `descriptor.test_files` — target-repo-relative test-file paths. That raw string is interpolated UNQUOTED into `test_cmd` (the `elif whole_file_args:` arm: `f'{test_py} -m pytest {whole_file_args} -q'`) and into `sel_args` when the module's generated oracle / importing tests match (`sel_args = f'{whole_file_args} -k {_kexpr}'`). `test_cmd` becomes part of the task's `verification_command`, which the harness later runs under `shell=True` (`harness/rebuild/loop.py:1330` & `:1347`, `harness/orchestrator.py:3142`, `executable='/bin/bash'`). A target whose test-file path is `t.py; touch pwned #` injects an arbitrary command: the bare `;` terminates the pytest invocation and `touch pwned` runs as a separate command whenever the harness runs the verification_command. A live PoC importing the REAL `build_unit_task` and calling it with a malicious `descriptor.test_files` entry emitted a `verification_command` whose `shlex.split` yielded standalone `touch` / `pwned` tokens and a bare `;` outside any quote. (`_k_expr` from `unit.name` is ALREADY single-quoted at task.py:359-403 and is NOT the vector; the unquoted value is the test-file PATH.)

THE CURRENT vulnerable line (harness/rebuild/task.py, inside `build_unit_task`, ~line 515 at HEAD) is, byte-for-byte:

```python
    _module_tfs = _module_test_files(descriptor, module_rel)
    _gate_tfs = _module_tfs if _module_tfs else descriptor.test_files
    whole_file_args = ' '.join(_gate_tfs)
```

which then flows UNQUOTED into the test_cmd / sel_args blocks (~lines 537-566 at HEAD), byte-for-byte:

```python
        if _module_tfs:
            sel_args = f'{whole_file_args} -k {_kexpr}'
        else:
            sel_args = descriptor.unit_test_selector.replace('{unit}', _kexpr)
        ...
        if has_oracle:
            test_cmd = (
                f'{test_py} -m pytest {sel_args} -q; __rc=$?; '
                f'if [ "$__rc" = "5" ]; then __rc=0; fi; exit $__rc'
            )
        elif whole_file_args:
            test_cmd = (
                f'{test_py} -m pytest {sel_args} -q; __rc=$?; '
                f'if [ "$__rc" = "5" ]; then {test_py} -m pytest {whole_file_args} -q; __rc=$?; fi; '
                f'exit $__rc'
            )
        else:
            test_cmd = f'{test_py} -m pytest {sel_args} -q'
    elif whole_file_args:
        test_cmd = f'{test_py} -m pytest {whole_file_args} -q'
```

THE FIX (verified-diff: built in a /tmp clean worktree 2026-06-11 and proven the RED oracle goes 4/4 GREEN with 35/35 rebuild regression tests still green): replace ONLY the `whole_file_args = ' '.join(_gate_tfs)` line with a `shlex.quote`'d join, adding a function-LOCAL `import shlex` immediately above it (a local import keeps the change to the SINGLE symbol `build_unit_task` — a module-top import is already present at the existing oracle_cmd block from f3a7320 but is INSIDE the `else:` arm, which executes AFTER this line, so this earlier site needs its own local import; do NOT add a second module-top import):

```python
    _module_tfs = _module_test_files(descriptor, module_rel)
    _gate_tfs = _module_tfs if _module_tfs else descriptor.test_files
    # CWE-78: _gate_tfs are TARGET-REPO-relative test-file paths spliced into
    # test_cmd (and sel_args), which becomes the verification_command run under
    # shell=True. shlex.quote each path so a malicious path (``t.py; touch X #``)
    # stays ONE pytest argument token and cannot inject a shell command. (_k_expr
    # is already single-quoted; the oracle_cmd paths were quoted in f3a7320.)
    import shlex
    whole_file_args = ' '.join(shlex.quote(_tf) for _tf in _gate_tfs)
```

Quoting each `_tf` independently makes every test-file path one shell token, so no metacharacter in any path can break out of the pytest path argument; the `' '.join` still produces a space-separated multi-file pytest path list, byte-equivalent for benign paths except for harmless shell quoting. The `sel_args`, `test_cmd`, and oracle_cmd blocks are UNCHANGED (they consume the now-quoted `whole_file_args`); `_k_expr` is already single-quoted and untouched. NOTE on `import shlex`: confirmed present at module top? — it is NOT; the existing `import shlex` is FUNCTION-LOCAL inside the oracle_cmd `else:` arm (task.py:612, added f3a7320), which runs LATER than this line, so this fix's local `import shlex` is required and is NOT a duplicate of a module-top import. Do NOT add a module-top import.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/rebuild/task.py` is a LARGE file; this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry, kind `'symbol'`, name `'build_unit_task'`, whose `code` is the FULL `def build_unit_task(...) -> dict:` reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/rebuild/task.py`, changing ONLY the `whole_file_args` line shown above (add the function-local `import shlex` line + wrap the join in `shlex.quote`). `build_unit_task` spans lines 445-671 at HEAD (~226 lines). KNOWN GOTCHA — LARGE-SYMBOL TRUNCATION: agents have deterministically truncated large symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted `build_unit_task` must START with `def build_unit_task(` and END with `    return spec_dict`, and must still contain the `_gate_tfs = _module_tfs if _module_tfs else descriptor.test_files` line, the `if descriptor.unit_test_selector:` selector branch, every `test_cmd` arm, the existing oracle_cmd `import shlex` + `shlex.quote` block (from f3a7320, byte-identical), the `if oracle_skip:` branch, and the `spec_dict = {` literal — all byte-identical except the one `whole_file_args` line. If your draft dropped any of those, you truncated — re-read the staged target and re-emit. Do NOT add a module-top import, do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT add any new top-level symbol (no R-anchor — the change is wholly inside `build_unit_task` via a function-local import), do NOT touch `_build_spec`, `_k_expr`, `_module_test_files`, the oracle_cmd block, or any other symbol.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-rebuild-testcmd-quote`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/rebuild/task.py"]` ONLY. partial_edit semantics (single `__JANUSMASK_PATCHES__` list with ONE `'symbol'` entry for `build_unit_task`, per the LOUD DISPATCH DIRECTIVE). verification_command: `python -m pytest tests/test_rebuild_task_testcmd_quote_wired.py tests/adversarial/test_rebuild_engine.py tests/adversarial/test_rebuild_no_pathless_pytest.py tests/adversarial/test_rebuild_kexpr_method_scoping.py tests/adversarial/test_rebuild_eg3_module_scope.py tests/adversarial/test_rebuild_partial_edit_largefile.py -q`. The pre-committed RED oracle `tests/test_rebuild_task_testcmd_quote_wired.py` is the authoritative contract — make it 4/4 green; do NOT author new tests. The five `tests/adversarial/test_rebuild_*.py` paths are the pre-existing drift guards (35/35 green at HEAD) and must stay green.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. a test-file path carrying a shell-injection payload (`t.py; touch X #`) in `descriptor.test_files` (no selector → the `elif whole_file_args:` branch) is emitted as a SINGLE pytest path-argument token (shlex.split yields the literal payload), with no surviving standalone `;`/`touch` shell token.
  2. a benign test-file path (`tests/test_mod.py`) still yields a well-formed pytest command: `-m pytest tests/test_mod.py ... -q` (no behavioral change for legitimate inputs).
A third (the same payload riding `sel_args = f'{whole_file_args} -k {_kexpr}'` via a `_module_test_files` basename match, neutralized the same way) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT change `build_unit_task`'s signature, its docstring, the `task_id` computation, the `_build_spec` call, the `_module_test_files`/`_gate_tfs` selection, the `if descriptor.unit_test_selector:` branch, the `test_cmd` arms, the oracle_cmd block (already quoted in f3a7320), the `if oracle_skip:` control flow, the `spec_dict` literal, or any other line of the function — ONLY the `whole_file_args = ' '.join(_gate_tfs)` line (function-local `import shlex` + per-path `shlex.quote`).
- Does NOT re-quote `_k_expr` (the `-k` expression from `unit.name`) — it is ALREADY single-quoted at task.py:359-403; double-quoting it would corrupt the selector.
- Does NOT add a module-top `import shlex` (the existing one is function-local inside the oracle_cmd arm; this fix adds its own function-local import earlier); does NOT touch any other symbol in `harness/rebuild/task.py`.
- Does NOT modify `harness/rebuild/loop.py`, `harness/orchestrator.py`, `harness/rebuild/oracle.py`, or any caller — only the command-STRING construction is fixed.
- Does NOT touch any file other than `harness/rebuild/task.py`.
- Out of scope: integration testing of the end-to-end worker/daemon rebuild flow beyond the six listed pytest files; this leaf is a behavior-only unit fix verified by the pre-committed oracle plus the existing rebuild regression batteries.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_rebuild_task_testcmd_quote_wired.py`. Confirmed RED on HEAD f3a7320 (2026-06-11): 3 failed (`test_whole_file_args_path_injection_is_neutralized`, `test_sel_args_module_scoped_path_injection_is_neutralized`, `test_multiple_test_files_each_quoted` — the test-file path leaks as separate shell tokens) / 1 passed (`test_benign_command_still_well_formed`). After the fix it is 4/4 GREEN.
- Drift guards (pre-existing, all green at HEAD): `tests/adversarial/test_rebuild_engine.py`, `tests/adversarial/test_rebuild_no_pathless_pytest.py`, `tests/adversarial/test_rebuild_kexpr_method_scoping.py`, `tests/adversarial/test_rebuild_eg3_module_scope.py`, `tests/adversarial/test_rebuild_partial_edit_largefile.py` — 35/35 at HEAD; must stay green (they exercise the test_cmd construction and catch any faithful-reproduction drift in the 226-line `build_unit_task`).
- VERIFIED DIFF (2026-06-11, /tmp clean-worktree build at HEAD f3a7320): with ONLY the `whole_file_args` line changed (function-local `import shlex` + per-path `shlex.quote`), the RED oracle is 4/4 GREEN and the rebuild regression set stays 35/35; the INV9 capability gate passes (the function builds a STRING; it contains no `subprocess(..., shell=True)`/eval/exec/os.system Call node, so the staged symbol is capability-clean).
- The verbatim CURRENT `whole_file_args` line + the downstream test_cmd/sel_args blocks and the exact corrected form are embedded in `# Scope`; the staged read-only target is at `{WORK_DIR}/inbox/targets/harness/rebuild/task.py` (`build_unit_task` spans lines 445-671 at HEAD).

# Deliverables

`harness/rebuild/task.py` with `build_unit_task`'s `whole_file_args = ' '.join(_gate_tfs)` line changed to add a function-local `import shlex` and wrap each test-file path in `shlex.quote` (`' '.join(shlex.quote(_tf) for _tf in _gate_tfs)`), so a malicious target test-file path can no longer inject a command into the `shell=True` verification_command's test_cmd / sel_args. Turns `tests/test_rebuild_task_testcmd_quote_wired.py` 4/4 GREEN while the five `tests/adversarial/test_rebuild_*.py` drift guards stay green (35/35). Every other line of `build_unit_task` (including the f3a7320 oracle_cmd block and the already-single-quoted `_k_expr`) and of `harness/rebuild/task.py` is byte-identical; benign rebuild verification commands are unchanged in behavior.

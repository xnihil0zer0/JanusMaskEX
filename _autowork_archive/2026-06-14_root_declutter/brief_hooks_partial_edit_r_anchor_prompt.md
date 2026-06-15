---
interfaces: "in-place EDIT of harness/orchestrator.py::prepare_task_prompt — augment the PARTIAL-EDIT DISPATCH prompt f-string with an 'ADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR)' section so additive EDIT leaves know to anchor new symbols on an existing one instead of naming a not-yet-existing symbol; behavior-only, signature unchanged, additive to the prompt string only"
---

# Title

Document the R-ANCHOR additive pattern in the PARTIAL-EDIT prompt (harness/orchestrator.py::prepare_task_prompt EDIT — harness_self_fix)

# Scope

EDIT `harness/orchestrator.py` (SENSITIVE path — meta_task_type MUST be `harness_self_fix`; an operator decision file authorizes the commit). Inside `prepare_task_prompt(task)` the PARTIAL-EDIT DISPATCH prompt f-string (the `prompt += '\nPARTIAL-EDIT DISPATCH ...'` assignment, ~orchestrator.py:1531) documents ONLY how to REPLACE an existing `kind:'symbol'` block. It says NOTHING about how to ADD a brand-new top-level symbol. So when an additive EDIT leaf runs (e.g. "add 3 new functions to ngv2/debate_router.py"), the agent emits patch entries naming NEW (not-yet-existing) symbols like `{{'kind':'symbol','name':'calculate_shannon_entropy','code':...}}`. `git_integration._apply_symbol_patch` can only slice-replace an EXISTING symbol, so it raises `KeyError` → "patch apply failed" / verification fails.

The harness ALREADY supports adding new top-level symbols via the R-ANCHOR mechanism (PHASE_R_ANCHORED_PATCH in `_apply_symbol_patch`, harness/git_integration.py:1095-1108, extras logic 1176-1209). Verified rules:
- A `kind:'symbol'` patch entry's `name` MUST be an EXISTING top-level symbol (the "anchor").
- `code` must `ast.parse` to EXACTLY ONE primary def/class (or single-Name assign) whose name equals the anchor's leaf name — i.e. the anchor reproduced — PLUS zero or more "extra" top-level nodes.
- Extras may be FunctionDef/AsyncFunctionDef/ClassDef/Import/ImportFrom/Assign/AnnAssign ONLY. Any extra whose name collides with an existing top-level name (or the anchor leaf) → ValueError. Extras are only allowed for a 1-part (top-level) anchor name, never a dotted `Outer.inner`.
- The harness inserts the extras IMMEDIATELY BEFORE the anchor block and preserves every other byte of the file. There is NO drift guard on the patch path, but the agent should copy the anchor verbatim from the staged read-only target to be safe.

THE FIX (additive — augment the PARTIAL-EDIT prompt f-string only): weave a new "ADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR)" section into the existing PARTIAL-EDIT DISPATCH f-string. The string is an f-string that uses `{tsq}` for raw triple-quotes and `{{`/`}}` for literal braces — MATCH that escaping exactly. Preserve every other byte of `prepare_task_prompt` and of the rest of the prompt text. This is an ADDITIVE edit to the prompt string only — do NOT change the existing REPLACE guidance, the region guidance, the manifest block, or any other line.

VERBATIM CURRENT END of the PARTIAL-EDIT f-string (the blind worker must locate exactly this tail inside the `prompt += '\nPARTIAL-EDIT DISPATCH ...` assignment; it is the last bullet of the existing "Rules:" list):

```
- The submission file MUST contain ONLY this ``__JANUSMASK_PATCHES__``\n  assignment at top level (no other statements, imports, or decorators).\n- Replace ONLY the named symbols/regions you must change. Never emit a\n  whole-file manifest for a partial edit.\n
```

INSERT the following NEW section text into the f-string IMMEDIATELY AFTER that final `\n` (i.e. append it to the end of the PARTIAL-EDIT f-string, before the closing `"`). Reproduce this text byte-for-byte using the SAME f-string escaping (`{tsq}` for raw triple-quotes, `{{`/`}}` for literal braces). The new fragment to APPEND to the PARTIAL-EDIT f-string:

```
\nADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR):\n- A 'symbol' patch entry can ONLY replace a symbol that ALREADY EXISTS in\n  the target file. If you name a symbol that does not yet exist, the patch\n  apply FAILS (KeyError) -- you cannot create a new symbol by simply naming\n  it in a 'symbol' entry.\n- To ADD brand-new top-level function(s)/class(es)/constant(s), use the\n  R-ANCHOR pattern: pick an EXISTING top-level symbol in the SAME file as\n  the ANCHOR; set the entry's ``name`` to that anchor; in ``code``, FIRST\n  reproduce the anchor's CURRENT source VERBATIM (copy it exactly from\n  {{WORK_DIR}}/inbox/targets/<rel>), THEN include your NEW top-level\n  symbol(s) in the SAME ``code`` block. The harness inserts the new symbols\n  immediately before the anchor and keeps every other byte of the file.\n- Put ALL new top-level symbols for one file as extras on a SINGLE anchor\n  entry (do not spread them across multiple entries).\n- New symbol names must NOT collide with any existing top-level name in the\n  file; the anchor ``name`` must be a top-level symbol (a 1-part name, never\n  a dotted ``Outer.inner``). Allowed new-symbol kinds: def / async def /\n  class / Import / ImportFrom / module-level assignment.\n- Concrete example -- add two NEW functions ``foo`` and ``bar`` to a file\n  that already defines top-level ``baz``, anchoring on ``baz``:\n\n    __JANUSMASK_PATCHES__ = [\n        {{'file': '<rel/path>', 'kind': 'symbol', 'name': 'baz', 'code': r{tsq}def baz() -> int:\n    return 0\n\ndef foo() -> int:\n    return 1\n\ndef bar() -> int:\n    return 2\n{tsq}}},\n    ]\n\n  Here ``baz`` is reproduced VERBATIM (the anchor) and ``foo``/``bar`` are\n  the new symbols carried as extras in the same ``code`` block.\n
```

This is purely ADDITIVE prompt guidance — it does not change any harness behavior, only what the worker prompt documents. Do NOT touch `_apply_symbol_patch` or any other symbol.

meta_task_type=`harness_self_fix`. verification_command: `pytest tests/test_partial_edit_prompt_r_anchor_wired.py`.

LOUD DISPATCH DIRECTIVE: `harness/orchestrator.py` is a LARGE file, so this MUST be a partial edit. This edit MODIFIES the EXISTING function `prepare_task_prompt` (it does NOT add a new top-level symbol), so it is a STRAIGHT symbol replacement, NOT an R-anchor-with-extras. Emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry of kind `'symbol'`, name `'prepare_task_prompt'`, whose `code` is the FULL corrected `def prepare_task_prompt(...)` (the ENTIRE function with ONLY the PARTIAL-EDIT f-string augmented as above and every other line — the long docstring, all other `prompt += ...` blocks, the manifest block, the test_authoring block, the spec_summary tail, the `return prompt`) preserved BYTE-FOR-BYTE. Read the function's CURRENT on-disk content from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/orchestrator.py`. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, and do NOT touch any other symbol in the file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `partial-edit-r-anchor-prompt`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. files_touched: `["harness/orchestrator.py"]` ONLY (no other file). partial_edit semantics (single `__JANUSMASK_PATCHES__` symbol entry for `prepare_task_prompt`). verification_command: `pytest tests/test_partial_edit_prompt_r_anchor_wired.py`. The leaf's `non_goals` MUST carry the literal word `integration` (out of scope is integration testing). The pre-committed RED oracle `tests/test_partial_edit_prompt_r_anchor_wired.py` (committed at 5072082 on JM master) is the authoritative contract — make it 4/4 green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. r-anchor-mechanism-documented: the PARTIAL-EDIT prompt returned by `prepare_task_prompt` for a task that gets the partial-edit block CONTAINS the marker `R-ANCHOR` and the phrase `already exist`.
  2. r-anchor-example-present: the same prompt CONTAINS the worked example anchor name `baz` and the new symbol names `foo` and `bar`.
`minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT change `harness/git_integration.py` or the `_apply_symbol_patch` R-anchor behavior — guidance only.
- Does NOT touch any file other than `harness/orchestrator.py`.
- Does NOT change the existing REPLACE / region / manifest / test_authoring guidance; the new section is purely additive.
- Does NOT change the signature of `prepare_task_prompt` or any other symbol in the file.
- Does NOT add any module-level import.
- Out of scope: integration testing of the end-to-end additive-edit commit flow; this leaf is a behavior-only unit fix verified by the pre-committed oracle.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_partial_edit_prompt_r_anchor_wired.py` (JM master commit 5072082). Three assertions are RED today (R-ANCHOR marker, `already exist` phrase, `baz`/`foo`/`bar` example); one sanity test (the PARTIAL-EDIT block is present) is green and locks the code path.
- The VERBATIM current END of the PARTIAL-EDIT f-string and the EXACT new section text to append are embedded in `# Scope` above. Match the f-string escaping (`{tsq}` for raw triple-quotes, `{{`/`}}` for literal braces) exactly.
- The R-anchor mechanism this guidance describes: `_apply_symbol_patch` PHASE_R_ANCHORED_PATCH (harness/git_integration.py:1095-1108, extras logic 1176-1209).

# Deliverables

`harness/orchestrator.py` with `prepare_task_prompt`'s PARTIAL-EDIT DISPATCH prompt string augmented by an "ADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR)" section (anchor-on-existing-symbol guidance + the foo/bar-on-baz worked example), every other byte of the function and file preserved. Turns `tests/test_partial_edit_prompt_r_anchor_wired.py` 4/4 GREEN. Additive EDIT leaves now learn to anchor new top-level symbols on an existing one instead of naming a not-yet-existing symbol (which fails with KeyError on the patch-apply path).

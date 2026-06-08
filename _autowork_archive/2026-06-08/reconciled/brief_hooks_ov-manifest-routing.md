---
interfaces: "harness/orchestrator.py: add module-level _requires_verbatim_manifest(files_touched) predicate and route non-.py / multi-file BYPASS_FUZZER_TYPES edit leaves in prepare_task_prompt to the __JANUSMASK_MANIFEST__ verbatim whole-file dispatch instead of the Python-only __JANUSMASK_PATCHES__ symbol-patch dispatch."
meta_task_type: harness_self_fix
---

# Title

FIX harness/orchestrator.py — route non-Python / multi-file bypass-fuzzer edit leaves to the verbatim __JANUSMASK_MANIFEST__ dispatch

# Scope

ONE leaf (do NOT split). A surgical routing fix in `harness/orchestrator.py` against its
pre-committed RED oracle `tests/adversarial/test_nonpy_manifest_routing.py` (AUTHORITATIVE).
The dispatch-prompt builder `prepare_task_prompt` currently checks `mtt in BYPASS_FUZZER_TYPES`
FIRST and forces EVERY safe edit type (`harness_plumbing`, `harness_self_fix`, ...) into the
PARTIAL-EDIT (`__JANUSMASK_PATCHES__`) branch — whose applier `_apply_symbol_patch` is pure
`ast.parse` and CANNOT apply a non-Python (`.js`/`.css`/`.yaml`) or multi-file edit. Route those
leaves to the existing `__JANUSMASK_MANIFEST__` whole-file (verbatim) dispatch instead. The
validation, save, and commit sides ALREADY prefer a manifest when one is emitted, so ONLY the
dispatch prompt needs to change.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: harness_self_fix
- files_touched: ["harness/orchestrator.py"]
- verification_command: "python -m pytest tests/adversarial/test_nonpy_manifest_routing.py -q"
- spec_author: null
- IMPL-only: author/edit NO test. The oracle is pre-committed and authoritative.
- This is a SINGLE .py file edit → it uses the working __JANUSMASK_PATCHES__ symbol-patch path
  (kind:'symbol'). Emit ONE patch entry for `prepare_task_prompt`, R-anchoring the new helper.

# Inputs

`harness/orchestrator.py` is staged read-only at `{WORK_DIR}/inbox/targets/harness/orchestrator.py`.
Read the CURRENT `prepare_task_prompt` from there and reproduce it BYTE-FOR-BYTE except for the
routing change below. Its two large `prompt += '...'` dispatch strings (the PARTIAL-EDIT block and the
MULTI-FILE block) MUST be preserved verbatim — copy them exactly from the staged file; do NOT
paraphrase, truncate, or re-escape them.

# Non-Goals

No change to `_validate_submission`, `_save_final_output`, `_parse_manifest`, `git_integration`, or any
prompt-string CONTENT. Do NOT touch the patches path for single `.py` edits. Do NOT add a new patch
`kind`. ONE leaf editing exactly `harness/orchestrator.py`. Does not author its own oracle.

# Implementation notes

Exactly two edits, both inside / beside `prepare_task_prompt` (module-level, `harness/orchestrator.py`):

1. ADD a new module-level helper (it rides as an R-anchored EXTRA node in the SAME `kind:'symbol'`
   patch entry whose `name` is `prepare_task_prompt` — a 1-part top-level qualname permits extra
   top-level def nodes, inserted immediately before the primary). The helper:

   ```python
   def _requires_verbatim_manifest(files_touched) -> bool:
       """True when a leaf's edits must use verbatim whole-file __JANUSMASK_MANIFEST__
       writes rather than the Python-only __JANUSMASK_PATCHES__ symbol/region path.

       Two cases require the language-agnostic verbatim manifest path:
       - multi-file bundles (len > 1): the manifest commits every file atomically;
       - any non-Python target (.js/.html/.css/.yaml/...): _apply_symbol_patch is
         pure ast.parse and cannot apply a non-Python file.

       A single .py target returns False so the working Python symbol-patch flow
       (webui_control / webui_server edits) is preserved unchanged.
       """
       if not isinstance(files_touched, list) or not files_touched:
           return False
       return len(files_touched) > 1 or any(not str(f).endswith('.py') for f in files_touched)
   ```

2. In `prepare_task_prompt`, just after `files_touched` and `mtt` are computed, add:
   `use_manifest = _requires_verbatim_manifest(files_touched)`
   then change the dispatch guard so the manifest case wins:
   - the PARTIAL-EDIT branch guard becomes:
     `if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and not use_manifest:`
   - the MULTI-FILE branch condition becomes:
     `elif use_manifest:`   (replacing the old `elif isinstance(files_touched, list) and len(files_touched) > 1:`)

   Everything else in the function — the base prompt, both giant `prompt += '...'` dispatch strings
   (copy them VERBATIM from the staged target), the `test_authoring` block, the `spec_summary` tail,
   and the `return prompt` — stays byte-identical.

Net effect: a `harness_plumbing` leaf touching `['app.js','styles.css']` and a `harness_self_fix` leaf
touching `['harness/config.yaml']` now emit a `__JANUSMASK_MANIFEST__` dispatch; a single `.py` leaf
(e.g. `harness/webui_control.py`) still emits the `__JANUSMASK_PATCHES__` dispatch.

# COMMITTED ORACLE CONTRACT (authoritative; you cannot read tests/ at synthesis time, so it is reproduced here — your code MUST make it pass)

`tests/adversarial/test_nonpy_manifest_routing.py` asserts, against `prepare_task_prompt`:
- `{meta_task_type:'harness_plumbing', files_touched:['tools/webui_static/app.js','tools/webui_static/styles.css']}`
  ⇒ prompt CONTAINS `__JANUSMASK_MANIFEST__` and `MULTI-FILE DISPATCH`, and does NOT contain `PARTIAL-EDIT DISPATCH`.
- `{meta_task_type:'harness_self_fix', files_touched:['harness/config.yaml']}`
  ⇒ prompt CONTAINS `__JANUSMASK_MANIFEST__`, and does NOT contain `PARTIAL-EDIT DISPATCH`.
- REGRESSION `{meta_task_type:'harness_plumbing', files_touched:['harness/webui_control.py']}`
  ⇒ prompt CONTAINS `PARTIAL-EDIT DISPATCH` and does NOT contain `__JANUSMASK_MANIFEST__`.
- Three more guardrails (already green): `_save_final_output` writes `.files.json` for a manifest;
  a manifest commit lands non-.py files verbatim in one commit; a symbol patch on `.js` fails loud.

# Deliverables

`harness/orchestrator.py` with `_requires_verbatim_manifest` added and `prepare_task_prompt` routing
fixed, GREEN under `python -m pytest tests/adversarial/test_nonpy_manifest_routing.py -q`, with the two
RED tests (multifile/single non-.py) now passing and zero regressions.

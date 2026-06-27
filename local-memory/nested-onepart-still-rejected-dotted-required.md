---
name: nested-onepart-still-rejected-dotted-required
description: "nested_symbol_patch_onepart did NOT deliver 1-part bare-name nested apply (only refined the reject message); patch a nested closure via the DOTTED Enclosing.nested form or the enclosing top-level symbol"
metadata:
  node_type: memory
  type: project
  originSessionId: c03fdb29-c511-46c5-a8df-c5c401fae776
---

🔴 BUILT-not-WORKS, adversarially proven 2026-06-21 (Agent 4, direct `_apply_symbol_patch` runs). The allowlist comment claiming "the 1-part bare-name nested apply landed; the nested closure build_evidence is now patchable" (from `nested_symbol_patch_onepart`, oracle `3746f2c` + impl `f4d8ba3`) is **FALSE**. `f4d8ba3` only refined the *rejection diagnostic* — `harness/git_integration.py::_apply_symbol_patch` `len(parts)==1` branch still `raise ValueError` for a bare name resolving to a nested-only def (now split into 1-scope vs ambiguous-multi-scope messages). No splice, no `located=<nested node>`. The 12/12 oracle is non-vacuous but **encodes rejection**: `test_apply_symbol_patch_single_nested_name_raises_valueerror` asserts `pytest.raises(ValueError)`; the misleadingly-named "applied" test patches a TOP-LEVEL `helper` (which also exists nested) and asserts the nested copy is left untouched.

**Live impact:** a 1-part `{"kind":"symbol","name":"build_evidence"}` patch is caught at `git_integration.py:~1602` → `committed=False` → surfaces as `auto_commit_failed`. **To patch a nested closure, a brief MUST use either the DOTTED `EnclosingFn.nested` qualname form (works via prior `58300e5`) OR patch the whole enclosing top-level symbol** (e.g. `name: 'build_default_seams'` to extend the nested `build_evidence` — which the corrected `brief_hooks_p11_build_evidence_perphase.md` lines 339-342 already mandate). The earlier memory note "dotted-only; 1-part still rejected" was ACCURATE; this was overseer MISATTRIBUTION — a diagnostic-message landing logged as an apply-capability landing. The real 1-part bare-name nested apply gap remains OPEN (not on the P1.1 critical path since the dotted/enclosing form works). See [[new-symbol-needs-r-anchor-or-autocommit-fails]] for the related top-level-new-symbol case.

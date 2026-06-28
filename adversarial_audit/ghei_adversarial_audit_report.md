# Adversarial Audit & Gap Analysis Report: GHEI Pipeline Implementation

**Target Codebase:** `JanusMaskEX`
**Master Plan:** `/mnt/ai-data/Research-JanusMask/final_ghei_implementation_plan.md`
**Acceptance Contract:** `/mnt/ai-data/Research-JanusMask/ghei-closure-deliverables-and-acceptance-contract.md`
**Audited Components:** Grounding (`ST_GROUNDING`), failure severity classification, traceback parsing, cryptographic validation of `grounding.json`, and backtrack FSM routing.

---

## 1. Executive Summary

An adversarial audit of the GHEI pipeline implementation in `JanusMaskEX` reveals a significant divergence between the master plan/contract requirements and the actual codebase. While some helper utilities (such as virtual framebuffer display management and boundary smoothing) are functionally rich and well-implemented, the core state machine, pre-flight grounding routing, and local model integration are either **completely missing**, **mocked/stubbed**, or **unwired (dead code)**. 

Furthermore, several critical security and logic bugs have been discovered in the failure classification and cryptographic signature verification routines, rendering the pipeline fragile and vulnerable to spoofing.

---

## 2. Detailed Findings & Gaps

### Finding 2.1: Pre-Flight Grounding (`ST_GROUNDING`) is Mocked and Unreachable
* **Plan Requirement:** Pre-flight Grounding (`ST_GROUNDING`) runs codebase research before synthesis to write signed `grounding_<task_id>.json` correctness axioms.
* **Actual Code:** 
  1. Grounding does **not** run as a pre-flight check. It is only triggered as an exception handler catch-all in the orchestrator's task processing loop.
  2. The orchestrator's exception-catching logic is completely decoupled from actual test/fuzz failures in the Bubblewrap sandbox. Sandbox test failures exit with non-zero codes which are recorded as task results, but they *do not* raise Python exceptions in the orchestrator loop. Hence, the `except Exception` block in `harness/orchestrator.py` is never hit on test failures.
  3. The FSM states `ST_START`, `ST_CYCLE_DETECTION`, `ST_DECOMPOSE_EPIC`, and `ST_GOAL_DEF` are completely missing. Only Briefs (`brief_hooks_*.md`) serve as entry points; there is no pipeline for Goals.
* **Missing Components:** 
  - `check_grounding_required` is not implemented anywhere in the workspace.
  - `extract_missing_symbols` is not implemented anywhere in the workspace.
  - Telemetry and backtrack count functions (`update_task_backtrack_count` and `get_task_backtrack_count` in `harness/state.py`) are completely missing.

### Finding 2.2: Cryptographic Signature Key Manipulation & Default Key Vulnerability
* **Plan Requirement:** The FSM must generate signed `grounding.json` bundles with cryptographic signature validation to prevent tampering.
* **Actual Code:** In `harness/orchestrator.py` (lines 3788-3792):
  ```python
  key = task.get('grounding_key') or task.get('grounding_secret') or ...
  if not key:
      key = 'default_secret_key'
  ```
  If `grounding_key` or `grounding_secret` is omitted in the task configuration, the signature validation defaults to using the static string `"default_secret_key"`. This is a severe security gap: an attacker can easily construct a valid signature using this publicly known default key and inject tampered axioms to hijack the state machine.

### Finding 2.3: Path Parsing Bug in Exception Classification
* **Bug Location:** `harness/grounding.py:68` in `is_project_file`.
* **Vulnerability:** The code checks if a filepath belongs to a third-party library or standard library using simple substring searches:
  ```python
  for marker in ['site-packages', '.venv', 'dist-packages', 'lib/python', '/usr/lib']:
      if marker in norm:
          return False
  ```
  If the operator's workspace folder path happens to contain any of these markers (e.g. `/home/user/my.venv-project/JanusMaskEX`), then `marker in norm` will return `True` for *every project file*. Consequently, `is_project_file` returns `False` for all project files, misclassifying target file syntax errors as `conceptual_mismatch` rather than `implementation_defect`. This breaks FSM routing completely.

### Finding 2.4: Chained Exception Bug in Failure Severity Classification
* **Bug Location:** `harness/grounding.py:51` in `classify_failure_severity`.
* **Vulnerability:** Python chained exceptions (e.g., `raise ValueError from SyntaxError` or when an exception occurs inside a handler) wrap the root cause error. The classification logic only inspects `lines[-1]` (the last line of the traceback). If the traceback ends with a chained exception or wrapper error, the parser misses the underlying `SyntaxError` or `ModuleNotFoundError` root cause, misrouting the task.

### Finding 2.5: Incorrect Classification of Conceptual Triggers
* **Plan Requirement:** `ModuleNotFoundError`, `AttributeError`, `ImportError`, and `KeyError` must be classified as `conceptual_mismatch` to trigger regrounding.
* **Actual Code:** `harness/grounding.py:54`:
  ```python
  if exc_type not in ('SyntaxError', 'IndentationError', 'TabError'):
      return 'implementation_defect'
  ```
  This explicitly forces `ModuleNotFoundError`, `AttributeError`, `ImportError`, and `KeyError` to be classified as `implementation_defect`, preventing them from ever routing to regrounding, in direct violation of the plan.

### Finding 2.6: Local Model Client Dead-Code & Multimodal Mismatch
* **Bug Location:** `harness/model_backends.py:193` in `synthesize_inpaint_with_retries`.
* **Vulnerability:** 
  1. `synthesize_inpaint_with_retries` is never called anywhere in the workspace. It is completely dead code.
  2. The function is designed for *image inpainting* rather than text/code inpainting, taking `image_path` and `mask_path` and base64-encoding them as images. This represents a functional mismatch for text-based GHEI code synthesis.

---

## 3. Adversarial Test & Empirical Evidence

An adversarial script (`adversarial_audit/adversarial_audit_test.py`) was written and run on the live workspace to verify these gaps.

### 3.1 Script Output / Evidence
```
=== Testing validate_grounding_bundle ===
Valid Signature Test: True (Expected: True)
Alg None Exploitation Test: False (Expected: False)
Default Key Vulnerability Test: True (Expected: True - shows default key is vulnerable if not overridden)

=== Testing classify_failure_severity ===
External Dep SyntaxError: conceptual_mismatch (Expected: conceptual_mismatch)
Project File SyntaxError: implementation_defect (Expected: implementation_defect)
Path Parsing Bug (.venv in path): conceptual_mismatch (Expected: implementation_defect, Actual: conceptual_mismatch)
Chained Exception: implementation_defect (Expected: conceptual_mismatch, Actual: implementation_defect)
ModuleNotFoundError: implementation_defect (Expected: conceptual_mismatch, Actual: implementation_defect)
```

---

## 4. Proposed Corrections & Document Additions

### 4.1 Corrections to `final_ghei_implementation_plan.md`

1. **Section 1.1 (Scope of GHEI Pipeline):** 
   - Add warning about separating the orchestrator's exception block from test execution logs. Emphasize that `classify_failure` must run on the *test execution stdout/stderr* rather than the orchestrator's Python traceback.
2. **Section 3.1 (Grounding & Failure Routing - `harness/grounding.py`):**
   - Correct the implementation of `classify_failure` to parse the entire traceback (using regex to look for root cause exceptions) instead of just the final line.
   - Include `ModuleNotFoundError`, `AttributeError`, `ImportError`, and `KeyError` in the severity classifier.
   - Refactor `is_project_file` to perform exact path resolution using `pathlib.Path` parent hierarchy checks instead of insecure substring matches on absolute paths.
   - Enforce cryptographic validation key configuration and forbid fallback to a static default key like `default_secret_key` in production.

### 4.2 Corrections to `ghei-closure-deliverables-and-acceptance-contract.md`

1. **Section 2 (Exit Criteria - X4 & X5):**
   - Update X4 to explicitly require test coverage for chained exceptions, non-SyntaxError conceptual triggers (`ModuleNotFoundError`, `ImportError`), and exact path-resolution validation.
   - Update X5 to require verifying that the state directories do not contain `.venv` style sub-string false-positives.
2. **Section 4 (WAVE 1 deliverables):**
   - Under P1.1, explicitly add `check_grounding_required` and `extract_missing_symbols` as mandatory deliverables with their exact interfaces and assertions.
   - Explicitly add verification tests for default key rejection and alg validation.

# Root-cause: reconciler-reaps-spent-briefs-impl synthesis_or_ast_failed

## CONCLUSION: (3) — promotion working as DESIGNED; NO code gap. Hypothesis REFUTED.

The block is the deliberate operator-approval safety gate for a sensitive `harness/**`
edit, NOT a promotion code defect. NO fix brief authored.

## Trace (non-retry loop; `use_retry_module` absent from config -> False)
- agent_a=claude, agent_b=gemini. Final run: claude submitted a VALID candidate,
  gemini "died without submitting (code 0)" -> poll_for_submission returns None
  (orchestrator.py:1064) -> agent_b_code=None -> status 'timeout'
  (orchestrator_worker.py:406).
- XOR branch FIRES correctly: `(agent_a_code is None) != (agent_b_code is None)`
  -> True (orchestrator_worker.py:417). present=claude, failing=gemini.
- present_valid=True (claude validated, line 442). Decision file read fails
  (no file) -> approval_ok=False (lines 449-454).
- `_single_agent_promotion_decision` (line 456) hits gate 2:
  meta_task_type=='harness_self_fix' -> is_sensitive=True (line 1021); approval_ok=False
  -> returns (False, 'Sensitive target requires operator approval') (line 1037-1038).
- promote=False -> falls through to retry (line 468). gemini timed out all 3 retries
  -> synthesis_success stayed False -> ast_validation_failed
  "no error-severity AST violations recorded" (the XOR/promote path never populates
   agent_*_violations, so the SELFHEAL telemetry has nothing to report) -> _mark_blocked
  'synthesis_or_ast_failed' (line 584).

## Mandate B — analytic AST verification (verify_reconciler_submission.py)
claude submission (code len 2852): ONE symbol patch on harness/state_reconciler.py,
kind=symbol name=reap_stale_disk (R-anchor), code ast.parse OK, top-level defs =
['reap_stale_disk', 'reap_spent_briefs']. VALID + COMPLETE, not truncated.
=> failure is NOT agent quality.

## Contrast that PROVES design-correctness
daemon-self-reload-impl (same shape: harness_self_fix, gemini timeout, claude valid)
SUCCEEDED via single_agent_promotion ONLY because it HAD
state/control/decisions/daemon-self-reload-impl.json {"decision":"approve"} ->
approval_ok=True -> gate 2 passed. The reconciler impl had NO decision file.

The rc=0-no-submit case and the submitted-but-invalid case BOTH route through the same
XOR branch + `_single_agent_promotion_decision`; the sensitivity/approval gate (line
1037) is evaluated before any ceiling/waive, by design fail-closed. No gap remains for
the rc=0-no-submit case specifically.

## RECOMMENDATION (no brief)
This is a sensitive harness/** edit that requires an operator decision file, exactly as
the prior absent-peer/ceiling-waive promotion work intended. To land the reconciler fix,
write state/control/decisions/reconciler-reaps-spent-briefs-impl.json with
{"decision":"approve", ...} and re-dispatch (clear the selfheal_skip marker +
running/.slot first). No harness code change is warranted.

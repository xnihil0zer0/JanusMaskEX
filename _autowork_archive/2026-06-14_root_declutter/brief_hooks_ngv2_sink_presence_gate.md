---
interfaces: "creates the NEW standalone module ngv2/sink_presence_gate.py -- a pure, deterministic, stdlib-only sink-presence gate exposing verify_sink_present(target_source: str, expected_signature: str) -> dict; the function operates ONLY on strings passed in (no filesystem, no network) so it is differential-fuzzable, and returns a fixed-shape dict {present: bool, status: 'present'|'patched_or_moved', in_comment_only: bool, may_confirm: bool}; modelled on the existing pure ngv2 recon helpers and wired so the NobleGreed verdict path can refuse a confirmed verdict when the cited vulnerable construct no longer exists as LIVE code at the pinned SHA"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/sink_presence_gate.py -- NEW pure deterministic gate that verifies the cited vulnerable construct STILL EXISTS as LIVE code in the target source at the pinned SHA before any NobleGreed "confirmed" verdict is allowed. In the bug-bounty pipeline several findings were marked verdict=confirmed against code that was ALREADY PATCHED at the pinned commit (e.g. Flowise mass-assignment later guarded by checkAnyPermission; Flowise SSRF later normalizing IPv4-mapped IPv6 before the deny-check). The PoCs were self-contained, so they never noticed the real source no longer contained the vulnerable construct. This module is the deterministic gate: given the target source text and the expected vulnerable signature, it decides whether that signature occurs as LIVE code -- not only inside comments, string-literals, or docstrings -- and reports whether a "confirmed" verdict may proceed.

# Scope

CREATE the NEW single-file module `ngv2/sink_presence_gate.py` (NobleGreed external-target task -- `working_dir` = /home/xnihil0zer0/NobleGreedv2). The module is PURE and deterministic: its primary function `verify_sink_present(target_source: str, expected_signature: str) -> dict` operates ONLY on the two strings passed in (no filesystem, no network, no clock, no randomness, no subprocess, no MCP, no third-party import, no import of any sibling ngv2 leaf), so identical inputs produce byte-identical output and the function is differential-fuzzable.

The function returns a fixed-shape dict with exactly the keys:
- `present` (bool) -- True iff `expected_signature` occurs in `target_source` as LIVE code.
- `status` (str) -- `"present"` iff `present` else `"patched_or_moved"`.
- `in_comment_only` (bool) -- True iff the signature occurs in the source ONLY inside comments / string-literals / docstrings and never as live code.
- `may_confirm` (bool) -- equals `present`; the NobleGreed verdict path consults this and refuses a "confirmed" verdict when it is False.

MATCHING LOGIC: determine whether `expected_signature` occurs in `target_source` as LIVE code (executable program text), not only inside comments, string-literals, or docstrings. Insignificant whitespace and indentation differences between the signature and the source MUST be normalized so they do not defeat the match. If the signature appears in the source but every occurrence is inside a comment / string-literal / docstring, then `in_comment_only=True` and `present=False`. `present` is True ONLY for a live-code occurrence. `status="present"` iff `present` else `"patched_or_moved"`. `may_confirm = present`.

# Non-Goals

This is an EDIT-adjacent gate leaf; full pipeline integration -- the integration of this gate's verdict-blocking decision into the live NobleGreed verdict-emission path beyond the single reachability/wired hook proven by the committed oracle -- is OUT OF SCOPE for this leaf and belongs to a separate downstream integration EDIT leaf. Do NOT add any real parser/SSA/symbolic-execution dataflow, network, filesystem reads, wall-clock, randomness, subprocess, or logging. Do NOT import any third-party package or any sibling `ngv2/**` leaf. Do NOT touch `ngv2/verdict.py`, `ngv2/submission_verdict.py`, `ngv2/detonation.py`, or any other existing module beyond the minimal wiring reference the oracle requires. Do NOT author or modify any test other than what the committed oracle already pins -- the oracle is authoritative. The string-level live-vs-comment classification (with insignificant-whitespace normalization) is the ONLY analysis in scope; no language-specific full lexing is required.

# Inputs

The committed authoritative oracle `tests/ngv2/test_sink_presence_gate_wired.py` (currently RED -- the module does not yet exist) is the acceptance contract; make it GREEN. It pins the fixed return shape `{present, status, in_comment_only, may_confirm}`, the live-vs-comment classification, the insignificant-whitespace normalization, and the reachability/wired hook into the NobleGreed verdict path. The two motivating real-corpus cases are the Flowise mass-assignment finding (the vulnerable construct later guarded by `checkAnyPermission`) and the Flowise SSRF finding (the deny-check later preceded by IPv4-mapped-IPv6 normalization): in both, the cited vulnerable signature is no longer present as live code at the pinned SHA, so `verify_sink_present` must return `present=False`, `status="patched_or_moved"`, `may_confirm=False`. Reuse the existing pure-helper conventions of the `ngv2/` package (stdlib only -- no new dependency). Fixed inputs to reuse, do NOT rebuild: the NobleGreed verdict path module(s) the gate is wired into, and the committed oracle.

# Deliverables

The NEW file `ngv2/sink_presence_gate.py` exposing the primary function with the exact signature `verify_sink_present(target_source: str, expected_signature: str) -> dict` returning a dict with exactly the keys `present` (bool), `status` (`"present"` | `"patched_or_moved"`), `in_comment_only` (bool), and `may_confirm` (bool), with the matching logic described in Scope. The module is reachable/wired into the NobleGreed verdict path (the verdict path consults `may_confirm` and refuses a "confirmed" verdict when it is False), and the committed oracle `tests/ngv2/test_sink_presence_gate_wired.py` proves that wiring.

The behavior is pinned by at least these edge cases (mirrored in the oracle's regression/property tests):

(a) signature present VERBATIM in live code -> `present=True`, `status="present"`, `in_comment_only=False`, `may_confirm=True`.

(b) signature ABSENT (the construct was patched / removed) -> `present=False`, `status="patched_or_moved"`, `in_comment_only=False`, `may_confirm=False`.

(c) signature appears ONLY inside a `#` comment or a docstring (no live-code occurrence) -> `in_comment_only=True`, `present=False`, `status="patched_or_moved"`, `may_confirm=False`.

(d) signature present in live code but with DIFFERING insignificant whitespace / indentation versus the cited signature -> still `present=True`, `status="present"`, `may_confirm=True` (whitespace is normalized before matching).

Verified GREEN by `python3 -m pytest -q tests/ngv2/test_sink_presence_gate_wired.py`.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and any operator decision file are keyed to it): `task_id`: `ngv2_sink_presence_gate`. meta_task_type=`validation` (NEW pure deterministic gate function -- single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/sink_presence_gate.py"]` ONLY (this is a NEW single-file module -- emit the COMPLETE file whole-file, never a symbol patch). verification_command: `python3 -m pytest -q tests/ngv2/test_sink_presence_gate_wired.py` (CWD-relative -- NO `cd`). The committed RED oracle `tests/ngv2/test_sink_presence_gate_wired.py` is the authoritative acceptance contract -- make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries naming the edge cases above (signature-present-verbatim, signature-absent-patched, comment-only-occurrence, whitespace-normalized-match). Because `non_goals` contains the literal word `integration`, the integration-test requirement is excused; the `*_wired` oracle named in `verification_command` satisfies the wiring requirement.

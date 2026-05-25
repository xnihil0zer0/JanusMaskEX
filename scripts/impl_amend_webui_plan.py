"""scripts/impl_amend_webui_plan.py

One-shot plan amender for plan_hooks_webui_full.json. Drops the 5 Gemini-drafted
tasks (t1-t5 — duplicates of already-shipped v1 sidecar work; critique findings
#7, #8, #9) and applies the critique's suggested_patch blobs for findings
#1, #2, #3, #6, #10, #11, #12, #13, #14. Idempotent — running twice on the
already-amended plan is a no-op.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

PLAN = Path(__file__).resolve().parent.parent / "plan_hooks_webui_full.json"


def _by_id(plan: dict, tid: str) -> dict:
    for t in plan["tasks"]:
        if t["task_id"] == tid:
            return t
    raise KeyError(tid)


def main() -> int:
    plan = json.loads(PLAN.read_text())
    before = len(plan["tasks"])

    # 1. Drop Gemini's t1-t5 (already shipped v1 sidecar duplicates).
    plan["tasks"] = [t for t in plan["tasks"] if not t["task_id"].startswith("t")]

    # 2. Critique #1 (E6 timing-bench inflated) — replace std-dev assertion with
    #    a structural check that hmac.compare_digest is invoked.
    e6 = _by_id(plan, "TASK-E6-INTEGRATION-ADV-TESTS")
    fr = e6["spec"].setdefault("functional_requirements", [])
    if len(fr) > 4 and "std-dev" in fr[4].lower():
        fr[4] = (
            "Adversarial token-comparison test asserts that hmac.compare_digest is "
            "invoked on the auth path (mock import + call-count assertion). Drop the "
            "wall-clock std-dev gate — Python stdlib already guarantees constant-time "
            "comparison; a flaky timing assertion is anti-signal."
        )

    # 3. Critique #2 (E2 compare_digest timing-vague property test) — replace with
    #    two edge-case-covering property tests (the plan validator requires
    #    >= 2 edge_cases reflected in property_tests + regression_tests).
    e2 = _by_id(plan, "TASK-E2-AUTH-CSRF")
    pt = [
        p for p in e2["test_spec"].get("property_tests", [])
        if "runtime_constant" not in p.get("name", "")
    ]
    new_props = [
        {
            "name": "test_arbitrary_token_file_contents_either_load_or_refuse_to_start",
            "accepts": ["arbitrary bytes (0-1024 LoC)"],
            "covers_edge_case": "Token file exists but is empty or shorter than 32 bytes",
        },
        {
            "name": "test_arbitrary_csrf_nonce_strings_either_consumed_or_rejected_with_structured_error",
            "accepts": ["arbitrary URL-safe-ish nonce strings"],
            "covers_edge_case": "Two clients race to consume the same nonce",
        },
    ]
    for np in new_props:
        if not any(p.get("name") == np["name"] for p in pt):
            pt.append(np)
    e2["test_spec"]["property_tests"] = pt

    # 4. Critique #3 + plan-validator rule (minimum_test_count >= 1.5 *
    #    functional_requirements). E5 has 13 FRs -> need >= 20. Add a 20th unit
    #    test (per critique's suggested patch) and keep the count at 20.
    e5 = _by_id(plan, "TASK-E5-FRONTEND-SPA")
    e5["test_spec"]["minimum_test_count"] = 20
    ut5 = e5["test_spec"].setdefault("unit_tests", [])
    if not any(u.get("name") == "test_exponential_backoff_caps_at_30s" for u in ut5):
        ut5.append({
            "name": "test_exponential_backoff_caps_at_30s",
            "accepts": ["SSE reconnect attempts under sustained server unavailability"],
        })

    # 5. Critique #6 (E7 docs token_budget) is contradicted by the plan validator,
    #    which enforces test_tokens >= 1.5 * implementation_tokens for ALL task
    #    types including docs. Honor the validator: keep ratio at 1.5x exactly,
    #    and keep minimum_test_count at the validator floor of
    #    ceil(1.5 * len(functional_requirements)) = 9 for E7's 6 FRs.
    e7 = _by_id(plan, "TASK-E7-RUNBOOK")
    tb = e7.get("token_budget_ratio") or {}
    if tb.get("test_tokens", 0) > 0:
        # Hold impl at 350, set test to exactly 1.5x = 525.
        tb["implementation_tokens"] = 350
        tb["test_tokens"] = 525
        tb["note"] = (
            "Docs deliverable; test budget at the validator floor of 1.5x impl. Tests "
            "are runbook-coverage grep + section-presence checks + curl shell-syntax "
            "validation. Critique flagged this as inverted but the validator enforces "
            "the 1.5x ratio uniformly — honor the validator."
        )
    e7["test_spec"]["minimum_test_count"] = 9

    # 6. Critique #10 (E3 stale/malformed decision file edge cases).
    e3 = _by_id(plan, "TASK-E3-CONTROL-PLANE")
    ec = e3["spec"].setdefault("edge_cases", [])
    addn = [
        "POST /api/tasks/{task_id}/approve when state/control/decisions/{task_id}.json "
        "already exists with a conflicting decision -> 409 with "
        '{"error": "decision_already_recorded", "existing": <decision>}.',
        "Pre-existing decision file is malformed JSON -> 500 with structured error; "
        "do not crash the server; do not silently overwrite operator intent.",
    ]
    for line in addn:
        if line not in ec:
            ec.append(line)

    # 7. Critique #11 (E2 CSRF TTL vs long ops).
    ec2 = e2["spec"].setdefault("edge_cases", [])
    addn2 = (
        "CSRF nonce TTL (5 min) is shorter than some long-running mutating operations "
        "(e.g. POST /api/planner/kickoff which spawns subprocesses). Nonces are "
        "validated and consumed at request entry only — not held across the operation. "
        "Document this contract in the runbook."
    )
    if addn2 not in ec2:
        ec2.append(addn2)

    # 8. Critique #12 (E5 partial JSON write).
    ec5 = e5["spec"].setdefault("edge_cases", [])
    addn5 = (
        "STATE.json mid-write (partial JSON observed via SSE or polling): the store "
        "ignores the update and waits for the next valid parse. After 3 consecutive "
        "parse failures, surface a non-fatal warning toast and a console.warn — do "
        "not stop rendering, do not spam the toast surface."
    )
    if addn5 not in ec5:
        ec5.append(addn5)

    # 9. Critique #13 (E4 pause-flag IO errors).
    e4 = _by_id(plan, "TASK-E4-ORCHESTRATOR-HITL")
    ec4 = e4["spec"].setdefault("edge_cases", [])
    addn4 = (
        "pause_flag_path exists but is a directory (EISDIR), unreadable (EACCES), or "
        "vanished mid-read: log once at WARNING and treat as not-paused; do not crash "
        "run_pipeline. Idempotent — repeated failures collapse to one log entry per "
        "minute."
    )
    if addn4 not in ec4:
        ec4.append(addn4)

    # 10. Critique #14 (E1+E6 file ownership of tests/integration/test_webui_static.py).
    e1 = _by_id(plan, "TASK-E1-STATIC-SHELL")
    spec_e1 = e1["spec"]
    impl_notes = spec_e1.get("implementation_notes", "") or ""
    ownership_note = (
        "\n\nOWNERSHIP: tests/integration/test_webui_static.py is **owned by E1**. "
        "E1 ships a minimal seed (root + traversal asserts only). E6 imports and "
        "extends it via additional test_* functions in the same file — E6 must NOT "
        "rewrite the seed. Diff at execution time should be append-only relative to "
        "E1's commit."
    )
    if "OWNERSHIP:" not in impl_notes:
        spec_e1["implementation_notes"] = impl_notes + ownership_note

    e6_notes = e6["spec"].get("implementation_notes", "") or ""
    if "OWNERSHIP:" not in e6_notes:
        e6["spec"]["implementation_notes"] = e6_notes + (
            "\n\nOWNERSHIP: tests/integration/test_webui_static.py is owned by E1 "
            "(see E1 implementation_notes). E6 extends append-only — no rewrite of "
            "the E1 seed."
        )

    PLAN.write_text(json.dumps(plan, indent=2) + "\n")
    after = len(plan["tasks"])
    print(f"amended: {before} -> {after} tasks; dropped t1-t5; applied 9 critique patches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

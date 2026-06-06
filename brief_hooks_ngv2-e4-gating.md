---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Super-epic B — ngv2-e4-gating: target eligibility/qualification & safety validators (epic: true, child_epics: true)

# Scope

An epic (`epic: true`, `child_epics: true`, `plan_kind: epic`) that decomposes into EXACTLY
TWO sub-epic children, each itself an epic (`epic: true`, `plan_kind: epic`) decomposing
into leaf modules under the `ngv2/` package of the external NobleGreedv2 repo (working_dir
/home/xnihil0zer0/NobleGreedv2). The two sub-epics:

## Sub-epic B1 — slug `ngv2-e4-eligibility-pkg` (`epic: true`)
EIGHT leaves: target qualification gating, bounty payout lookup, repo-complexity assessment,
web-framework detection, language-specific vulnerability patterns, deserialization-usage
detection, the huntr-eligibility CACHE replay (pure; the live HTTP fetch is deferred), and
batch qualification orchestration.

## Sub-epic B2 — slug `ngv2-e4-safety-pkg` (`epic: true`)
FIVE leaves: graduated permission model, bash-command validation, prompt-integrity
verification, the safety framework (deterministic state), and prompt-hint accumulation.

Each leaf is a NEW single-file whole-file deterministic stdlib-only Python module, IMPL-only
(its oracle is already committed at tests/test_<leaf>.py), verified with
`python -m pytest tests/test_<leaf>.py -q`. Leaves are mutually independent and may build in
any order; they consume only the already-committed ngv2 spine via plain imports.

# Non-Goals

No live huntr.com HTTP (the eligibility cache replays committed JSON only). No live command
execution — bash validation is static analysis of command strings. No leaf authors tests.
No third-party imports (stdlib only). No cross-leaf wiring.

# Inputs

The external NobleGreedv2 repo with the committed spine and the committed Epic-4
B-super-epic leaf oracles. Legacy design source: /mnt/ai-data/NobleGreed-legacy/services
(huntr_eligibility.py, qualify_target.py, bounty_gate.py, permission_model.py,
bash_validator.py, prompt_integrity.py, safety.py, prompt_hints.py) and
/services/tools (repo_complexity_check.py, detect_web_framework.py,
language_specific_patterns.py, quick_deser_check.py, batch_qualify.py).

# Deliverables

Thirteen NEW single-file whole-file ngv2/ modules across the two sub-epics, each IMPL-only
and pinned by its committed oracle, each verified with
`python -m pytest tests/test_<leaf>.py -q`. Every brief carries working_dir
/home/xnihil0zer0/NobleGreedv2.

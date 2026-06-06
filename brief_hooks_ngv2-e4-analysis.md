---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Super-epic A — ngv2-e4-analysis: vulnerability detection, grounding, adversarial & neurosymbolic verification (epic: true, child_epics: true)

# Scope

An epic (`epic: true`, `child_epics: true`, `plan_kind: epic`) that decomposes into EXACTLY
THREE sub-epic children, each itself an epic (`epic: true`, `plan_kind: epic`) that
decomposes into leaf modules under the `ngv2/` package of the external NobleGreedv2 repo
(working_dir /home/xnihil0zer0/NobleGreedv2). The three sub-epics:

## Sub-epic A1 — slug `ngv2-e4-grounding-pkg` (`epic: true`)
SEVEN leaves: deterministic rule-based vulnerability scanning, false-positive knowledge
base, portfolio classification, semgrep+regex cross-validation pre-analysis, the taint-spec
library, and the CodeQL/Joern injected-runner shells (mock seam; never invoke the real CLI).

## Sub-epic A2 — slug `ngv2-e4-adversarial-pkg` (`epic: true`)
SIX leaves: adversarial root-cause classification, injection-cycle scoring, evasion variant
generation, and the model-file-format (MFF) root-cause / variant-generator / scorer family.

## Sub-epic A3 — slug `ngv2-e4-neurosymbolic-pkg` (`epic: true`)
FOUR leaves: AST constraint checking, AST-based policy verification, constraint-accumulating
backtracking search, and the z3 SMT-solver bridge with a deterministic rule-based fallback
(injected solver seam).

Each leaf is a NEW single-file whole-file deterministic stdlib-only (or injected-seam)
Python module, IMPL-only (its oracle is already committed at tests/test_<leaf>.py), verified
with `python -m pytest tests/test_<leaf>.py -q`. Leaves are mutually independent within and
across sub-epics and may build in any order; they consume only the already-committed
ngv2 spine (ngv2.contracts.Finding etc.) via plain imports.

# Non-Goals

No live analyzer subprocess (CodeQL/Joern/semgrep) execution — injected runner seams only,
tested with mocks. No live z3 process required — the bridge must work via its rule-based
fallback. No leaf authors tests. No third-party imports (stdlib only). No cross-leaf wiring.

# Inputs

The external NobleGreedv2 repo with the committed Epic-1/2/3 spine and the committed Epic-4
A-super-epic leaf oracles. Legacy design source: /mnt/ai-data/NobleGreed-legacy/services/code_audit,
/services/adversarial, /services/neurosymbolic, /knowledge/taint_specs.

# Deliverables

Seventeen NEW single-file whole-file ngv2/ modules across the three sub-epics, each
IMPL-only and pinned by its committed oracle, each verified with
`python -m pytest tests/test_<leaf>.py -q`. Every brief carries working_dir
/home/xnihil0zer0/NobleGreedv2.

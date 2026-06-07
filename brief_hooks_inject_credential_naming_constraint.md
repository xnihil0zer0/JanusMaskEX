---
interfaces: "adds a NEW pure helper `harness.planner.plan_normalizer._inject_credential_naming_constraint(plan, repo_root)` and wires ONE call to it into the existing `normalize_plan` chain (after `_force_smoke_gated_leaf_impl`, before `_inject_oracle_sources`); no signature change to `normalize_plan`"
---

# Title

B6: inject a credential-naming constraint into external-build leaf specs so synthesis avoids the hardcoded-credential AST gate

# Scope

`harness/ast_enforcer.py` flags ANY variable whose name matches the
case-insensitive pattern `(password|secret|key)` assigned a string LITERAL as a
`security` error ("Hardcoded credential detected in variable '<name>'") — strict
even for an EXTERNAL clean-room target (e.g. the NobleGreedv2 `ngv2/*` modules).
A leaf whose natural implementation binds a field label / check id / dictionary
key to a variable named `key` (or `secret`, `password`, `api_key`, `secret_key`,
…) therefore fails synthesis (`synthesis_or_ast_failed`) and exhausts its retry
budget, even though the code is correct and contains NO real credential.
Empirically: `submission_readiness` bound field-label literals to a var named
`key` → 5 findings → terminal.

Fix (lowest risk; does NOT loosen the security gate): a NEW pure deterministic
helper `_inject_credential_naming_constraint(plan, repo_root)` that, for
EXTERNAL-build leaf plans, appends a short directive to every non-test_authoring
task's `spec['implementation_notes']` steering the blind synthesis agent away
from binding string literals to credential-named variables. It mirrors the
existing `_inject_oracle_sources` precedent in the same file (pure, deep-copy,
idempotent, strict no-op when inert) — it changes ONLY the spec the agent reads,
never the code the AST gate inspects. The helper is added as a NEW top-level def
ANCHORED as a trailing definition rendered with the single-symbol patch on
`normalize_plan` (the same R-anchor technique used to land `_inject_oracle_sources`
and `_force_smoke_gated_leaf_impl`), and `normalize_plan` gains exactly ONE new
call to it, placed AFTER `_force_smoke_gated_leaf_impl(...)` and BEFORE
`_inject_oracle_sources(...)`.

EXACT helper behaviour (reproduce precisely; the committed oracle
`tests/planner/test_inject_credential_naming_constraint.py` is authoritative):

1. Strict no-op returning the input unchanged when: `repo_root is None`; `plan`
   is not a dict; `plan.get('child_slugs')` is truthy (an epic plan); or
   `Path(repo_root).resolve() == Path(PROJECT_ROOT).resolve()` (a JM-INTERNAL
   self-fix plan — it MUST NEVER be steered). Import
   `from harness.paths import PROJECT_ROOT`. Guard the `.resolve()` call so a bad
   `repo_root` (TypeError/ValueError/OSError) returns the input unchanged.
2. Otherwise deep-copy the plan. If `tasks` is not a list, return the copy.
3. For each task that is a dict, is NOT test_authoring (use the module's existing
   `_is_test_authoring(t)` helper), and carries a dict `spec`: read
   `notes = spec.get('implementation_notes')`. If `notes` is a str already
   containing the literal marker `CREDENTIAL-NAMING CONSTRAINT`, SKIP it
   (idempotent). Otherwise append a constraint block to
   `spec['implementation_notes']` (preserve any existing notes by appending; if
   notes is empty/None set it to the block).
4. The appended block MUST contain the literal marker text
   `CREDENTIAL-NAMING CONSTRAINT`, the phrase `string literal`, and must name the
   triggering substrings `key`/`secret`/`password`. RECOMMENDED block text:

   `\n\n# CREDENTIAL-NAMING CONSTRAINT (the AST security gate FAILS the build if a variable whose name contains (case-insensitive) "password", "secret", or "key" is assigned a string literal — it reads as a hardcoded credential even though this is an external clean-room target with no real secret). NEVER bind a string literal to such a variable. Use a neutral name instead (field_name, check_id, label, name, ident, column) or iterate a collection literal / build the mapping from a list of tuples. This applies to dict keys held in a temp var, field labels, and constant identifiers.\n`

5. Return the modified copy. Pure (deep-copy, never mutate the input). Idempotent
   (the marker guard prevents a second injection).

# Required plan shape

EXACTLY ONE task. `meta_task_type: planner_tooling` (the target
`harness/planner/plan_normalizer.py` is NOT on the `_NEVER_AUTO_APPROVE`
deny-list, so this auto-commits on the worker path with NO operator decision
file). A single-symbol partial edit of `normalize_plan` that inserts the one new
call AND renders the new `_inject_credential_naming_constraint` def as a trailing
definition anchored on that same patch (NEVER whole-file edit the module; do NOT
add `_inject_credential_naming_constraint` as its own separate patch entry). No
test-authoring task (oracle already committed). `verification_command:
python -m pytest tests/planner/test_inject_credential_naming_constraint.py tests/planner/test_force_smoke_gated_leaf_impl.py tests/planner/test_inject_oracle_sources.py tests/planner/test_plan_normalizer.py -q`
(the new oracle PLUS three existing plan_normalizer suites, to prove no
regression). Do NOT glob `tests/planner/`.

# Non-Goals

Do NOT change the `normalize_plan` signature or the order of the existing
`_dedupe_oracles` / `_enforce_module_first` / `_sanitize_impl_verification_commands`
/ `_force_smoke_gated_leaf_impl` / `_inject_oracle_sources` steps (only INSERT the
new call between `_force_smoke_gated_leaf_impl` and `_inject_oracle_sources`). Do
NOT steer JM-internal plans (`repo_root` None or PROJECT_ROOT) — a hard invariant
pinned by the oracle. Do NOT touch `ast_enforcer.py` or relax the security
heuristic. Do NOT touch any other module or the daemon. Do NOT add a config flag.
Do NOT whole-file edit `plan_normalizer.py`. Keep the helper pure (deep copy, no
mutation of the input, no I/O). This is a pure deterministic in-memory transform
with no I/O, subprocess, network, or external collaborator, so NO integration
test is required or wanted — the committed unit-level oracle fully covers it;
exclude integration tests (record this integration exclusion in the task's
non_goals).

# Inputs

`harness/planner/plan_normalizer.py`: the existing `normalize_plan` (chains
`_dedupe_oracles` -> `_enforce_module_first` -> `_sanitize_impl_verification_commands`
-> `_force_smoke_gated_leaf_impl` -> `_inject_oracle_sources`; insert the new call
between the last two), the `_inject_oracle_sources` helper as the structural
template (pure, deep-copy, repo_root guard, idempotent, marker-skip), and the
existing `_is_test_authoring(task)` helper for the skip predicate.
`harness/ast_enforcer.py` `visit_Assign`/`visit_AnnAssign` confirm the heuristic
(`re.search('(?i)(password|secret|key)', target.id)` on a string-`Constant`
assignment). `harness/paths.PROJECT_ROOT` distinguishes internal from external
plans. The committed RED oracle
`tests/planner/test_inject_credential_naming_constraint.py` pins the exact
contract.

# Deliverables

The new `_inject_credential_naming_constraint` helper + the single inserted call
in `normalize_plan`, landing green against the committed oracle and the three
named regression suites. IMPLEMENTATION CONSTRAINTS to emit as
implementation_notes: meta_task_type planner_tooling (non-deny -> auto-commit, no
decision file); oracle-first (already committed); single-symbol partial edit of
`normalize_plan` with the new def R-anchored as a trailing node on that patch (the
`_inject_oracle_sources` / `_force_smoke_gated_leaf_impl` precedent);
verification_command names the four test files explicitly (no glob, no network,
no pip).

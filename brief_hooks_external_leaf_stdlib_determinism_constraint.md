---
interfaces: "broadens the existing external-leaf constraint emitted by `harness.planner.plan_normalizer._inject_credential_naming_constraint(plan, repo_root)` to ALSO forbid third-party imports (stdlib-only) and wall-clock / nondeterministic sources, in ONE constraint block; no signature change, no other function touched, no change to when it fires"
---

# Title

B6-twin: extend the external-leaf synthesis constraint to enforce stdlib-only + determinism (stop pydantic / datetime.now build failures)

# Scope

`harness.planner.plan_normalizer._inject_credential_naming_constraint` already
appends a credential-naming directive to every external-build leaf task's
`spec['implementation_notes']` (so blind synthesis avoids the hardcoded-credential
AST gate). Two MORE synthesis-quality classes fail external leaves the same way —
the blind agent reaches for a construct the STDLIB-ONLY DETERMINISTIC verification
jail forbids:

1. THIRD-PARTY IMPORTS: data-model / config leaves import `pydantic` /
   `pydantic_settings` (e.g. ngv2/kg_schema.py, ngv2/kg_config.py). These are NOT
   installed in the verification environment, so `pytest tests/test_<leaf>.py`
   fails collection (exit 2) -> auto_commit rollback -> the leaf is parked. The
   AST gate does not catch this (it is not eval/nondeterminism), so synthesis
   passes but verification fails.
2. WALL-CLOCK / NONDETERMINISM: clock-stamping leaves call `datetime.now()` /
   `time.time()` etc. (e.g. ngv2/crash_analyzer.py), which the AST nondeterminism
   gate rejects -> synthesis_or_ast_failed -> parked.

Fix: broaden the SAME constraint block this helper already emits so it carries
THREE directives instead of one — keeping the existing credential-naming
directive verbatim and ADDING (a) stdlib-only and (b) determinism directives.
This changes ONLY the spec text the blind agent reads; it does not touch any gate.

EXACT behaviour (the committed oracle
`tests/planner/test_inject_credential_naming_constraint.py` is authoritative):

- The helper keeps firing in exactly the same cases as today (external leaf,
  non-test_authoring tasks with a dict spec; strict no-op for repo_root None /
  PROJECT_ROOT / epic plan; pure; idempotent via the existing marker check).
- The appended block STILL begins with / contains the literal marker
  `CREDENTIAL-NAMING CONSTRAINT` and STILL contains the phrase `string literal`
  and the credential substrings `key`/`secret`/`password` (the existing oracle
  assertions must keep passing).
- The block ADDITIONALLY contains, in the SAME appended text:
  * the word `stdlib` AND the literal `pydantic` — a directive: "import ONLY the
    Python standard library; do NOT import any third-party package (NO pydantic,
    pydantic_settings, attrs, pyyaml, numpy, requests, ...) — they are NOT
    installed in the verification environment and the import fails collection;
    for data models / config use stdlib dataclasses / enum / typing and plain
    dict/JSON, never pydantic BaseModel/BaseSettings".
  * the literal `datetime.now` (or the phrase `wall-clock`) AND at least one of
    `time.time` / `random` / `uuid` / `secrets` — a directive: "do NOT call
    wall-clock / nondeterministic sources (datetime.now/utcnow, time.time/
    monotonic, unseeded random, uuid, os.urandom, secrets); accept any timestamp
    / seed / clock as an explicit parameter with a deterministic default (the
    oracle injects it via now_fn / make_scripted_clock) — the AST gate bans
    these constructs".
- The idempotency marker check stays the SAME literal (`CREDENTIAL-NAMING
  CONSTRAINT`), so a note already carrying it is skipped (no double-append) and
  `normalize_plan` run twice is unchanged.

Implement by replacing the single block string the helper currently appends with
the broadened multi-directive block string (keep the credential text intact, add
the two new directives). Do NOT change the marker, the firing conditions, the
deep-copy purity, or the skip logic.

# Required plan shape

EXACTLY ONE task. `meta_task_type: planner_tooling` (the target
`harness/planner/plan_normalizer.py` is NOT on the `_NEVER_AUTO_APPROVE`
deny-list, so this auto-commits on the worker path with NO operator decision
file). A single-symbol partial edit of `_inject_credential_naming_constraint`
ONLY (do NOT touch any other function; do NOT whole-file edit the module). No
test-authoring task (oracle already committed). `verification_command:
python -m pytest tests/planner/test_inject_credential_naming_constraint.py tests/planner/test_force_smoke_gated_leaf_impl.py tests/planner/test_inject_oracle_sources.py tests/planner/test_plan_normalizer.py -q`
(the extended oracle PLUS three existing plan_normalizer suites). Do NOT glob
`tests/planner/`.

# Non-Goals

Do NOT change the helper signature, its firing conditions, the marker literal,
the deep-copy purity, or the idempotency skip. Do NOT remove or weaken the
existing credential-naming directive — only ADD the stdlib-only and determinism
directives to the SAME block. Do NOT touch `ast_enforcer.py`, the verification
jail, or any gate. Do NOT touch any other module or the daemon. Do NOT add a
config flag. Do NOT whole-file edit `plan_normalizer.py`. INTEGRATION-TEST
EXCLUSION: this is a pure deterministic in-memory string transform with no I/O,
subprocess, network, or external collaborator, so NO integration test is
required or wanted — the committed unit-level oracle fully covers it; exclude
integration tests (record this integration exclusion in the task's non_goals).

# Inputs

`harness/planner/plan_normalizer.py`: the existing
`_inject_credential_naming_constraint` (the block-string it appends + its marker
skip + deep-copy purity); broaden ONLY the appended block string. The committed
oracle `tests/planner/test_inject_credential_naming_constraint.py` pins the exact
contract (credential text preserved + stdlib/pydantic + datetime.now/wall-clock
directives added). `harness/ast_enforcer.py` confirms the nondeterminism ban; the
stdlib-only requirement is enforced by the verification environment (pydantic is
absent there).

# Deliverables

The broadened `_inject_credential_naming_constraint` block landing green against
the committed oracle and the three named regression suites. IMPLEMENTATION
CONSTRAINTS to emit as implementation_notes: meta_task_type planner_tooling
(non-deny -> auto-commit, no decision file); oracle-first (already committed);
single-symbol partial edit of `_inject_credential_naming_constraint` only;
verification_command names the four test files explicitly (no glob, no network,
no pip).

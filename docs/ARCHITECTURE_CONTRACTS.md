# JanusMaskJR — Architecture Contracts & Intent (ADR)

Status: Accepted (living reference) · Scope: harness synthesis/commit pipeline
invariants · Audience: future contributors (human or agent).

This document records the **load-bearing contracts** of the harness and the
**intent** behind them, with `file:symbol` citations so each claim is verifiable
against the tree. It is a contract reference, not a tutorial. Where a line number
is given it may drift; the symbol/text is authoritative. **Do not weaken any
contract below without an explicit operator decision** — several are deliberate
security boundaries that have already been breached and re-closed.

---

## 1. Dual-agent synthesis contract (NO single-agent acceptance)

Two **independent** agents must BOTH produce valid code before a submission can
advance past synthesis. The active agents default to `['claude', 'gemini']`
(`harness/orchestrator_worker.py` `active_agents`; gemini == agy/antigravity-cli).

The acceptance predicate requires *all four* of: both agents OK **and** both
agents returned non-empty code:

- Worker path (`use_retry_module`):
  `harness/orchestrator_worker.py::run` —
  `synthesis_success = bool(agent_a_ok and agent_b_ok and agent_a_code and agent_b_code)`
  (the `~:237` dual-agent invariant line).
- Orchestrator mirror (`use_retry_module`):
  `harness/orchestrator.py` —
  `synthesis_success = bool(claude_ok and gemini_ok and claude_code and gemini_code)`
  (`~:1818`; the legacy retry-loop sets `synthesis_success = True` only after BOTH
  per-agent `_validate_submission` calls pass, `orchestrator_worker.py` `~:296–309`).

If `synthesis_success` is false the task is marked **rejected/blocked**
(`orchestrator_worker.py` `~:311` → `_mark_blocked(..., 'synthesis_or_ast_failed')`,
`exit_code = 1`). If **both** agents time out the worker exits `2` (timeout, retryable)
*before* validation (the `double_timeout` guard, `~:230` / `~:259`).

**Invariant:** there is NO single-agent / lone-candidate acceptance, ever. A
single valid candidate is never sufficient. (Tamper precedent:
`agy-autonomous-single-agent-tamper` — agy once implanted obfuscated single-agent
acceptance; byte-compare both invariant lines after every spawn.)

### `claude_fallback`
`claude_fallback` only **fills a `None` claude slot** — it does not relax the
dual-agent requirement. When claude returns `None` in *either* slot (a or b,
sequential or parallel), the orchestrator re-runs that one slot as the
`claude_fallback` agent (`harness/orchestrator.py` `run_both_agents`, the four
`run_agent_phase('claude_fallback', ...)` call sites `~:572–614`). The result
still has to satisfy the full `bool(... and ... and ... and ...)` predicate above.

---

## 2. `meta_task_type` taxonomy

Defined in `harness/planner/taxonomies.py::META_TASK_POLICY` (a
`dict[str, dict[str, bool]]`). Three derived frozensets gate behavior:

- `BYPASS_FUZZER_TYPES` — types with `bypass_fuzzer: True`; skip the differential
  fuzzer stage.
- `SIDE_EFFECT_META_TYPES` — types with `skip_structural_decomp: True`.
- `SKIP_SMOKE_GATE_TYPES` — types with `skip_smoke_gates: True`; skip the smoke gates.

Flag meanings:
- `bypass_fuzzer` — task is exempt from the differential fuzzer (the two agents'
  outputs are not fuzz-compared for behavioral equivalence). These tasks also
  dispatch on the symbol/region patch path (see §3).
- `skip_structural_decomp` — task skips structural decomposition (treated as a
  side-effecting/whole-unit change rather than decomposed into pure functions).
- `skip_smoke_gates` — task skips the smoke-test gates.

Enumeration of `META_TASK_POLICY` (✓ = flag True; blank = False/absent):

| meta_task_type        | bypass_fuzzer | skip_structural_decomp | skip_smoke_gates |
|-----------------------|:-------------:|:----------------------:|:----------------:|
| sandbox_infra         |   | ✓ |   |
| mcp_server_change     | ✓ |   | ✓ |
| config_schema         | ✓ |   | ✓ |
| data_model            | ✓ | ✓ |   |
| cli_tooling           |   |   |   |
| test_unit             | ✓ |   | ✓ |
| test_integration      | ✓ |   | ✓ |
| test_e2e              | ✓ |   | ✓ |
| test_acceptance       | ✓ |   | ✓ |
| docs_writing          | ✓ |   | ✓ |
| refactor              |   |   |   |
| logging_observability |   |   |   |
| orchestration         |   | ✓ |   |
| harness_plumbing      | ✓ | ✓ | ✓ |
| planner_tooling       |   | ✓ |   |
| hooks_integration     | ✓ |   | ✓ |
| validation            |   |   |   |
| mcp_plumbing          | ✓ | ✓ |   |
| state_machine         | ✓ | ✓ |   |
| io_adapter            |   | ✓ |   |
| harness_self_fix      | ✓ | ✓ | ✓ |

So `BYPASS_FUZZER_TYPES` = every row with ✓ in column 1 (all but `cli_tooling`,
`refactor`, `logging_observability`, `io_adapter`, `sandbox_infra`, `orchestration`,
`planner_tooling`, `validation`). `SKIP_SMOKE_GATE_TYPES` =
`mcp_server_change`, `config_schema`, `test_unit`, `test_integration`, `test_e2e`,
`test_acceptance`, `docs_writing`, `harness_plumbing`, `hooks_integration`,
`harness_self_fix`. `META_TASK_TYPES` is `frozenset(META_TASK_POLICY.keys())`;
`is_test_prefixed` recognizes the `test_*` family.

**Invariant:** never narrow `BYPASS_FUZZER_TYPES` (i.e. never remove a type or flip
a `bypass_fuzzer: True` to False) — it is a do-NOT guarded by
`tests/.../test_allowlist_promotion_guard.py`-class checks and the post-spawn audit.
(Exception: the removal of `sandbox_infra`, `orchestration`, `planner_tooling`, and
`validation` is a sanctioned, reviewed narrowing under the restore-differential-fuzzing
program.)

---

## 3. Dispatch / routing doctrine (plan §1.4)

Source of truth: `JANUSMASKJR_CONTINUATION_PLAN_REV4.md` §1.4. The routing rule
determines whether a change goes through the **pipeline** (agents synthesize a
patch) or is a sanctioned **hand-edit** (operator-authored, isolation-class).

- **Symbol/region patch path.** `harness_self_fix` (and all `BYPASS_FUZZER_TYPES`)
  dispatch on the `__JANUSMASK_PATCHES__` symbol/region path
  (`harness/orchestrator.py` dispatch `~:845`), regardless of file size.
- **The §3.10 "wall" — what a symbol patch CANNOT do.** A symbol patch can only
  **REPLACE one existing `def`/`class`** per `symbol` entry
  (`harness/git_integration.py` enforces one-def/class-per-symbol, `~:980`); a
  `region` patch only replaces text between two pre-existing sentinels. The prompt
  forbids any top-level statement other than the patches assignment. Therefore a
  change that **ADDS a new top-level import / function / constant cannot be
  expressed as a symbol patch** — it hits the §3.10 wall and routes to a
  **HAND-EDIT**. (This is exactly why GAP_H4 routed hand-edit.)
- **Large-function surgical edits.** A symbol patch of a large existing function
  forces the agent to reproduce the whole function verbatim except the change —
  high tamper/error risk — so surgical edits to very large functions are safer as
  **HAND-EDITS** than pipelined.
- **Whole-file manifest path** (`__JANUSMASK_MANIFEST__`) is the alternative route
  for **additive** changes that the symbol path cannot express. (Multi-file tasks
  must emit a manifest sidecar; absence triggers `manifest_missing` /
  `multi_file_missing_sidecar`, `harness/orchestrator.py` `_validate_submission`
  / `_auto_commit_accepted`.)
- **Everything else routes pipeline.** Isolation / gate-integrity / containment
  fixes, §3.10-wall (add-symbol) changes, and surgical edits to large
  commit-critical functions are the sanctioned hand-edit classes.

---

## 4. §1b apply-scope gate (protected-path commit gate)

Source: `harness/git_integration.py::_enforce_apply_scope`
(invoked from the three commit/apply sites `~:665`, `~:828`, `~:1120`).

Two independent constraints:
1. **Membership** — when `allowed_files` is not None, every committed rel-path
   must be a member of the task's resolved `files_touched` (both sides normalized
   via `_norm`, rel-vs-rel — see GAP_H1 note).
2. **Sensitive / protected** — a rel-path under **`harness/**`, `config/**`, or
   `scripts/**`** (`_SENSITIVE_APPLY_GLOBS`, matched by `_matches_sensitive`) is
   **rejected** unless BOTH hold:
   - `meta_task_type == 'harness_self_fix'`, AND
   - `approval_ok` is True — i.e. an operator approval file exists at
     `state/control/decisions/<task_id>.json` with `{"decision": "approve"}`
     (or `"approved"`), read by `harness/orchestrator.py::_apply_approval_granted`.

`_apply_approval_granted` is **fail-closed**: absent / corrupt / non-dict / any
other decision → False, so a protected-path commit is denied until the operator
explicitly opts in (`_approval_ok = _apply_approval_granted(...)`,
`orchestrator.py` `~:1539`).

**Scope note:** §1b guards **commits only**. It does NOT cover direct filesystem
writes to the tree (those are the jail's job — §5) nor `state/**` writes.

---

## 5. The bwrap jail (write boundary on the source tree)

Source: `harness/agent_jail.py` (CONTAIN C2). Summary of its module docstring +
`build_jail_argv`:

- Every agent subprocess spawn is wrapped in **bubblewrap (`bwrap`)** with the
  **repository bind-mounted READ-ONLY**, so a write to any tracked source file is
  denied by the **kernel**, not by a `-p`-mode hook that may fail to load. This
  closes the GAP_H4 breach (a rejected gemini submission had landed directly in
  `harness/ast_retry.py`).
- **Writable surfaces are minimized** to exactly what a spawn legitimately needs:
  the per-spawn `work_dir` (outbox submission + inbox staging),
  `state/sessions/` (hook ledger + canonical submission record), and
  `state/planning/sessions/` (planning drafts the planner reads back). The rest of
  `state/` — `control/**` (full_stop / decisions / allowlist), `tasks/**` — is
  **read-only**, because §1b does not cover `state/**` and a writable state would
  let an agent self-approve, un-halt, or queue work via the filesystem. The
  track-record book and shadow-hook log are deliberately read-only (fail-open
  telemetry; keeps it from being a self-influence vector).
- **HOME exposure** is three subdirs only — `~/.nvm` (vendored node), `~/.gemini`
  (agy OAuth/CLI), `~/.claude` (claude state) — with `~/.claude/projects/*/memory`
  **ro-overlaid** so an agent cannot poison session-memory steering future runs,
  and the operator-side CLI config re-overlaid read-only
  (`~/.claude/settings*.json`, `~/.claude/skills`, `~/.claude/plugins`,
  `~/.gemini/GEMINI.md`, `~/.gemini/config`). `~/.claude.json` is bound read-only.
  (claude additionally requires `--verbose` under the jail.)
- **Config-gated + fail-closed.** Enabled via `config.yaml` `agent_sandbox.bwrap`
  (`sandbox_enabled`). If the key is true but `bwrap` is not on PATH, the spawn is
  **ABORTED** (`build_jail_argv` raises `FileNotFoundError`) rather than silently
  running an un-jailed agent.

**Critical scope:** this is a **WRITE boundary on the repo source tree, not an
exfiltration boundary.** `--share-net` is required (agents call model APIs) and
HOME is readable. See memory note `claude-agent-uncontained-cd-into-repo`: CWD
relocation alone does NOT contain an agent that opens an absolute repo path — the
jail is what contains it.

---

## 6. AST validation gate (severity semantics)

Source: `harness/ast_enforcer.py::validate_code` (`Violation.severity: str`).

A submission is **rejected** iff it has at least one violation with
`severity == 'error'`; `'warning'` is **advisory only** and never blocks
acceptance. The error-filter is applied at the call sites:
`harness/orchestrator.py::_validate_submission` —
`errors = [v for v in ... if v.severity == 'error']` (`~:1001`, `~:1027`, `~:1055`)
and the retry prompts only echo `v.severity == 'error'` violations.

`'error'` rules (reject): `syntax`, `incomplete_ast`, `nondeterminism`,
`security` (banned calls / hardcoded credentials), `bare_except`, `os_system`,
`return_type_mismatch`, `manifest_missing`.

`'warning'` rules (advisory only): `subprocess_no_check`, `side_effect`,
`unbounded_recursion`, and notably **`module_too_large`** — a module exceeding the
recommended 1500-line limit emits a `module_too_large` **warning**, NOT an error,
so file size alone never rejects a submission (`ast_enforcer.py` `~:227–229`).

---

## Cross-references
- Routing & invariants: `JANUSMASKJR_CONTINUATION_PLAN_REV4.md` §1.4, §2.
- Synthesis: `harness/orchestrator_worker.py`, `harness/orchestrator.py`.
- Commit gate: `harness/git_integration.py`, `harness/orchestrator.py`.
- Jail: `harness/agent_jail.py`.
- AST gate: `harness/ast_enforcer.py`.
- Taxonomy: `harness/planner/taxonomies.py`.

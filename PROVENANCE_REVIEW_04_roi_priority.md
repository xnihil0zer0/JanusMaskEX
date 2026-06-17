# Provenance Injection — Adversarial ROI / Prioritization Review

**Reviewer stance:** hard-nosed skeptic. Question: is "provenance injection" the highest-leverage
investment, or a distraction from bigger, cheaper, more permanent bottlenecks?

**Verdict up front:** Provenance ranks LOW. The dominant loss is not regression and not dup-PoCs —
it is **good code being thrown away by gates and budgets before it can land**. Internal
regression-provenance solves a near-empty problem; the only slice that survives the ROI cut is a
thin **external commit-pin + eligibility thread** for submission *correctness* (not dedup). All of it
is out-ranked by three cheaper, more permanent fixes. Do #1 first: align the promotion ceiling with
the retry budget OR raise the synthesis retry budget — it costs a one-line change and unblocks the
entire class of "one valid agent, one mis-escaped agent" tasks, including the fix that is currently
stuck trying to land.

---

## 1. Verification of the empirical claims (file:line)

### 1.1 Single-agent promotion is WIRED and ENABLED — but structurally unreachable. CONFIRMED (with a twist)
- The mechanism is wired into the live dispatch loop:
  `harness/orchestrator_worker.py:486` calls `_single_agent_promotion_decision(...)` inside the XOR
  branch (`agent_a_valid != agent_b_valid`, line 464), and on `promote` it forces
  `synthesis_success = True` and breaks (lines 487-494).
- It is ENABLED in config: `harness/config.yaml:118 enable_single_agent_promotion: true`,
  `harness/config.yaml:121 single_agent_promotion_ceiling: 3`.
- **TWIST / stale docstring:** the decision function's own docstring
  (`harness/orchestrator_worker.py:941-944`) still says it is *"PURE, opt-in, and dead-until-wired:
  this helper is NOT called from main() or any live dispatch path"* and *"defaults OFF"*
  (line 949, line 968). That is now FALSE — it is called (486) and enabled (config 118). The
  docstring is misleading drift, but the wiring is real.
- The gate ladder is real (`harness/orchestrator_worker.py:968-996`): (1) enable flag,
  (2) `consecutive_failures >= ceiling`, (3) sensitive-target requires `approval_ok`,
  (4) re-validate the surviving code. So the owner's "operator-surfaced, not silent" requirement is
  partially honored only for sensitive targets — non-sensitive promotion is currently silent except
  for the lifecycle event at line 488.

### 1.2 The promotion ceiling can NEVER be reached. CONFIRMED — this is the real bug
This is the load-bearing finding. Trace:
- `consecutive_failures` is read from the persisted retry sidecar:
  `harness/orchestrator_worker.py:473-477` → `attempts` from
  `state/.../tasks/blocked/<id>.retry.json` **+ 1**.
- That sidecar is only bumped *between dispatches* by `_write_retry_sidecar`
  (`harness/orchestrator.py:1754 attempts += 1`, written 1756), called from `_mark_blocked`
  (`harness/orchestrator.py:1784`).
- The daemon's restage budget: `harness/autowork_daemon.py:926-928`:
  ```
  _DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed', 'embedded_tests_failed', 'narrow_fuzz_failed')
  effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts
  if attempts >= effective_max:  # 1 >= 1 -> exhausted, NOT restaged
  ```
- A `synthesis_or_ast_failed` block (emitted at `harness/orchestrator_worker.py:533`) writes
  `attempts=1`. On the next daemon sweep `attempts (1) >= effective_max (1)` → the task is marked
  `.exhausted` (lines 928-935) and **never re-dispatched**.

**Net:** within the single dispatch the sidecar still reads `attempts=0` → `consecutive_failures=1`.
`1 < ceiling(3)` → promotion refuses ("Ceiling not reached", line 972). The task then exhausts and
is gone. The ceiling of 3 is **mathematically unreachable** given a deterministic-outcome budget of
1. A valid Gemini submission is discarded because Claude mis-escaped quotes — exactly as claimed.

### 1.3 Dual-agent path requires BOTH agents AST-valid. CONFIRMED
`harness/orchestrator_worker.py:368`:
`synthesis_success = bool(agent_a_ok and agent_b_ok and agent_a_code and agent_b_code)` (retry-module
path) and `455 if not (agent_a_valid and agent_b_valid):` (main path). Promotion (1.1/1.2) is the
only escape, and it is unreachable per 1.2.

### 1.4 The nested-triple-quote synthesis fragility is STRUCTURAL. CONFIRMED
- The partial-edit prompt instructs the agent to embed reconstructed code inside an `r'''...'''`
  literal inside a Python `__JANUSMASK_PATCHES__` assignment:
  `harness/rebuild/task.py:288-293` ("submit ONE `__JANUSMASK_PATCHES__` list ...",
  `'code': r'''<your fully reconstructed ... here>'''`).
- That submission is parsed by **`ast.parse(code)`**: `harness/git_integration.py:1032-1035`. If the
  embedded `code` body contains its own triple-quotes (docstrings / nested strings) and the agent
  mis-escapes, `ast.parse` raises `SyntaxError` → `_parse_patches` returns `None` (1034-1035) → the
  whole submission is judged AST-invalid.
- **There is NO non-embedded patch format.** The patch must round-trip through a Python source
  literal; the parser keys strictly on a single top-level `Assign` to `__JANUSMASK_PATCHES__`
  (1037-1044) whose values are string `Constant`s (1056-1058). No sidecar-JSON / base64 / fenced-blob
  path exists. The quote-nesting hazard is intrinsic to the chosen wire format.

### 1.5 Gate false-rejects dominate; `missing_wiring_oracle` mis-roots external EDIT leaves. CONFIRMED
- `harness/planner/plan_validator.py:173 wd = plan.get('working_dir')` — if the draft never stamps
  `working_dir`, `wd is None`.
- `_is_module_creating(task, working_dir=wd)` resolves file existence against
  `effective_target_root(working_dir)` (`plan_validator.py:53`, `harness/paths.py:175-187`).
  `effective_target_root(None)` returns **`PROJECT_ROOT` (the JM repo)** (paths.py:181 via
  `_target_is_self(None)`).
- For an external EDIT leaf (file exists in NGv2/target but not under JM root),
  `resolved.exists()` is False (plan_validator.py:61) → returns `True` (module-creating) → triggers
  `missing_wiring_oracle` (plan_validator.py:222-243) even though the leaf only edits an existing
  external file. A textbook false-reject. Root cause: `working_dir` not stamped on the draft.
- **Partial remediation already in flight:** `git log` shows `a7f9ad1 Integrate validated code for
  strip-stray-mutation-target` (the mutation_target normalizer LANDED) and `db7a9ca` its RED oracle —
  so the `mutation_gate_error` stray-field false-reject is fixed. The working_dir-stamp fix has its
  RED oracle landed (`d2f3603 Add RED oracle: collect_agent_draft stamps brief working_dir before
  draft validation`) but **no matching "Integrate validated code" commit** — i.e. the impl has NOT
  landed. This is the "failed to land for hours" claim, confirmed by absence.

### 1.6 NGv2 34 failures are all missing-toolchain, ZERO regressions. CONFIRMED
- `/home/xnihil0zer0/NobleGreedv2/requirements.txt` PINS `z3-solver>=4.16`, `tree-sitter>=0.25`
  (+ language packs), but the interpreter has neither installed:
  `python -c "import z3"` → `ModuleNotFoundError: No module named 'z3'`;
  `python -c "import tree_sitter"` → `ModuleNotFoundError`.
- The z3 solver adapter and tree-sitter verifier are the "wired gates" from prior sessions. With the
  modules absent, those gates **cannot actually gate** — they fail/skip. Regression-prevention has
  almost nothing to protect here.

### 1.7 The bottleneck is self-demonstrating
The fix that would close 1.5 (working_dir stamp) is itself stuck behind 1.2/1.4: its RED oracle
landed but the impl keeps failing synthesis (nested-quote / budget-1). The harness is currently
unable to land the harness fix that would unblock the harness. That is the strongest possible signal
about where the leverage is.

---

## 2. Ranked ROI table of interventions

ROI ≈ (impact × breadth) ÷ cost. "Permanent?" = reusable root-cause per the owner's principle.

| # | Intervention | Impact | Breadth (task-classes unblocked) | Cost | Permanent / reusable? | ROI |
|---|---|---|---|---|---|---|
| **A** | **Align `single_agent_promotion_ceiling` with the deterministic retry budget** (set ceiling=1, OR raise `synthesis_or_ast_failed` budget so attempts can reach 3) so a lone valid agent rescues the task | **Very high** — recovers EVERY task where 1/2 agents is AST-valid; today that path is dead (1.2) | **Broad** — all synthesis tasks, internal + external, every meta_task_type | **Tiny** — config/const + one budget guard; the decision fn already exists & is wired | **Yes** — one durable rule change, applies forever | **HIGHEST** |
| **B** | **Kill the embedded-triple-quote fragility** — add a non-embedded patch wire format (separate JSON/blob sidecar for `code`, decoded outside `ast.parse`), or pre-`ast.parse` auto-repair of mis-escaped quotes | **High** — removes the single most common deterministic AST-invalid cause for large-file edits | **Broad** — every `partial_edit` / large-module leaf (the hardest, highest-value edits) | **Medium** — new format + parser path in `git_integration.py` + prompt in `task.py` | **Yes** — structural, reusable for all future partial edits | **HIGH** |
| **C** | **Eliminate gate false-rejects** — land the `working_dir` stamp (1.5); mutation_target normalizer already done | **High** — `missing_wiring_oracle` false-positive blocks ALL external EDIT leaves (the NGv2 pipeline's bread and butter) | **Broad** for external work; narrower internal | **Small** — stamp `working_dir` on the draft; RED oracle already committed | **Yes** — root-cause; reusable | **HIGH** |
| **D** | **Raise / auto-tune retry budgets** for deterministic outcomes | Medium — gives flaky/borderline tasks more shots | Broad but blunt (risks re-burning compute on truly-dead tasks) | Small | Partly — a tuning knob, not a root fix; subsumed by A for the promotion case | MED |
| **E** | **Provision the NGv2 toolchain** (`pip install z3-solver tree-sitter*`) so wired gates actually gate | Medium — turns 34 phantom fails green, lets solver/AST gates run | Narrow — NGv2 verification only; pure env/ops | Trivial | Partial — env provisioning, not code; reusable via requirements/CI but not a "harness" fix | MED |
| **F.ext** | **Provenance — EXTERNAL commit-pin + eligibility thread** (target commit SHA + eligibility flag through the artifact chain) | Medium — submission *correctness* (a PoC pinned to the wrong commit is invalid/unclaimable) | Narrow — only matters once PoCs actually land & get submitted | Medium | Yes if done as a threaded field | LOW-MED |
| **F.int** | **Provenance — INTERNAL regression-provenance** (ledger origin/date/locking-oracles, edit-prompt surfacing, test_scoper drives locking oracles) | **Low** — solves regression, but data shows ~0 regressions (1.6); 34/34 NGv2 fails are toolchain, single-agent rescue fired once in 105k log lines | Narrow — regression class is near-empty today | **High** — ledger schema + worker prompt + test_scoper changes, multi-file | Yes, but solving a near-empty problem | **LOWEST** |
| F.dedup | Provenance — early-novelty / detector-lineage dedup | Low now — you can't dedup PoCs you can't synthesize/land | Narrow | Medium | Yes | LOW |

---

## 3. Verdict on provenance's priority + which slice survives

**Provenance is not the highest-leverage investment. It is mostly a distraction from the live
bottleneck.** The evidence:

- The dominant loss mode is **pre-commit GATE/BUDGET false-rejection of good code**, not regression.
  Regression-provenance (F.int) is engineered for a problem the data says is near-empty: zero real
  regressions in NGv2 (1.6), single-agent rescue fired once in 105k lines (1.2), and that single
  rescue is *unreachable by design* — the loss is the rescue mechanism being starved, not absence of
  provenance.
- Dedup-provenance (F.dedup) and most of external provenance presuppose a working synthesis→land→
  submit pipeline. Today that pipeline stalls at synthesis (1.2/1.4) and at the planner gate (1.5).
  Provenance optimizes a stage that the work never reaches. Classic premature optimization.

**Which slice survives the ROI cut:** only the **external commit-pin + eligibility thread (F.ext)**,
and only for **submission correctness**, not dedup. Rationale: a confirmed PoC that is not pinned to
the exact target commit (and not checked against eligibility) is *invalid on submission* — that is a
correctness bug, not an optimization, and it is cheap to thread one SHA + one flag through the
artifact chain. It still ranks below A/B/C and should be done **after** the pipeline can actually
produce a landed PoC. Everything internal (F.int) should be **shelved** until a regression problem
actually exists; building it now violates the owner's "don't conflate BUILT with WORKS" principle
(you'd build green ledger plumbing that prevents a problem nobody has).

---

## 4. The one thing I'd do first

**Make the lone valid agent actually rescue the task (Intervention A).** The decision function is
already written, wired (orchestrator_worker.py:486), and enabled (config:118) — it is dead solely
because `consecutive_failures` can never reach `ceiling=3` under a deterministic-outcome budget of 1
(autowork_daemon.py:927). Fix the arithmetic so the two agree:

- Simplest permanent fix: set `single_agent_promotion_ceiling: 1` (config.yaml:121) so a single XOR
  failure with one AST-valid agent promotes within the one allotted dispatch; OR raise the
  `synthesis_or_ast_failed` deterministic budget so `attempts` can actually climb to the ceiling.
- Keep the owner's "operator-surfaced, not silent" requirement: the sensitive-target approval gate
  (orchestrator_worker.py:990) already exists; for non-sensitive promotions, emit/raise the
  promotion to the operator surface rather than only the lifecycle event at line 488.

Why first: it is a near-zero-cost, permanent, reusable root-cause change that immediately recovers
the entire "one good agent, one mis-escaped agent" class — which is *the exact failure now blocking
the working_dir-stamp fix from landing (1.7)*. Land A, and C lands itself; then B removes the
mis-escape cause at the source; then (and only then) consider F.ext for submission correctness.

**Caveat / honest counter-argument:** A is a recovery valve, not a cure — it masks the underlying
Claude-side quote mis-escape. If you only do A and never do B, you systematically promote Gemini over
Claude on large partial edits, which could skew quality. So A is the right *first* move (cheap,
unblocks now), but B must follow to fix the root cause rather than route around it.

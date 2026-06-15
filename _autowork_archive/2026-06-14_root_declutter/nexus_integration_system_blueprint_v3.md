# JanusNexus — Integration System Blueprint (v3, second-pass verified)

> **Provenance.** This is a second adversarial verification pass over
> `nexus_integration_system_blueprint.md` (**v1**, the aspirational draft) and
> `nexus_integration_system_blueprint_v2.md` (**v2**, the first correction),
> produced 2026-06-09 by four fresh parallel agents that re-read the live
> codebases (`/home/xnihil0zer0/JanusMaskJR`, `/home/xnihil0zer0/NobleGreedv2`)
> and the academic grounding in `autocompiler_research/`. **It supersedes v2.**
>
> **The headline finding: v2 was right about almost everything that matters.**
> Every existence/absence verdict in v2's reality ledger holds at `path:line`;
> the `vm.createContext` RCE blocker is real; the AlphaEvolve lineage correction
> is correct; the NGv2 `sandboxkit` architecture faithfully formalizes the
> documented project intent. v3 keeps all of that.
>
> **What v3 adds (the second-order corrections v2 itself got wrong or missed):**
> 1. v2's **AST-crossover critique is itself wrong** — the `inf`-keyed appends do
>    *not* corrupt offsets. The real §3B bugs are an unimplemented Elo-fallback and
>    non-deterministic append ordering (§2d).
> 2. v2's **parent-selection fix overshoots** — `c_elo=400` makes early exploration
>    dominate the whole Elo spread; use `c_elo≈100–200` and restore forced-first-visit (§2a).
> 3. Several real defects v2 didn't flag: a positional `Violation(...)` API mismatch,
>    more tree-sitter node-type gaps, an int/float/bool `==` collapse in containment,
>    and a SQLite double-transaction bug (§2c–2e).
> 4. **JM already ships more isolation than v2 credited** (a real libseccomp-bpf filter
>    + rlimits) — but it is **fail-open**. The right move is *harden what exists* (fix
>    fail-open, add Landlock), **not** migrate to sandlock (§3).
> 5. The JS runner has an **availability bug independent of the RCE**: its timeout can't
>    interrupt a synchronous loop and wedges the persistent worker (§3).
> 6. The NGv2 detonation⇄jail convergence has a real **network impedance mismatch** v2
>    called "verbatim": detonation PoCs often need reach to the *target*, but the jail's
>    net control is all-or-nothing (§5), and `sandboxkit.execute(language=…)` is **unbacked**
>    today — `harness/sandbox.py` runs **Python only** (§5).
>
> Two small v2 citation slips are corrected inline in §1. Net: v2 ≈ 95% correct;
> v3 closes the remaining gaps and removes one wrong fix.

---

## 0. How to read this document

- **EXISTS / ASPIRATIONAL / WRONG** verdicts and every `path:line` were re-checked
  against the live tree, not inherited from v1 or v2.
- Where v2 and v3 agree, the citation is kept terse.
- Where **this pass overturns v2**, it is flagged `⚠ CORRECTS v2`.
- Where this pass **adds** a defect v2 missed, it is flagged `+ NEW`.

---

## 1. Reality ledger — what exists today vs what is proposed

JanusMaskJR today **is** the "linear, lock-step dual-agent loop" v1 wants to replace —
that framing is accurate. The deterministic verification spine is genuinely strong; the
entire evolutionary-population "nexus" is unbuilt.

| Capability (v1 section) | Status | Evidence (corrected) |
| --- | --- | --- |
| `harness/ast_enforcer.py` — `Violation` (`@dataclass`), `_ValidationVisitor`, `validate_code` | **EXISTS** | `ast_enforcer.py:14` `@dataclass`/`:15` `Violation`; `:25` `_ValidationVisitor`; `:187` `validate_code` |
| `harness/diff_fuzzer.py` — Hypothesis differential fuzzer + corpora | **EXISTS** | `diff_fuzzer.py:24` hypothesis import; **`:67` `_AST_STMT_CORPUS`, `:113` `_PATH_CORPUS`** (⚠ v2 paired these line numbers in reverse) |
| `harness/test_author.py` — `stub_for` mutant + non-vacuity + ref-verification + adversarial critic (v1 §9A) | **EXISTS — more complete than v2 said** | `:49` `stub_for`; `:58` `run_oracle_against`; `:101` `oracle_is_non_vacuous`; `:221` `author_oracle`; ref-verify gate `:264`; critic-review loop `:280`+re-validation `:335` |
| Python-`ast` symbol patching (the "lock-step" baseline) | **EXISTS** | **`harness/git_integration.py:103`** `_ast_merge`; `:1070` `_apply_symbol_patch` (⚠ v2 wrote the path as repo-root `git_integration.py`) |
| `harness/agent_jail.py` bwrap jail (`build_jail_argv`, `--unshare-net`, `bind_credentials=False`), **fail-closed** | **EXISTS** | `agent_jail.py:65` `build_jail_argv`; `:97-102` fail-closed (`bwrap` missing → `FileNotFoundError`); `:129-130` `--unshare-net --unshare-ipc` *when `bind_credentials=False`*; `:319` ro-bind repo |
| `harness/sandbox.py` Python sandboxed execution + **real seccomp-bpf + rlimits** + `sandbox_child_env` seam | **EXISTS (Python-only)** | `:115` `sandbox_child_env`; `:75` `ExecutionResult`; `:652-715` libseccomp-bpf filter; `:192-203` rlimits; `:1315` `Sandbox.execute`; `:1497` `BatchRunner.execute_batch` |
| `autocompiler_research/distill_harness_rules.py` + synthesized checker + 4 addenda | **EXISTS as files; TOY DEMO only** | hardcoded rich/ablated strings `:104-121`; **0 importers** repo-wide |
| §2 Population DB / `sketches`/`matches`/`matchmaker_queue` / Elo / P-UCB / rater tournament | **ASPIRATIONAL (0% built)** | grep `matchmaker\|population.db\|elo_rating\|p_ucb\|sketch` → **0 hits** |
| §3/§5 Tree-sitter crossover + JS/TS queries + `node_runner.js` JS bridge | **ASPIRATIONAL** | `tree_sitter` not in `.venv` nor `venv`, not in `requirements.txt`; no `node_runner.js`; **`sandbox.py` executes Python only** (no `node`/JS path anywhere) |
| §9B deterministic sandbox (`sitecustomize.py`, `LD_PRELOAD`/`libdeterminism.so`) | **ASPIRATIONAL** | only the `sandbox_child_env` env-injection seam exists (thread-pins + `PYTHONHASHSEED=0`); grep `sitecustomize\|LD_PRELOAD\|libdeterminism` → 0 hits |
| §8 "distilled rules feed the validation flow / append to `ast_enforcer.py`" | **FALSE as written** | the prototype is isolated; no harness module imports it |

**Independent "% built" estimate:** ~25–30% of the verify/fuzz/test-author substrate, 0%
of the evolutionary-population vision. v2's "≈20–25%" is right, arguably slightly low,
because `test_author.py` already ships the full §9A adversarial-oracle loop. **The single
biggest unbuilt leap** is the closed-loop evolutionary/self-distilling layer (population DB
+ matchmaker + selection + a *live* trace-diff that actually feeds synthesized rules back
into validation). Today JM is a strong **one-shot gated builder**; the "nexus" premise is
the missing ~70%.

**Process reality (governs all of §2–§5):** JanusMask's own rule — verified in code —
requires that **every `harness/**` change land through the gated `harness_self_fix`
pipeline with a hand-authored RED oracle and an operator decision file, never a hand-edit.**
Evidence: `git_integration.py:82` (auto-commit only when `meta_task_type=='harness_self_fix'`
and approval present); `orchestrator.py:2286` `_NEVER_AUTO_APPROVE` deny-list (includes
`git_integration.py`, `orchestrator.py`, `agent_jail.py`, `sandbox.py`'s siblings, `services/**`);
`control_gate.py:121` decision-file gate. Every correction below is therefore **one or more
oracle-first gated leaves**, not a `make` run.

---

## 2. Corrected conceptual framing & technical specifications

### 2.0 Lineage: this is AlphaEvolve, not "AlphaProof Nexus" (v2 — upheld)

There is **no DeepMind system named "AlphaProof Nexus."** v1 fused the project's own
"Nexus" branding onto a DeepMind name for authority:

- **AlphaProof** — formal *theorem proving* in Lean (RL + autoformalization). No code-patch
  population, no Elo tournament, no AST crossover. Citing it for this design is wrong on
  every mechanism.
- **AlphaEvolve** — the actual ancestor: an evolutionary coding agent with a **population of
  programs**, LLM mutate/recombine, **automated fitness functions**, parent selection. v1's
  population DB, parent selection, crossover, and fitness loop are AlphaEvolve-shaped.
- The pairwise **Elo-arena** motif is closer to **LLM-judge arenas** (Chatbot Arena) than to
  anything in AlphaProof — and note AlphaEvolve itself scores with *automated programmatic*
  fitness, **not** an LLM-judge Elo. v1's Elo tournament is a hybrid that is neither.

**Action:** rename to AlphaEvolve, cite it, drop "AlphaProof Nexus."

### 2.0b Is population + Elo the right tool? Match the tool to the *fitness landscape* (v2 — upheld, sharpened)

v2's core argument is sound: JanusNexus's job is **correctness-to-a-spec** (pass the
oracle/tests), a **decision/SAT problem** with a **cliff** fitness landscape (pass or fail),
not a gradient-optimization problem. Population/Elo/crossover is gradient-climbing machinery
that adds little to clearing a binary gate, and crossing two *failing* candidates has no
principled reason to yield a passer.

**Sharpening (the discriminator v2 oversimplified):** AlphaEvolve did **not** restrict
itself to soft "performance tuning" — it improved correctness-bearing, verifiable algorithms
(e.g. matrix-multiplication tensor decompositions, scheduling heuristics). The real
discriminator for *keeping the evolutionary apparatus* is **whether fitness is a graded,
automatically-computable real number with headroom**, not "performance vs correctness." And
the part that is genuinely weakest here is specifically the **LLM-judge Elo** layer — LLM
pairwise judgments are non-transitive and position-biased, violating Elo's latent-skill
assumption — *not* population search per se.

**Recommendation (refined):**
- **Correctness-gated path:** parallel **best-of-N generation + the automated oracle/fuzz
  gate + keep survivors.** Captures most of AlphaEvolve's benefit (diverse parallel attempts,
  automated fitness) with none of the DB/Elo/crossover/matchmaker surface.
- **Diff-minimality:** compute **deterministically** (changed bytes / AST nodes) + one lint
  pass. No tournament.
- **Reserve population + selection + crossover** for sub-problems that expose a **graded
  automated fitness with headroom** (perf, algorithmic search) — and even there, prefer a
  programmatic fitness over an **LLM-judge** Elo.

This dissolves most of v1's highest-risk unbuilt surface and is far more compatible with the
gated-self-fix landing constraint.

### 2a. CRITICAL — parent selection is dimensionally broken; v2's fix is right in *shape*, wrong in *constant* `⚠ CORRECTS v2`

v1's `select_parent_p_ucb` adds **raw Elo** (~1000–1600) to a bonus
`2·sqrt(ln N / nᵢ)` that is **≈4.3 at N=100,nᵢ=1** (arithmetic verified: `2·√(ln100/1)=4.29`).
Exploration is ~0.3% of the score → the argmax never flips → **degenerates to greedy.** As
written it is **not evolutionary**, and it is **not P-UCB** (no policy-prior term; it's UCB1
misnamed). v2 is correct on all of this.

**But v2's proposed `c_elo=400` overshoots.** With `bonus = 400·√(ln N / (n+1))`:
`n=0,N=100 → 859`; `n=1 → 608`; `n=10 → 259`. An **859-Elo** bonus is *larger than the entire
spread* between best and worst sketches (~400–600 Elo), so for the first several selections
exploration **dominates** rating entirely — it inverts v1's bug into near-pure
round-robin. Also, swapping v1's `ln N / nᵢ` for `n+1` in the denominator **drops UCB1's
forced-first-visit guarantee** (n=0 no longer yields an unbounded bonus), so a low-Elo novel
sketch can be starved.

**Corrected fix:**

```python
import math

def select_parent_ucb_over_elo(sketches, c_elo: float = 150.0):
    """UCB1 with the exploit term in Elo units.
    c_elo ≈ 100–200 puts the exploration bonus at ~1 rating std-dev (NOT 4×, which
    is what c_elo=400 does). Untried sketches (n==0) get a forced first visit so we
    keep UCB1's 'try every arm once' property. To earn the 'P-', multiply `bonus`
    by a policy prior P(s) (LLM promise score / source-agent weight)."""
    N = sum(s["selection_count"] for s in sketches) + 1
    def score(s):
        n = s["selection_count"]
        if n == 0:
            return float("inf")                      # forced first visit (UCB1)
        return s["elo_rating"] + c_elo * math.sqrt(math.log(N) / n)
    return max(sketches, key=score)
```

Also note (neither v1 nor v2 caught): `selection_count` rises at **selection** time while
Elo only updates after a **match** completes, so a selected-but-unrated sketch's count grows
against a stale rating — document/decouple the update timing. *(If §2.0b is adopted, this
whole mechanism is reserved for the graded-fitness sub-problem, off the correctness path.)*

### 2b. CRITICAL — `vm.createContext` is NOT a security sandbox (v2 — upheld) + the timeout wedge `+ NEW`

Node's `vm` isolates *globals*, **not** a security boundary (Node's own docs say so).
The escape is real and weaponizable:
`this.constructor.constructor('return process')()` reaches the host realm's `process`, then
`process.mainModule.require('child_process').execSync(...)` → full RCE. Omitting
`require`/`process` from the context object does nothing (the leak is the `Function`
constructor / prototype chain). `unshare -n -r` blocks **only** network (no FS/PID/mount/CPU
confinement; `-r` only maps a userns root so `-n` is permitted unprivileged);
`--max-old-space-size` caps **only** V8 old-space heap (not new-space, ArrayBuffers, native
allocs, CPU, fds, or processes). Running adversarial PoCs/fuzz candidates here is RCE.

`+ NEW` **availability bug, independent of the RCE:** v1's timeout uses
`Promise.race([target(...), setTimeout(reject)])`. A synchronous busy-loop (`while(true){}`)
never yields to the microtask queue, so the timeout **never fires** and the **persistent
worker wedges** — taking the whole batch with it. The only robust JS timeout is a hard
parent-side **wall-clock kill of the worker process** (and/or `vm`'s synchronous `{timeout}`
option where applicable).

**Fix (mandatory before any untrusted-JS path):** do **not** use `vm` for untrusted code.
Layer two distinct tiers (they are *not* interchangeable):
1. **OS boundary (mandatory):** run `node` under the **same bwrap jail** the Python side uses
   — `agent_jail.build_jail_argv(bind_credentials=False)` (ro-bind rootfs, tmpfs work dir,
   `--unshare-net`) **plus the existing seccomp filter plus rlimits** — and a hard parent-side
   process kill for timeout.
2. **In-process defense-in-depth:** `isolated-vm` (a true V8 isolate; closes the language-level
   escape but does *not* sever FS/syscalls on its own).
Prove parity with a **red-team escape test** (assert `this.constructor.constructor('return
process')()` and `child_process` are unreachable, and that a sync infinite loop is killed).
"Same safety as the Python sandbox" is a requirement to be **proven, not asserted.** Also
note: `unshare -r` (rootless userns) may be **disabled** on some hosts
(`kernel.unprivileged_userns_clone=0`) — the path must **fail closed** there, never fall back
to an un-jailed `node`.

### 2c. HIGH — anti-stub rule is a false-positive generator (v2 — upheld) + a `Violation` API mismatch `+ NEW`

`_is_static_primitive_return` flags **any** function with ≥1 non-`self`/`cls` param whose
single statement returns a constant **or** `None`. That condemns legitimate code: `return
None` (the most common valid body), predicates, feature-flag accessors, `__hash__`, sentinel
validators. The empty-body and `raise NotImplementedError` detectors are fine as errors.

`+ NEW` v1's snippet constructs `Violation('stub_detected', 'error', node.lineno, msg)`
**positionally**, but the real dataclass (`ast_enforcer.py:14`) is used keyword-style
(`Violation(rule=…, severity=…, line=…, message=…)`) — the blueprint's positional call is an
**API mismatch** a v3 implementation must fix regardless of the false-positive question. (Also:
the visitor ignores `*args`/`**kwargs`-only signatures, an inconsistency.)

**Fix:** demote static-return `stub_detected` from hard `error` to **warning**, and let the
**oracle be ground truth** (a real stub fails the test). If kept as a gate, require (a) exclude
`return None`, (b) exclude single-param predicates, (c) only flag when the returned constant
trivially satisfies a *known asserted* value. Fix the `Violation(...)` constructor call.

### 2d. AST crossover — v2's offset critique is WRONG; the real bugs are elsewhere `⚠ CORRECTS v2`

v2 said "process new-symbol appends in a separate pass; don't rely on the `inf` sort key
because it corrupts offsets." **Traced and refuted:** new-symbol edits sort *first* (largest
key, `reverse=True`) and are applied via `result.extend(...)`, which appends at the **tail**;
every in-place splice (`result[sb:eb]=…`) operates strictly *before* those tail bytes. The
trailing appends therefore **do not shift any in-place index.** The algorithm is offset-safe;
v2's "corruption" claim is incorrect. (Processing appends in a separate pass is fine as
*clarity* hygiene, but it fixes no bug.)

**The genuine §3B defects (both missed by v2):**
1. **Unimplemented Elo-fallback.** The conflict branch's comment says "Fallback to Elo
   Selection: choose changes from the higher-rated parent," but the code immediately
   `raise ValueError(...)`. Any symbol *both* parents touched aborts crossover entirely — the
   exact failure §2.0b warns about. Implement the documented fallback or delete the comment.
2. **Non-deterministic append order.** New symbols all tie at sort key `inf`; Python's stable
   sort then preserves **set-iteration order** (`mod_a`/`mod_b` are sets), which varies across
   runs → **non-reproducible** crossover output. Sort new symbols by a stable key (name).
3. **Keep the cheap compile/oracle gate downstream:** name-disjoint ≠ semantically composable;
   a spliced child neither parent represents must still clear the oracle (v2 — correct).

### 2e. Tree-sitter / containment / concurrency correctness (v2 — upheld, with additions)

- **§3A/§5A JS query bug (v2 — upheld):** `(class_definition …)` / `(function_definition …)`
  are **Python** tree-sitter nodes; JS/TS use `class_declaration` and `function_declaration`,
  so v1's JS class extraction silently matches nothing.
  `+ NEW` v2 missed further gaps: arrow-function **class fields** (`public_field_definition` /
  `field_definition`, e.g. `foo = () => {}`), `function_expression` assignments
  (`const f = function(){}`), and TS interface/abstract `method_signature`; §5A's param query
  covers only `function_declaration`, so arrow-fn and method params aren't extracted at all.
  Enumerate the full node set per grammar.
- **§3 premise (v2 — upheld):** tree-sitter is **not installed** and JM has **no** existing
  tree-sitter merge — frame the CST pivot as net-new, and **pin one parser authoritative for
  symbol byte ranges** (tree-sitter byte ranges vs Python-`ast` containment can disagree).
- **§4B containment (v2 — partly corrected):** placeholder indent must derive from the first
  *code* line inside the range, not the START-comment line (v2 — correct).
  `⚠ CORRECTS v2`: v2's **NaN** concern is essentially **unreachable** here (there is no `nan`
  source literal; `float('nan')` parses to a `Call`, not a `Constant`). The **real**
  value-comparison defect is the Python **int/float/bool `==` collapse**: `compare_ast_nodes`
  compares `ast.Constant.value` with `!=`, so `return 1`, `return 1.0`, and `return True`
  compare **equal** — a false-negative for value-type changes. Prefer canonical
  `ast.dump(t, include_attributes=False)` comparison, which sidesteps both the hand-rolled
  recursion and the `==` collapse.
- **§2B/§6 SQLite (v2 — upheld, plus one v2 missed):** open `dequeue_match` with
  `isolation_level=None` so the explicit `BEGIN IMMEDIATE` is unambiguous (matches §6);
  `+ NEW` v1's §2B *also* nests the explicit `BEGIN IMMEDIATE` inside `with conn:`, which is
  itself a transaction context manager → **double transaction management** (can raise on
  block exit) — drop one or the other. On fork, **`close()` the inherited fd before**
  discarding the thread-local (a dropped-but-open WAL fd can corrupt the DB); wrap `ROLLBACK`
  in its own try/except (rolling back with no active txn raises and masks the original error);
  `journal_mode=WAL` is **DB-level/persistent**, not a per-connection pragma.
- **§2C Elo math (v2 — upheld):** correct (`E_a+E_b=1`, FIDE-style provisional K decay,
  `new=old+K·(score−expected)`). Keep full precision internally; round only for display.

---

## 3. Sandboxing & determinism — harden what exists, don't rebuild it

This pass found **JM already ships more isolation than v2 credited**, which *strengthens*
v2's "reuse the Python jail for JS" recommendation.

**What exists today (verified):**
- **bwrap jail** (`agent_jail.py`): ro-bind rootfs, tmpfs work dir, `--unshare-net --unshare-ipc`
  on the untrusted path, credential-strip via `bind_credentials=False`, **fail-closed** when
  `bwrap` is missing.
- **In-process seccomp-bpf filter** (`sandbox.py:652-715`): blocks
  `socket/connect/bind/listen/accept/execve/fork/vfork` + threaded `clone`/`clone3`, default
  on (`SandboxConfig.seccomp=True`).
- **rlimits** (`RLIMIT_AS/CPU/STACK/NPROC`) and `PYTHONHASHSEED=0` + thread-pinning via
  `sandbox_child_env`.

**Two real gaps to fix (oracle-first, gated):**
1. `+ NEW` **The seccomp filter is FAIL-OPEN.** `_init_seccomp_globals` silently `return`s if
   `find_library("seccomp")` is None (`sandbox.py:657-659`); `_install_seccomp` no-ops if the
   context didn't set up (`:685-686`). On a host without libseccomp, untrusted Python runs
   **unfiltered and silently** — the opposite of the jail's commendable fail-closed posture.
   Make it **fail-closed** (refuse to run untrusted code without a filter), or at minimum
   loudly degrade.
2. **No Landlock FS confinement on the in-process execute path** — it leans on bwrap mount
   namespaces. Add **Landlock** (the cheap, unprivileged FS-allowlist primitive from the
   sandlock research) under the existing jail.

**bwrap vs sandlock — recommendation:** **stay on bwrap+seccomp+rlimits and add Landlock;
do NOT migrate to sandlock.** JM already has bwrap-class isolation; sandlock is Rust,
arXiv-fresh (May 2026), and brings its own `BranchFS`/usernotify supervisor — a large new
dependency + failure domain for a ~5 ms/fork startup win JM doesn't bottleneck on (JM's cost
is the LLM turn). Adopt sandlock's **principles** (kernel-enforced, fail-closed,
capability-separated, default-deny net, Landlock allowlist), not its codebase.

**Determinism layer (§9B) — keep as a *flakiness* tool, never a *security* control.** The
`addendum_sandbox_determinism.md` design is unusually honest about its limits and is
**complementary** to the kernel boundary, not a substitute. Real caveats for v3:
- `LD_PRELOAD`/`libdeterminism.so` is **inert** for statically-linked Go/Rust binaries and
  direct `syscall` instructions — exactly the cases it nominally targets. Only the kernel
  (seccomp/Landlock) closes those.
- The **virtual clock** can decouple from real resource enforcement: mocked `time.monotonic`
  must not let in-candidate self-limiting loops spin past the parent CPU rlimit, and oracles
  that *measure* time will assert against fiction.
- `sitecustomize.py` only loads if the work dir is on `sys.path` and `-I`/`-S` isn't in play —
  an unstated precondition; `socket`-mock and `id()`-override are bypassable (raw `_socket`,
  C-level `id`), so they are belt-and-suspenders to the kernel net-sever, not a boundary.

**Makefile (§7) — fix the self-defeating masks:** `PYTHON := venv/bin/python` points at a
**non-existent** binary (the live interpreter is **`.venv/bin/python`**; a stray `venv/lib`
makes the bug look plausible). `build-tree-sitter` asserts importing `tree_sitter_*` which
**fails today**. `cd webui && npm install || true` and `lint … || echo` **swallow failures** —
indefensible for a system whose premise is deterministic gating. Fix the venv path, drop the
`|| true`/`|| echo` masks, make tree-sitter **optional** until the multi-language path is real.

---

## 4. Harness Distillation — keep the prototype, fix the claim (v2 — upheld)

`autocompiler_research/distill_harness_rules.py` + the four addendum docs are **real files**
and the prototype **runs** — but as a **self-contained toy demo** over hardcoded rich/ablated
strings, with **zero importers** in the harness. v1 §8's claim that compiled rules are "stored
into the workspace's validation flow / appended to `ast_enforcer.py`" is **false today.**

**Corrected scope:**
- §9A's double-directional gating (ref-verify + non-vacuity mutant + adversarial critic) is the
  **one advanced layer already built** — and more completely than v2 credited
  (`test_author.py` ships all three gates + a re-validation loop).
- Treat distillation (§8), the determinism layer (§9B), constrained decoding (§9C), and
  loop-invariants (§9D) as **proposals**. Each needs: (1) a **live differential-trace harness**
  (run real tasks under rich vs ablated metadata — *not* hardcoded strings), then (2) a gated
  `harness_self_fix` leaf with a RED oracle to wire the synthesized checker into
  `ast_enforcer.validate_code` / `diff_fuzzer` corpora. Until that wiring exists, the prototype
  is a research spike, not a feature.

---

## 5. NobleGreedv2 ⇄ JanusNexus — the integration architecture (v2 — upheld, two mismatches corrected)

v2's §5 is the newest, least-reviewed section. This pass **confirms its core architecture and
its alignment with documented project intent**, and corrects two understated impedance points.

### 5a. The recommendation (upheld): share the node, not the loop

The two systems share **exactly one node** — NGv2's detonation `runner`:
- **JanusNexus loop:** evolutionary *build* (select → crossover/mutate → AST/anti-stub gates →
  (population) → **git commit**). Unit: a *sketch*; success: passes tests / commits.
- **NGv2 loop:** linear *hunt* (`hunt → triage → poc → detonate → report → done` over a
  `HuntStateMachine`). Unit: a *Finding/PoC*; success: a per-PoC **verdict**. No population,
  no tournament, no commit.

Forcing NGv2's hunt loop through JanusNexus's task/commit pipeline is a category error (a
Finding is not a committable sketch; a verdict is not a tournament win). **This matches the
documented intent verbatim** — MEMORY: "HARVEST JM jail+detonation; NGv2 runtime does the
dangerous detonation later, **sidestepping JM's eval/exec+mutation+commit impedance**." So:
**keep the loops separate; share the detonation node** through a stable facade. *(Open item the
intent records but §5 doesn't yet cover: the memory also wants JM's **hooks + daemon** harvested
— out of scope for the narrow node-sharing facade, noted as future work, not a contradiction.)*

### 5b. The convergence is real — with a network carve-out v2 called "verbatim" `⚠ CORRECTS v2`

Verified at `path:line`:
- NGv2 detonation is one injected callable: `ngv2/pipeline.py:12` `run_pipeline(handlers, *,
  success_marker='VULNERABLE')`, runner called at `:36` with the **exact** 4-tuple contract
  `runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms)` (`detonation.py:17`,
  `poc_runner.py:12`).
- `DetonationChamber.detonate` (`detonation.py:15-26`) maps outcome → verdict; the **only**
  NGv2-specific knob is `success_marker`. **Exact mapping** (v2's prose flattened this):
  `exit_code==0 AND marker in stdout → 'confirmed'`; `exit_code not in (0, None) → 'refuted'`;
  **else → `'inconclusive'`** (a zero/None exit *without* the marker is inconclusive, **not**
  refuted); runner raises → `'error'`.
- NGv2 ships **only** mock runners (`poc_runner.py` `make_mock_runner`/`make_scripted_runner`);
  the real subprocess/bwrap runner is an **intentional injection hole**. `PoC` fields
  (`contracts.py:42-47`: `finding_id`, `language`, `code`, `entrypoint`) **exist with the exact
  names** v2's adapter uses — the 5e snippet is field-correct.

`⚠ CORRECTS v2` **The threat models are close but NOT "verbatim."** The agent jail's untrusted
path uses `--unshare-net` (`agent_jail.py:130`) — it severs **ALL** network as the load-bearing
exfil control. But a detonation PoC frequently must reach the **target** it exploits (a service,
an endpoint). The jail is **binary** (`--share-net` with credentials, or `--unshare-net`
without) with **no target-only carve-out**. So:
- **Local/file-based PoCs** (e.g. NGv2's model-file deserialization exploits) → `--unshare-net`
  is a perfect fit; convergence holds.
- **Network-reaching PoCs** → `build_jail_argv(bind_credentials=False)` would sever the reach the
  PoC needs. The facade must add an explicit, **default-deny, target-scoped** network carve-out
  (allow *only* the target endpoint, nothing else) — this is net-new, not inherited.

### 5c. Boundary: a JanusNexus-owned `sandboxkit` facade (v2 — upheld; import closure verified)

Verified: the facade is a genuine **leaf**, not a tendril. `agent_jail.py` is **stdlib-only**;
`agent_streamer.py` stdlib-only; `harness/sandbox.py`'s only intra-harness import is a **lazy**
`from harness.paths import _target_is_self` and `paths.py` is stdlib-only — so a facade over
**sandbox + jail** drags in **no** config/orchestrator. (Caveat: `sandbox_smoke.py` *does* have a
lazy `from harness.orchestrator import load_config` — so **do not** fold `sandbox_smoke` into the
facade; wrap sandbox+jail only.) NGv2 imports `sandboxkit`, **never** `harness.*` directly;
JanusNexus is upstream/owner, NGv2 downstream-only.

**Surface — annotated for what is real-today vs aspirational `⚠ CORRECTS v2`:**

```python
# sandboxkit — the ONLY surface NGv2 may import from JanusNexus.

@dataclass
class ExecResult:                 # frozen mirror of harness ExecutionResult
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    return_repr: str = ""

def execute(code: str, entrypoint: str, inputs: list[dict], *,
            language: str = "python",   # ⚠ "python" REAL today; "javascript"/"typescript"
                                        #    ASPIRATIONAL — sandbox.py executes Python ONLY,
                                        #    no node/JS backend exists (gated on §2b + node bridge)
            timeout_ms: int = 5000,     # REAL  (SandboxConfig.timeout_per_input_ms)
            memory_limit_mb: int = 256, # REAL  (RLIMIT_AS)
            network: bool = False,      # PARTIAL — backed by agent_jail --unshare-net, but BINARY
                                        #    (all-or-nothing); target-scoped carve-out is net-new (§5b)
            deterministic: bool = True  # NARROW — today only PYTHONHASHSEED + thread-pinning;
                                        #    full determinism layer (§9B) is unbuilt
            ) -> list[ExecResult]: ...

def spawn_agent(argv, *, repo_root, work_dir, state_dir,
                bind_credentials: bool = True, network: bool = True) -> "AgentResult":
    """Backed by agent_jail.build_jail_argv + agent_streamer (both real today)."""
```

Everything population/Elo/crossover/commit stays **out** of the facade.

### 5d. Minimal first step (proves the boundary, one new file, zero loop changes)

Implement NGv2's real detonation `runner` as a thin adapter over `sandboxkit.execute`,
exploiting the already-injectable seam:

```python
# ngv2/sandbox_runner.py  (NEW — the real runner; swaps in for make_mock_runner in prod)
from sandboxkit import execute
from ngv2.contracts import PoC

def make_janusnexus_runner(*, timeout_ms: int = 5000):
    def runner(poc: PoC, target_spec) -> tuple:
        r = execute(code=poc.code, entrypoint=poc.entrypoint,
                    inputs=[{"args": [target_spec]}], language=poc.language,
                    timeout_ms=timeout_ms, network=False, deterministic=True)[0]
        return (r.exit_code, r.stdout, r.stderr, r.duration_ms)   # canonical 4-tuple
    return runner
```

`build_handlers(runner=make_janusnexus_runner())` swaps the mock for the real one; every
existing mock-injecting test keeps working. It is **gated and reversible** (default-OFF until
`sandboxkit.execute` exists; flipping is a one-line handler change — matching JM's
default-OFF-then-flip posture). **First validation:** detonate one known-`VULNERABLE`
**Python** PoC and assert `DetonationChamber` returns `verdict == 'confirmed'`. **Do not**
validate a JS PoC yet — the JS backend is unbuilt and gated on §2b.

### 5e. Sequencing

1. **Freeze the `sandboxkit` contract** (`ExecResult` + `execute()` signature) — interface only.
2. **Land `sandboxkit.execute` in JanusNexus** as a non-breaking wrapper over today's
   `Sandbox.execute`/`BatchRunner.execute_batch` — **Python only.**
3. **NGv2 `ngv2/sandbox_runner.py`** (5d) behind a default-OFF flag — proves the boundary
   end-to-end for Python.
4. **Add the target-scoped network carve-out** (§5b) before any network-reaching PoC.
5. **JS/TS detonation** onto the persistent node bridge — **only after §2b is resolved**
   (OS-jailed `node` + seccomp + rlimits + hard-kill timeout); behind the same
   `execute(language="javascript")`; NGv2 code unchanged.
6. **Optional / future:** route NGv2 hunt/triage *agent* spawns through `sandboxkit.spawn_agent`
   to retire duplicate jail code; harvest JM hooks/daemon (the intent's remaining items).

---

## 6. Landing order & process constraints

1. **Do not call it "evolutionary"** until §2a is fixed (today it's greedy).
2. **Do not enable any JS execution path** until §2b is resolved (RCE + sync-timeout wedge).
3. **Harden the existing sandbox** (fail-open seccomp → fail-closed; add Landlock) before
   widening the untrusted surface.
4. **Every `harness/**` change is a gated `harness_self_fix` leaf** — RED oracle + operator
   decision file, **never a hand-edit**. There is no "just run `make`" path; budget for many
   oracle-first leaves.
5. Pin `gemini-3.0-flash` (a forward-dated id) to a **verified-available** model and make it
   configurable; the LLM-judge rater is the **lowest-value** component (§2.0b) — prefer
   programmatic fitness.

---

## 7. Verification provenance

Compiled from a **second** four-agent adversarial pass (2026-06-09), each reading the real
repos and the `autocompiler_research/` papers, cross-checking **both v1 and v2** against ground
truth:
1. **Existence / reality-ledger audit** — confirmed v2's §0 verdicts; caught v2's two citation
   slips (`harness/git_integration.py` path; reversed corpus line numbers); independently
   estimated ~25–30% built.
2. **Algorithmic & conceptual soundness** — confirmed the P-UCB degeneration arithmetic; **found
   v2's `c_elo=400` overshoots** and **v2's splice offset-corruption claim is wrong**; surfaced
   the `Violation` API mismatch, the int/float/bool `==` collapse, more tree-sitter node gaps,
   and the SQLite double-transaction.
3. **Security / sandbox / determinism** — confirmed the `vm` RCE and "nothing of §9B is built";
   **found JM already ships a (fail-open) seccomp filter + rlimits**, the JS sync-timeout wedge,
   and recommended bwrap+Landlock over a sandlock migration.
4. **NGv2 ⇄ JanusNexus** — confirmed every §5 `path:line` and the intent-alignment; **found the
   network threat-model carve-out** v2 called "verbatim" and that `sandboxkit.execute(language=…)`
   is **unbacked** (Python-only sandbox) today.

Every "EXISTS/ASPIRATIONAL/WRONG", every `⚠ CORRECTS v2`, and every `+ NEW` in this document was
checked against the live codebase, not inferred from v1 or v2.

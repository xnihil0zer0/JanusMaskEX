# JanusNexus — Integration System Blueprint (v2, verified & corrected)

> **Provenance.** This is a fact-checked, adversarially-reviewed rewrite of
> `nexus_integration_system_blueprint.md`, produced 2026-06-09 by four parallel
> verification agents that read the actual codebase (`/home/xnihil0zer0/JanusMaskJR`,
> `/home/xnihil0zer0/NobleGreedv2`) and pressure-tested every claim, snippet, and
> framing. **It supersedes v1.** v1 is a useful design sketch but repeatedly conflates
> "designed (as a doc/prototype file)" with "built into the harness," misattributes its
> intellectual lineage, and contains a load-bearing algorithmic bug and a critical
> sandbox-security flaw. Where v1 was right, this version keeps it and says so; where it
> was wrong, this version corrects it and cites the evidence.
>
> **What changed at a glance:**
> 1. Re-grounded "exists vs proposed" (v1 ≈ 20–25% built; §0 ledger).
> 2. Corrected lineage: this is **AlphaEvolve**, not "AlphaProof Nexus."
> 3. Fixed the **dimensionally-broken parent selection** (v1 §2D degenerates to greedy).
> 4. Flagged **`vm.createContext` as a non-sandbox** (RCE) and the anti-stub rule as a
>    false-positive generator.
> 5. Re-scoped the search: for a **correctness-to-spec** engine, parallel best-of-N +
>    deterministic scoring beats the Elo/crossover apparatus; reserve population/Elo for
>    genuinely open-ended sub-problems.
> 6. Added the **NobleGreedv2 ⇄ JanusNexus integration architecture** (§5) — the
>    `sandboxkit` facade and the detonation≈sandboxed-execution convergence.

---

## 0. Reality ledger — what exists today vs what is proposed

JanusMaskJR today **is** the "linear, lock-step dual-agent loop" v1 wants to replace — that framing is accurate. The table below is the honest foundation for everything downstream.

| Capability (v1 section) | Status | Evidence |
| --- | --- | --- |
| `harness/ast_enforcer.py` + `Violation` dataclass + `NodeVisitor` enforcers (`validate_code`) | **EXISTS** | `ast_enforcer.py:14` `Violation`; `:25` `_ValidationVisitor`; `:187` `validate_code` |
| `harness/diff_fuzzer.py` — Hypothesis differential fuzzer + `_PATH_CORPUS`/`_AST_STMT_CORPUS` | **EXISTS** | `diff_fuzzer.py:24` hypothesis import; `:67`/`:113` corpora |
| `harness/test_author.py` — `stub_for` mutant + non-vacuity + ref-verification + adversarial critic (v1 §9A) | **EXISTS (largely built already)** | `test_author.py:49` `stub_for`; `:58` `run_oracle_against`; `:101` `oracle_is_non_vacuous`; `:221` `author_oracle` |
| Python-`ast` symbol patching (the "lock-step" baseline) | **EXISTS** | `git_integration.py:103` `_ast_merge`; `:1070` `_apply_symbol_patch` |
| `harness/agent_jail.py` bwrap jail (`build_jail_argv`, `--unshare-net`, `bind_credentials=False`) | **EXISTS** | `agent_jail.py:65` `build_jail_argv`; `:125-138` ro-bind + cred-strip + net-sever |
| `harness/sandbox.py` Python sandboxed execution + `sandbox_child_env` seam | **EXISTS** | `sandbox.py:115` `sandbox_child_env`; `Sandbox.execute`; `BatchRunner.execute_batch` |
| `autocompiler_research/distill_harness_rules.py` + synthesized checker + 4 addendum docs | **EXISTS as files** (prototype runs as a **toy demo** only) | files present; `__main__` uses hardcoded rich/ablated strings, **not** a live trace-diff |
| §2 Population DB / `sketches`/`matches`/`matchmaker_queue` / Elo / P-UCB / rater tournament | **ASPIRATIONAL (0% built)** | `grep matchmaker\|population.db\|elo_rating\|p_ucb` → zero hits |
| §3/§5 Tree-sitter crossover + JS/TS queries + `node_runner.js` JS bridge | **ASPIRATIONAL** | `tree_sitter` **not installed** in any venv; not in `requirements.txt`; no `node_runner.js`; JM is Python-only at the verify/fuzz layer |
| §9B deterministic sandbox (`sitecustomize.py`, `LD_PRELOAD`/`libdeterminism.so`, virtual clock) | **ASPIRATIONAL** | only the injection seam `sandbox_child_env` exists; no sitecustomize/LD_PRELOAD anywhere |
| §8 "distilled rules feed into the validation flow / append to ast_enforcer.py" | **FALSE as written** | the prototype is isolated in `autocompiler_research/`; **no harness module imports it** |

**Net:** v1 is a *vision plus a few real foundations*, not a description of a near-built system. Plan and communicate it that way. The biggest unbuilt leaps, in order of risk: (1) the entire population-search core; (2) everything tree-sitter / multi-language (the dependency isn't even installed); (3) the deterministic-sandbox layer; (4) a real JS sandbox (see §2 security blocker).

**Process reality (applies to all of §1–§4 below):** per JanusMask's own governing rule, **every `harness/**` change must land through the gated `harness_self_fix` pipeline with a hand-authored RED oracle and an operator decision file — not a hand-edit.** v1 supplies zero oracles and treats these as direct edits. Realistically this is many gated leaves, each oracle-first. Budget for that, not for a `make` run.

---

## 1. Corrected conceptual framing

### 1a. Lineage: this is AlphaEvolve, not "AlphaProof Nexus"

There is **no DeepMind system named "AlphaProof Nexus."** v1 fuses the project's own "Nexus" branding onto a DeepMind name for authority, and conflates three unrelated systems:

- **AlphaProof** — formal *theorem proving* in Lean (RL + autoformalization). No population of code patches, no Elo tournament, no AST crossover. **Citing it for this design is wrong on every mechanism.**
- **AlphaEvolve** — *the actual ancestor*: an evolutionary coding agent that keeps a **population of programs**, uses LLMs to mutate/recombine, scores them with **automated fitness functions**, and selects parents to evolve. v1's population DB, parent selection, crossover, and fitness loop are AlphaEvolve-shaped.
- The pairwise **Elo-arena** ranking motif is closer to LLM-judge arenas (e.g. Chatbot Arena) than to anything in AlphaProof.

**Action:** rename to AlphaEvolve, cite the AlphaEvolve work, and drop "AlphaProof Nexus."

### 1b. Is population + Elo the right tool for JanusNexus's job? Mostly no — match the tool to the problem

JanusNexus's core job is **correctness-to-a-spec: pass the oracle/tests.** That is a **decision/SAT problem** with a *cliff* fitness landscape (a candidate passes or it doesn't), not an optimization problem with a gradient. Evolutionary search (population, Elo, crossover, P-UCB) is gradient-climbing machinery; it adds little to clearing a binary gate:

- Crossing over two candidates that each **fail** the oracle has no principled reason to yield a passer — their failures are usually logically independent — and v1's own crossover **falls back to "pick the higher-Elo parent" on any symbol conflict**, i.e. it abandons recombination in exactly the only case where both parents touched the relevant symbol.
- Once a candidate **passes**, the oracle is **ground truth**; an LLM pairwise Elo judge over "elegance/minimality/safety" is a softer, noisier, costlier signal layered on a hard one — and LLM pairwise judgments are **non-transitive and position-biased**, which violates Elo's latent-skill assumption outright.

**Recommendation — keep the cheap 80%, drop the ceremony:**
- For the **correctness-gated path**: use **parallel best-of-N candidate generation + the automated oracle/fuzz gate + keep the survivors.** This captures most of AlphaEvolve's benefit (diverse parallel attempts, automated fitness) with none of the DB/Elo/crossover/matchmaker surface area.
- Compute **diff-minimality deterministically** (changed bytes / AST nodes) and run a single style/lint pass — no tournament needed.
- **Reserve population + Elo + crossover for genuinely open-ended sub-problems** — e.g. performance tuning or algorithmic search where "better" is a real-valued score with headroom *among already-passing candidates*. That is where AlphaEvolve actually wins; use it there, not on the SAT gate.

This re-scoping also dissolves most of v1's highest-risk unbuilt surface (§2 population DB, matchmaker, rater pool), and is far more compatible with the gated-self-fix landing constraint.

---

## 2. Corrected technical specifications (bugs fixed, blockers flagged)

Keep v1's **real** foundations (§0 ledger). The items below are the concrete corrections to the proposed code. (Section numbers reference v1.)

### 2a. CRITICAL — parent selection is dimensionally broken (v1 §2D)

`select_parent_p_ucb` adds a **raw Elo** exploit term (~1000–1600) to an exploration bonus `2·sqrt(ln N / nᵢ)` that is **~4 points at N=100, nᵢ=1**. Exploration is ~0.3% of the score and **never changes the argmax** → the search degenerates to greedy "always pick the highest Elo." As written it is **not evolutionary**. Also it is **not P-UCB** — P-UCB weights exploration by a *policy prior* `P(child)`; there is no prior term, so this is plain UCB1-over-Elo, misnamed.

**Fix:** normalize the exploit term to a win-probability/[0,1] reward before adding the UCB bonus, **or** scale the constant to the Elo regime (the logistic Elo constant ≈ 400):

```python
def select_parent_ucb_over_elo(sketches, c_elo: float = 400.0):
    """UCB1 with the exploit term in Elo units. c_elo (~the Elo logistic
    constant) puts exploration on the same scale as rating differences, so a
    rarely-tried sketch ~1 std-dev (≈200 Elo) below the best can still be
    explored. (To earn the 'P-': multiply the bonus by a policy prior P(s)
    such as an LLM promise score or source-agent weight.)"""
    import math
    N = sum(s["selection_count"] for s in sketches) + 1
    def score(s):
        n = s["selection_count"]
        bonus = c_elo * math.sqrt(math.log(N) / (n + 1))   # +1 guards log/zero domain
        return s["elo_rating"] + bonus
    return max(sketches, key=score)
```

(If §1b is adopted, this whole mechanism is reserved for the open-ended sub-problem and is *not* on the correctness path.)

### 2b. CRITICAL — `vm.createContext` is NOT a security sandbox (v1 §5C/§5D)

Node's `vm` isolates *globals*, **not** a security boundary — Node's own docs say so. Classic escape from inside the context: `this.constructor.constructor('return process')()` reaches the real `process`, then `process.mainModule.require('child_process').execSync(...)`. Omitting `require`/`process` from the context object does nothing (prototype-chain leak). Running **adversarial/untrusted** code (PoCs, fuzz candidates) here is a **remote-code-execution risk**. And `unshare -n -r` blocks *only* the network — no filesystem confinement, no CPU/pid limits; `--max-old-space-size` caps only V8 old-space heap.

**Fix (mandatory before any untrusted-JS path is enabled):** do not use `vm` for untrusted code. Use a true isolate (`isolated-vm`) **or** run the JS under the *same* OS-level jail the Python side already has — `agent_jail.build_jail_argv` (bwrap: ro-bind rootfs, tmpfs work dir, `--unshare-net`, dropped creds) — plus seccomp/landlock + CPU/pid rlimits. Treat "same safety as the Python sandbox" as a requirement to be *proven*, not asserted.

### 2c. HIGH — anti-stub rule is a false-positive generator (v1 §4C)

`_is_static_primitive_return` flags **any** function with ≥1 non-self param whose single statement returns a constant or `None`. That condemns legitimate code: `return None` is the single most common valid function body in Python; degenerate-but-correct constant returns, predicates, feature-flag accessors, `__hash__`, etc. all trip it.

**Fix:** demote `stub_detected` for static-return from a hard `error` to a **warning**, and let the **oracle be ground truth** (a real stub fails the test). If kept as a gate, require (a) exclude `return None`, (b) exclude single-param predicates, (c) only flag when the returned constant trivially satisfies a *known* asserted value. The empty-body and `raise NotImplementedError` detectors are fine as errors.

### 2d. Tree-sitter / crossover / containment correctness (v1 §3, §4)

- **§3A JS query bug:** `(class_definition …)` is a *Python* node; JS/TS grammars use `(class_declaration name: (identifier) @class.name)`. As written, JS class extraction silently matches nothing.
- **§3 premise:** tree-sitter is **not installed** and JM has **no existing tree-sitter merge** — frame the CST pivot as net-new (and resolve the **dual-parser coherence risk**: tree-sitter byte ranges vs. Python-`ast` containment can disagree; pin one as authoritative for symbol byte ranges).
- **§3B crossover:** process new-symbol *appends* in a separate pass **after** all in-place splices; do not rely on the `inf` sort key. Name-disjoint ≠ semantically composable — keep the cheap downstream compile/oracle gate to catch crossover candidates neither parent represents.
- **§4B containment:** derive placeholder indent from the first *code* line inside the range (not the comment line) to avoid AST-altering mis-indentation; make `compare_ast_nodes` **nan-safe** (`nan != nan` yields false positives); consider canonical `ast.dump` comparison. Downgrade the prose: this is a good *coarse* containment gate, not an airtight guarantee.

### 2e. Concurrency snippets (v1 §2B, §6)

- **§2B `dequeue_match`:** open this connection with `isolation_level=None` (as §6 correctly does) so the explicit `BEGIN IMMEDIATE` is unambiguous; the two snippets currently use inconsistent connection modes for the same pattern.
- **§6 `SQLiteConnectionPool`:** (a) on fork detection, `close()` the inherited connection's fd **before** discarding the thread-local (a dropped-but-open WAL fd in the child can corrupt the DB); (b) wrap the `ROLLBACK` in its own try/except (rolling back with no active transaction raises and masks the original error); (c) note `journal_mode=WAL` is DB-level/persistent, not a per-connection pragma. Elo math (§2C) is correct; keep full precision internally, round only for display.

---

## 3. Harness Distillation — keep the prototype, fix the claim (v1 §8/§9)

The distillation prototype (`autocompiler_research/distill_harness_rules.py`) and the four addendum design docs are **real files**, and the prototype **runs** — but as a **self-contained toy demo** over hardcoded rich/ablated strings, and it is **not imported by any harness module.** The v1 claim that compiled rules are "stored directly into the workspace's validation flow / appended to `ast_enforcer.py`" is **false today.**

**Corrected scope:** §9A's double-directional gating (ref-verify + non-vacuity mutant + adversarial critic) is the **one advanced layer already largely built** (`test_author.py`). Treat distillation (§8) and the determinism layer (§9B), constrained decoding (§9C), and loop-invariants (§9D) as **proposals**, each requiring: a live differential-trace harness (run real tasks under rich vs ablated metadata — not hardcoded strings), then a gated `harness_self_fix` leaf with a RED oracle to wire the synthesized checker into `ast_enforcer.validate_code` / `diff_fuzzer` corpora. Until that wiring exists, the prototype is a promising research spike, not a feature.

---

## 4. JanusNexus naming, Makefile, and landing order

- `gemini-3.0-flash` (v1 §2E) is a forward-dated model id; pin to a verified available model and make it configurable.
- §7 Makefile: the `build-tree-sitter` target asserts `import tree_sitter_python/javascript/typescript` which **fails today** (uninstalled); `PYTHON := venv/bin/python` points at a non-existent venv (the live one is `.venv`); `cd webui && npm install || true` and `lint … || echo` **swallow failures** — self-defeating for a system whose premise is deterministic gating. Remove the `|| true`/`|| echo` masks, fix the venv path, and make tree-sitter optional until the multi-language path is real.
- **Security-blocker ordering:** do not enable any JS execution path until §2b is resolved. Do not claim "evolutionary" until §2a is fixed.

---

## 5. NobleGreedv2 ⇄ JanusNexus — the integration architecture

This is the section v1 lacked, and it is where the JanusNexus direction **changes the earlier recommendation in a concrete way.**

### 5a. The question, re-evaluated

The owner asked whether — instead of building a separate agentic *spine* inside NobleGreedv2 (NGv2) — to drive NGv2 *through* JanusNexus via an API, so upgrading JanusNexus doesn't double-maintain shared core features (jail, agents, sandbox, daemon).

**Re-evaluated verdict (upheld and sharpened):** keep the **loops separate**, but **share the execution substrate** — and the JanusNexus blueprint makes that case *much stronger* at one specific seam: **detonation.**

### 5b. The convergence: detonation ≈ sandboxed execution with a different success-marker

NGv2's entire detonation step is one injected callable (`ngv2/pipeline.py:run_pipeline`, line 36):

```
runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms)
```

Its consumer, `ngv2/detonation.py:DetonationChamber.detonate`, *only* calls the runner and maps the outcome to a verdict (`exit_code==0 and success_marker in stdout → 'confirmed'`; else `refuted`/`inconclusive`/`error`). NGv2 ships **only mock runners** today (`ngv2/poc_runner.py:make_mock_runner/make_scripted_runner`); the real subprocess/bwrap runner is **intentionally left as an injection hole** ("injected at NGv2 runtime").

JanusNexus already owns exactly that runner: `harness/sandbox.py:Sandbox.execute` / `BatchRunner.execute_batch` (structured `ExecutionResult`), and the blueprint §5 generalizes it to JS/TS via the persistent `node_runner.js` bridge. Crucially, `harness/agent_jail.py:build_jail_argv(..., bind_credentials=False)` already implements the **detonation threat model verbatim**: credential-stripped, `--unshare-net` network-severed, fail-closed (bwrap missing → hard error, never an un-jailed spawn). NGv2 was designed with a hole shaped exactly like JanusNexus's sandbox runner; the only NGv2-specific knob is the `success_marker`, and `DetonationChamber(success_marker=...)` already isolates it.

Duplicating bwrap jailing + network-namespace isolation + a deterministic multi-language runner inside NGv2 would re-derive JanusNexus's **single most security-sensitive component**. That is the strongest shared-substrate case in either system.

### 5c. The loops still diverge (impedance confirmed)

The two systems share **exactly one node** — the detonate step's `runner`. Everything else diverges:

- **JanusNexus loop:** evolutionary *build* — parent selection → crossover/mutation → AST/anti-stub gates → (population/Elo) → **git commit.** Unit of work: a *sketch*; success: passes tests / commits.
- **NGv2 loop:** linear *hunt* — `hunt → triage → poc → detonate → report → done` over a `HuntStateMachine`. Unit of work: a *Finding/PoC*; success: a per-PoC **verdict**. No population, no tournament, no commit.

Forcing NGv2's hunt loop through JanusNexus's task/commit pipeline is a category error (a Finding is not a committable sketch; a verdict is not a tournament win), and the blueprint makes the Nexus loop *more* specialized toward population search, i.e. *further* from a linear hunt. **Reject "drive the whole loop through JanusNexus."** Share the node, not the loop.

### 5d. Recommended boundary: a JanusNexus-owned `sandboxkit` facade that NGv2 imports

A raw `import harness.sandbox` couples NGv2 to internals the blueprint is actively rewriting; an RPC service adds a failure domain and latency for zero isolation benefit (the isolation is bwrap, not the process hop). So: JanusNexus exposes a **thin, semver-stable facade** — `sandboxkit` — over its churning internals; **NGv2 imports `sandboxkit`, never `harness.*` directly.** JanusNexus is upstream/owner; NGv2 is downstream-only. (The import closure is clean: `agent_jail.py` is **stdlib-only**, `agent_streamer`/`sandbox_smoke` pull in nothing from the monolith — verified — so this facade is a genuine leaf, not a tendril into orchestrator.)

Minimal stable surface (and nothing more — keep it small so it survives churn):

```python
# sandboxkit — the ONLY surface NGv2 may import from JanusNexus.

@dataclass
class ExecResult:                 # frozen mirror of harness ExecutionResult,
    success: bool                 # decoupled from internal dataclass churn
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    return_repr: str = ""

def execute(code: str, entrypoint: str, inputs: list[dict], *,
            language: str = "python",          # "python" | "javascript" | "typescript"
            timeout_ms: int = 5000,
            memory_limit_mb: int = 256,
            network: bool = False,             # default-DENY: detonation is net-severed
            deterministic: bool = True) -> list[ExecResult]:
    """Backed by harness.sandbox (Sandbox.execute / BatchRunner.execute_batch)
    + the blueprint §5 node bridge for JS/TS. network/deterministic map onto
    agent_jail --unshare-net + the §9B determinism layer."""

def spawn_agent(argv, *, repo_root, work_dir, state_dir,
                bind_credentials: bool = True, network: bool = True) -> "AgentResult":
    """Backed by agent_jail.build_jail_argv + agent_streamer. For any NGv2 'spine'
    that calls a model under the same jail. bind_credentials=False + network=False
    for untrusted execution."""
```

Everything population/Elo/crossover/commit stays **out** of the facade — NGv2 never sees it.

### 5e. Minimal first step (proves the boundary, one new file, zero loop changes)

Implement NGv2's real detonation `runner` as a thin adapter over `sandboxkit.execute`, exploiting the already-injectable seam:

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

`build_handlers(runner=make_janusnexus_runner())` swaps the mock for the real one; every existing test that injects a mock keeps working (the injection design is preserved). It is **gated and reversible**: until `sandboxkit.execute` exists, NGv2 keeps shipping with the mock runner; flipping is a one-line handler change — matching JanusMask's default-OFF-then-flip rollout posture. First validation: detonate one known-`VULNERABLE` Python PoC and one JS PoC through this runner and assert `DetonationChamber` returns `verdict == 'confirmed'`, exercising both the Python `Sandbox.execute` path and the §5 node bridge through one facade call.

### 5f. Sequencing

1. **Freeze the `sandboxkit` facade contract** (`ExecResult` + `execute()` signature) — interface only.
2. **Land `sandboxkit.execute` in JanusNexus** as a non-breaking wrapper over today's `Sandbox.execute`/`BatchRunner.execute_batch` (Python first).
3. **NGv2: `ngv2/sandbox_runner.py`** (5e) behind a default-OFF flag — proves the boundary end-to-end.
4. **JS/TS detonation** moves onto the persistent node bridge (§5C) once it lands **and §2b is resolved** — behind the same `execute(language="javascript")`; NGv2 code unchanged.
5. **Optional:** route NGv2 hunt/triage *agent* spawns through `sandboxkit.spawn_agent` to retire any duplicate jail code — independent, lower priority.

**Net:** loops stay separate (build-factory vs hunt-runner), but the one security-critical node they share — running untrusted code in a credentialless, network-severed, deterministic jail and capturing its outcome — is **owned once by JanusNexus and imported by NGv2** through a stable `sandboxkit` facade, with NGv2's already-injectable `runner` seam as the zero-friction insertion point. That is the "don't double-maintain the core" win, scoped to exactly the part that is genuinely shared and genuinely dangerous — without paying the loop-coupling/impedance tax of driving NGv2 through JanusNexus's pipeline.

---

## 6. Verification provenance

Compiled from four parallel adversarial agents (2026-06-09), each reading the real repos:
1. **Blueprint vs reality** — file/feature existence audit (§0 ledger, §3 distillation correction).
2. **Technical & conceptual soundness** — bug table, AlphaEvolve misattribution, SAT-vs-optimization critique (§1, §2).
3. **NGv2 & substrate claims** — all verified; `agent_jail` is stdlib-only with a clean import closure (§5d).
4. **NGv2 ⇄ JanusNexus architecture** — the detonation≈sandboxed-execution convergence and the `sandboxkit` boundary (§5).

Every "EXISTS/ASPIRATIONAL/WRONG" verdict and every cited `file:symbol` in this document was checked against the live codebase, not inferred from v1.

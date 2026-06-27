# Phase-III RECON — Closing the Reachability Gap

**Date:** 2026-06-12 · **Scope:** read-only recon; no production edits, commits, or runs.
**Question:** how do we move NGv2 from "37 param-derived sinks, 0 claimable" to real, attacker-reachable, claimable bounties?

---

## 0. The measured problem, restated precisely

`_e2e_run/reachability.py` is **sink-anchored** and **intra-procedural**: it finds an
`eval/exec/os.system/subprocess(shell=True)` call and asks "is the dangerous arg
derived from a parameter *of the same enclosing function*?" (one-hop local taint, 4-iter
fixpoint, single file). Across the 24 eligible repos this found 37 hits and every one was
internal plumbing / dev-config / vendored / admin-gated (`RUN_LEDGER.md` §"Landscape result").

This is not a tuning problem. It is a **structural** one, proven by the corpus below.

### Decisive evidence — what the REAL bugs look like

`data/ngv2/huntr_existing_submissions.json` holds 664 accepted prior submissions across
32 repos; **26 of those repos are in our eligible set**. Reading the titles for the
eligible overlap (gradio, bentoml, comfyui, db-gpt, litellm, llama_index, llava, wandb,
composio, metagpt, localai, …), the accepted-bounty distribution is dominated by:

| Vuln class | Representative real bounty (eligible repo) | Source → Sink shape |
|---|---|---|
| **Deserialization RCE (CWE-502)** | bentoml "Unauthenticated RCE via `pickle.loads()` on HTTP request body in Runner Server"; comfyui "RCE via unsafe `torch.load()`"; wandb "Unsafe Deserialization in SavedModel"; llava "Pickle deser in `load_pretrained_model()`" | HTTP body / model file → (cross-file) → `pickle.loads`/`torch.load` |
| **SSRF (CWE-918)** | litellm "SSRF via user-controlled `api_base` in `/chat/completions`"; localai "SSRF in `/v1/images/generations`"; llama_index "SSRF in `resolve_image()`" | route param → (cross-file) → `httpx.get` |
| **Path traversal (CWE-22)** | db-gpt "Path traversal in `/api/v1/python/file/upload`"; composio "LFI via download API"; llama_index "Unauth RCE via path traversal in `download_dataset…`" | route param → file open/write |
| **eval on LLM/agent output (CWE-94/95)** | metagpt "RCE via insecure `eval()` in `ActionNode.xml_fill`"; superagi (non-elig) `eval()` on LLM output | request/config → (cross-file) → `eval` |
| **IDOR / missing auth** | gradio "Unauth RCE via `/vibe-code`"; reworkd/agentgpt IDOR | route → object access |

**Three structural facts kill the current engine:**

1. **Wrong sink set.** The dominant class is **deserialization (`pickle/torch/yaml/joblib`)**,
   which `reachability.py` does not scan at all. `ngv2/deser_detect.py` scans it — but is
   **ORPHANED** (test-only, never on a live path).
2. **Wrong direction.** Real flows start at a **source** (HTTP route, model-file load) and
   travel **across functions and files** to the sink. A sink-anchored single-function scan
   cannot see them.
3. **Wrong filter.** All 37 false positives failed not on "param-derived" but on
   **attacker-reachability + scope/auth** ("admin-gated by design", "hardcoded library
   name", "internal plumbing"). That judgment is semantic, not lexical.

Any winning design must fix all three.

---

## 1. What NGv2 already has (audited wiring status)

A striking finding: **the machinery for all three options is largely already built — but mostly orphaned.**

| Module | Purpose | Wired? |
|---|---|---|
| `pattern_scanner.py` | regex CWE-78/89/94/327/798 catalog | **WIRED** (drivers) |
| `semgrep_adapter.py` | semgrep CLI argv builder + injected runner | **WIRED** (→ `pre_analysis` → `analyzer` → `handlers` → `drive.py`) |
| `ast_verifier.py` / `treesitter_verifier.py` / `semantic_signals.py` / `confidence_signals.py` | structural proofs → confidence signals | **WIRED** (→ `session_gate`) |
| **`codeql_runner.py`** | CodeQL DB-create / analyze / taint-path, SARIF parse, injected runner | **ORPHANED** (test-only) |
| **`taint_spec_library.py`** + `data/ngv2/taint_specs/` | 12 bundled `.ql` path-problem queries: CWE-22, 78, 89, 94, **502 (×5: pickle/torch/numpy/yaml/joblib)**, 601, 918 + `manifest.json` | **ORPHANED** |
| **`deser_detect.py`** | CWE-502 sink scanner (pickle/torch/yaml/joblib/marshal/shelve) | **ORPHANED** |
| **`web_framework_detect.py`** | Flask/FastAPI/Django/aiohttp/tornado/bottle/sanic route + dep detection | **ORPHANED** |
| `joern_runner.py`, `z3_*` | alt engines | ORPHANED |

**Binaries / deps on the host:** `semgrep` PRESENT (`miniconda3/bin`), **`codeql` PRESENT
(`~/tools/codeql/codeql`)**, `joern` absent, `anthropic` SDK absent (LLM path uses the
`claude` CLI seam in `_e2e_run/claude_cli_client.py`, already proven live in the gptcache confirm).

So the bundled CodeQL taint-spec library **already targets the exact CWE distribution the
corpus demands** (note the 5 deserialization queries) — it has simply never been run.

---

## 2. The three options, costed

### (a) Inter-procedural taint engine — CodeQL vs Semgrep taint

This is the only option that *directly* supplies the missing capability: **sound-ish
cross-function, cross-file source→sink taint** with a concrete path artifact.

**Semgrep taint mode — REJECT as the engine.** Confirmed via Semgrep's own docs: OSS /
Community Edition taint is **intra-procedural, single-function only**. Cross-file
interprocedural taint is **Pro Engine** (proprietary binary, cloud-tied; free only under
the <10-contributor Team plan, whose ToS and hosted-infra model do not fit autonomous
analysis of third-party code in an offline jail). For our bug profile — request handler and
`pickle.loads` in *different files* — OSS semgrep adds **nothing over the existing
`reachability.py`**. (The wired `semgrep_adapter` is still useful as a cheap regex-rule
runner, just not as the interprocedural engine.)

**CodeQL — the strong candidate.**
- *Capability:* `python-security-extended.qls` ships maintained, interprocedural taint
  queries for exactly our CWEs (UnsafeDeserialization, SSRF, PathInjection, CommandInjection,
  CodeInjection, SqlInjection). Remote-flow source models = "untrusted external input",
  which structurally rejects the "hardcoded library name / internal plumbing" FPs that killed
  the 37. Plus the 12 bundled custom `.ql` specs already in-repo.
- *Offline/jail:* DB build and `database analyze` run **fully offline** once query packs are
  cached locally (one-time `codeql pack download`). No network at analyze time. Jail-compatible.
- *Integration shape:* **CLI**, via the injected `runner(argv)->(rc,out,err,sarif)` seam that
  `codeql_runner.py` **already defines**. SARIF→finding parsing already implemented and tested.
  Cost into the confidence cascade is low: a CodeQL taint path maps cleanly onto the existing
  `{'kind':'taint_flow'/'formal_path','result':'proof'}` signal that
  `semantic_signals`/`confidence_signals` already feed to `compute_confidence` → drives ADMIT.
- *Expected signal on ML-infra:* high — these are precisely the deser/SSRF/traversal flows the
  packs are built for, and the corpus proves they exist in our repos.
- *Cost remaining:* ~80% built. Remaining = a real subprocess runner factory, DB-build
  orchestration (minutes & ~GB per repo → must be gated, see (c)), wiring into the gate, and
  one production seam into `confidence_signals`.
- **RISK — license.** CodeQL CLI is free to analyze **"any Open Source Codebase hosted and
  maintained on GitHub.com"**, including automated analysis — which *our entire eligible corpus
  is*. The revenue motive is **not** the license's discriminator (the codebase's OSS-on-GitHub
  status is), so this use appears permitted. But the autonomous-for-bounty framing is close
  enough to the "automated analysis" clause that it **requires explicit owner sign-off before
  build**. This is the single gating risk on the recommendation.

### (b) LLM reachability-triage cascade stage — KEEP, but as a *filter*, not the engine

Insert an LLM stage (`ngv2.llm_client` over the proven `claude` CLI seam) between cheap scan
and expensive PoC synthesis: given finding + surrounding repo context, judge *"is this sink
reachable from an unauthenticated public entry point, and in-scope?"*

- *Strength:* it is the **only** option that can make the **scope/auth-gating** judgment that
  actually killed all 37 sinks ("admin-only sandboxed exec endpoint", "internal plumbing").
  Neither regex nor CodeQL can reason about business-logic auth.
- *Plug point:* a new `(triage → verify)` sub-gate in `session_gate.py`, emitting a
  `route='MANUAL'/'DROP'/'ADMIT'` band — the gate already routes on exactly these bands.
- *Cost:* ~1 CLI call per surviving finding (cents); precision good *if* it is given a concrete
  candidate path to adjudicate, poor if asked to *discover* the path from scratch.
- *Weakness — decisive:* an LLM asked to *find* the interprocedural path **hallucinates** and,
  worse, produces **no verifiable source→sink artifact**, which a bounty submission requires.
  So (b) must triage a path that something else *proved*. It cannot be the engine.

### (c) Source-first / entry-point-driven enumeration — KEEP, as the *cheap pre-filter*

Enumerate public entry points (Flask/FastAPI/gRPC routes, click/argparse CLIs, model-load
APIs) and forward-trace toward sinks. Reuses `web_framework_detect` (routes/frameworks) +
`deser_detect` (the missing CWE-502 sink class) + `pattern_scanner` + `ast_verifier`.

- *Strength:* reframes the search from "sink with a tainted local" to "**repo that has BOTH a
  public source AND a dangerous sink class**" — a cheap, sound *necessary condition* that the
  current engine lacks, and it finally puts the deserialization sink set in play.
- *Weakness — decisive:* the **forward inter-procedural trace itself** is exactly the hard part
  the current intra-proc engine cannot do. Building a sound cross-file trace from scratch in
  blind-worker leaves *re-implements CodeQL, badly*. As a *pre-filter* (does a source-sink pair
  even co-exist?) it is cheap and high-value; as the *prover* it is a multi-month trap.

---

## 3. Recommendation — a three-stage cascade, CodeQL as the load-bearing prover

> **Refutes the prior handoff's "do (c)+(b) before standing up (a)."** (c)+(b) *without* (a)
> merely relocates the unbuilt interprocedural-trace problem onto the LLM, which cannot emit the
> verifiable path a submission needs. And (a) is cheaper to stand up than the handoff assumed —
> it is ~80% built (orphaned `codeql_runner` + 12 taint specs + binary present). So we adopt all
> three, but with **CodeQL as the prover**, (c) as the cheap gate that makes it affordable, and
> (b) as the final scope judge:

```
Stage 1 (c) SOURCE×SINK PRE-FILTER  — cheap, reuses web_framework_detect + deser_detect
   → keep only repos with BOTH a public entry point AND a dangerous-sink class present.
   Purpose: avoid building a CodeQL DB (minutes, ~GB) for repos that can't possibly match.
Stage 2 (a) CODEQL INTERPROC TAINT  — the NEW capability; security-extended + bundled specs
   → prove source→sink path; emit taint_flow/formal_path proof into confidence_signals.
   This is what all 37 lacked and is the structural fix.
Stage 3 (b) LLM SCOPE/AUTH TRIAGE   — claude CLI seam; judges auth-gating + in-scope
   → DROP "admin-gated by design"/"internal plumbing" before expensive PoC synthesis.
   This filters the exact failure mode that killed the 37.
→ then existing PoC-writer + bwrap jail + repair loop (already proven on gptcache).
```

Each stage shrinks the candidate set before the next, more expensive, stage. The PoC writer /
jail / repair loop downstream already work; we are feeding them *attacker-reachable* candidates
for the first time.

### Why this ordering and not the handoff's
- (c) alone never produces a path → can't reach `confirmed`/claimable.
- (b) alone hallucinates paths and yields no submission artifact.
- (a) alone wastes minutes/GB building DBs for obviously-irrelevant repos and can't judge auth.
- **Together:** (c) cheaply gates (a); (a) supplies the missing proof + path artifact; (b)
  supplies the missing scope judgment. Each covers another's blind spot.

### Costed summary
| | New capability | Build cost | Offline/jail | License risk | Verdict |
|---|---|---|---|---|---|
| Semgrep taint (OSS) | none vs current | low | ok | none | **reject as engine** |
| **CodeQL (a)** | **interproc taint + path** | **med (80% built)** | **ok** | **owner sign-off** | **adopt: prover** |
| LLM triage (b) | scope/auth judgment | low | ok (CLI proven) | none | **adopt: filter** |
| Source-first (c) | source×sink gate | low (reuse orphans) | ok | none | **adopt: pre-filter** |

---

## 4. Risks & mitigations
1. **CodeQL license (gating).** Our corpus is OSS-on-GitHub, which the terms permit even for
   automated analysis; but get **explicit owner confirmation** before Stage-2 build. *Fallback if
   refused:* there is no equivalent free offline interprocedural engine — Semgrep Pro is paid/cloud,
   Joern is heavyweight/absent. The degraded path would be (c)+(b) with the LLM forced to emit a
   path it then self-detonates to verify (lower precision, no static guarantee). Flag this clearly.
2. **DB-build cost** (minutes, ~GB/repo). Mitigated by the Stage-1 (c) pre-filter + caching DBs
   keyed by repo SHA; build once per target, reuse across findings.
3. **CodeQL FP/precision** (e.g. taint through framework magic it can't model). Mitigated by the
   Stage-3 (b) LLM triage and the existing live-detonation gate (a CodeQL path is *evidence*, not
   confirmation — only the bwrap `semantic_verdict` confirms).
4. **Orphan-revival regressions.** `deser_detect`/`web_framework_detect`/`codeql_runner` are
   green-but-unwired; wiring them must add live-path oracles (per the standing "implementation ≠
   wired" rule), not just import them.
5. **Non-Python repos** (agentgpt TS, librechat JS). CodeQL covers JS/TS too (the runner's
   `SECURITY_SUITES` already lists javascript) — out of scope for the first build, note for later.

---

## 5. Single strongest piece of evidence
Of the 26 eligible repos that already have accepted huntr bounties, the modal accepted bug is
an **unauthenticated deserialization RCE reached from an HTTP request body or model-file load
across multiple files** (bentoml `pickle.loads` on request body; comfyui `torch.load`; wandb
SavedModel; llava `load_pretrained_model`). The current engine scans **none** of those sinks and
cannot cross a function boundary — it is structurally blind to the exact class that pays. CodeQL's
`python-security-extended` UnsafeDeserialization query, plus the **five deserialization `.ql`
specs already sitting unused in `data/ngv2/taint_specs/`**, target precisely this class
interprocedurally. The capability we need is 80% built and never switched on.

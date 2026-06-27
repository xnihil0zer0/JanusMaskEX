# BUILD PLAN — Reachability Cascade (CodeQL-prover, source×sink gated, LLM-triaged)

Implements the §3 recommendation of `DECISION.md`. Built the NGv2 way: small single-purpose
files, **rules-as-data** (sink/source/framework tables are JSON, not code), every external
effect behind an **injected seam** so oracles stay hermetic, and **live-path wiring oracles**
(not just unit-green) so revived orphans are actually reachable.

**Hard precondition (owner gate):** confirm CodeQL CLI license OK for the OSS-on-GitHub corpus
**before** Epic B is dispatched. Epics A and C have no license dependency and can proceed first.

---

## Dependencies on Phase I / II
- **Phase I (sourcing/corpus):** supplies the eligible-repo list + local clones (`tmp/recon_clones/`
  pattern, `data/ngv2/huntr_eligible_cache.json`). This plan consumes a clone path per target;
  it does not clone.
- **Phase II (scan layer):** supplies the cheap regex finding stream (`pattern_scanner`,
  `_e2e_run/recon_sinks.py`). Stage-1 here *augments* that stream with the missing CWE-502 sink
  class and the entry-point view; it does not replace it.
- **Reuses already-WIRED:** `confidence_signals.resolve_signals`, `session_gate.gate_transition`,
  `semantic_signals` proof shape, `poc_writer`/`poc_runner_live` (downstream, unchanged).
- **Revives already-BUILT-but-ORPHANED:** `deser_detect.py`, `web_framework_detect.py`,
  `codeql_runner.py`, `taint_spec_library.py` + `data/ngv2/taint_specs/`.

---

## Module list (new / changed)
| Module | New? | Role | Stage |
|---|---|---|---|
| `data/ngv2/reachability_rules/sink_classes.json` | new | rules-as-data: sink class → patterns/CWE | 1 |
| `data/ngv2/reachability_rules/entrypoint_sigs.json` | new | rules-as-data: framework → route/CLI/model-load signatures | 1 |
| `ngv2/entrypoint_scan.py` | new | enumerate public entry points from a clone (loads entrypoint_sigs.json; wraps `web_framework_detect`) | 1 |
| `ngv2/source_sink_prefilter.py` | new | pure gate: repo kept iff ≥1 entry point AND ≥1 dangerous sink co-exist | 1 |
| `ngv2/codeql_runner.py` | change | add `make_subprocess_runner()` factory (real seam) + DB-cache keyed by repo SHA | 2 |
| `ngv2/codeql_orchestrate.py` | new | thin: clone-path → create_database → run security suite + bundled specs → findings | 2 |
| `ngv2/taint_path_signal.py` | new | map a CodeQL taint finding → `{'kind':'taint_flow','result':'proof', path:[...]}` | 2 |
| `ngv2/confidence_signals.py` | change | fold a CodeQL taint-path proof into the signal list (1 seam) | 2 |
| `ngv2/reachability_triage.py` | new | LLM scope/auth judge over `llm_client` (claude CLI seam); returns ADMIT/MANUAL/DROP | 3 |
| `ngv2/session_gate.py` | change | insert `(triage → verify)` to consult `reachability_triage` band | 3 |
| `_e2e_run/drive_reachability.py` | new | hand-authorable driver: corpus → cascade → candidates for PoC writer | wiring |

---

## Leaf decomposition (blind-worker sized; RED oracle first for each)

### Epic A — Stage 1 source×sink pre-filter (no license dep; do first)
- **A1 `sink_classes.json` (rules-as-data).** Author the sink catalog: deser (pickle/torch/yaml/
  joblib/marshal), ssrf (httpx/requests/urllib `get/post`), path (open/`os.path.join` on input),
  cmdinj, eval. Each entry: `{id, cwe, patterns[], lang}`. *Oracle:* JSON schema + every CWE in
  {22,78,94,502,918} present; loadable; no duplicate ids. **Tiny, pure data.**
- **A2 `entrypoint_sigs.json` (rules-as-data).** Per framework (reuse `web_framework_detect`'s 7)
  + click/argparse + model-load APIs (`load_pretrained_model`, `torch.load`, `from_pretrained`):
  `{framework, kind: route|cli|model_load, signature_regex[]}`. *Oracle:* schema; covers fastapi/
  flask/django/click/argparse; loadable.
- **A3 `entrypoint_scan.py`.** `scan_entrypoints(clone_path) -> [{file,line,kind,framework}]`.
  Loads A2, delegates framework detection to the **revived** `web_framework_detect.detect_frameworks`,
  adds CLI + model-load regex. Pure, fs-rooted at `clone_path`, stdlib-only. *Oracle:* on a fixture
  repo with one FastAPI route + one argparse main, returns exactly those 2 entry points; empty dir → [].
- **A4 `source_sink_prefilter.py`.** `prefilter(clone_path) -> {keep: bool, entrypoints, sinks}`
  where `sinks` comes from the **revived** `deser_detect.check_deserialization` + `pattern_scanner`,
  `entrypoints` from A3; `keep = bool(entrypoints) and bool(sinks)`. Pure. *Oracle:* repo with route
  + `pickle.loads` → keep=True; repo with route but no sink → keep=False; **live-path oracle**: assert
  `deser_detect` and `web_framework_detect` are imported on this module's path (un-orphans them).

### Epic B — Stage 2 CodeQL prover (GATED on owner license sign-off)
- **B1 `codeql_runner.make_subprocess_runner()`.** Add a factory returning the real
  `runner(argv)->(rc,out,err,sarif)` that shells `codeql` and loads the SARIF file. Keep it behind
  the existing injected-seam contract; the module stays pure by default. *Oracle:* with a scripted
  fake `subprocess` seam, factory builds the right argv and parses a SARIF fixture; **never** spawns
  in tests. (Mirror the `semgrep_adapter` injected-runner discipline.)
- **B2 `codeql_orchestrate.py`.** `analyze_repo(clone_path, language, runner) -> findings[]`:
  `create_database` → `run_security_queries(security-extended)` → also `run_custom_spec` over each
  bundled `taint_specs/*.ql` (loaded/validated via `taint_spec_library.load_taint_spec_manifest`).
  Dedup by (file,line,cwe). *Oracle:* scripted runner returns canned SARIF for create+analyze; assert
  merged+deduped findings incl. a CWE-502 path; DB name deterministic. **Inject the runner — no real
  codeql in the oracle.**
- **B3 DB cache.** Key DB dir by `repo@sha`; skip rebuild if present. *Oracle:* second call with same
  sha invokes create-runner 0 times (injected counter).
- **B4 `taint_path_signal.py`.** `to_taint_proof(codeql_finding) -> {'tool':'codeql','kind':'taint_flow',
  'result':'proof','rule':cwe,'path':[...]}`; non-path/empty → None. Pure. *Oracle:* a path-bearing
  finding → proof with full source→sink path list; a no-location finding → None.
- **B5 wire into `confidence_signals.py`.** In `build_confidence_signals`, accept an optional
  `taint_proofs` list and merge (verbatim, like `semantic_signals`). One small seam. *Oracle:* a
  CodeQL taint proof present → `compute_confidence` sees a `taint_flow` proof → routes ADMIT; absent →
  unchanged. **Live-path oracle:** prove the merge fires through `resolve_signals`.

### Epic C — Stage 3 LLM scope/auth triage (no license dep; parallel with A)
- **C1 `reachability_triage.py` prompt builder (pure).** `build_triage_prompt(finding, path, snippets)
  -> str`: asks the model to classify {reachable_unauth | auth_gated | internal_only | out_of_scope}
  with a one-line justification, given the CodeQL path + code context. *Oracle:* prompt contains the
  sink, the source, the path, and an explicit JSON-output instruction; deterministic for fixed input.
- **C2 `reachability_triage.judge()` over injected `LLMClient`.** Parse the model JSON →
  band ADMIT/MANUAL/DROP. Uses `ngv2.llm_client.LLMClient` with an **injected `complete` seam** (the
  live path uses `_e2e_run/claude_cli_client.py`, already proven). *Oracle:* injected completion
  returning each verdict maps to the right band; malformed output → MANUAL (fail-safe, never DROP-silent).
- **C3 wire into `session_gate.py`.** Add `(triage → verify)` consulting C2's band before the
  confidence gate. *Oracle:* DROP band → gate ok=False error='out_of_scope'; ADMIT → proceeds.
  **Live-path oracle:** the new transition is registered in `_HANDLERS` and reachable via
  `gate_transition`.

### Epic D — Wiring / e2e driver (after A,B,C)
- **D1 `_e2e_run/drive_reachability.py` (hand-authorable, not ngv2/**).** corpus list → for each
  repo: A4 prefilter → (if keep) B2 CodeQL → B4 proofs → C2 triage → emit ADMIT candidates with
  source→sink path to the existing PoC writer. No oracle (driver), but smoke-run on 1 cloned repo.
- **D2 Regression sweep.** Full NGv2 suite green; assert the four revived modules now have ≥1
  non-test importer (kills the orphan-revival regression).

---

## Sequencing & parallelism
```
Owner license gate ──► (unblocks Epic B only)
Epic A (A1→A2→A3→A4)  ─┐   no license dep — START HERE
Epic C (C1→C2→C3)     ─┼─ parallel with A
Epic B (B1→B2,B3→B4→B5)┘   after license sign-off; B2 depends on A's clone path + revived taint_spec_library
Epic D (D1→D2)            after A,B,C land
```
- A and C are fully independent and license-free → dispatch immediately, in parallel.
- B is the only license-gated epic; if sign-off is delayed, A+C still deliver the cheap pre-filter
  and the scope triage (partial value), and the degraded fallback in DECISION §4.1 applies.
- Critical path: license-gate → B2 → B4 → B5 → D.

## Oracle strategy (cross-cutting)
1. **Rules-as-data first** (A1/A2): schema + coverage oracles on JSON — fastest, lowest-risk leaves.
2. **Injected seams everywhere external**: CodeQL via `runner(argv)`, LLM via `complete`. No oracle
   ever spawns `codeql`/`claude` or touches the network (matches `semgrep_adapter`/`codeql_runner`/
   `llm_client` existing discipline).
3. **Live-path (anti-orphan) oracles** on A4, B5, C3: assert the revived/new module is imported and
   invoked on the gate/driver path — per the standing "implementation ≠ wired" rule; unit-green alone
   does not count as done.
4. **Fail-safe defaults**: malformed LLM output → MANUAL (human review), never silent DROP; CodeQL
   runner error → finding dropped with logged error, never a fabricated proof.
5. **A CodeQL path is evidence, not confirmation** — the existing bwrap `semantic_verdict` remains the
   only thing that yields `confirmed`. Nothing here can manufacture a confirmed verdict.

## Definition of done
- A cloned eligible repo with a real deser/SSRF/traversal bug flows: prefilter keep → CodeQL emits a
  source→sink path → LLM triage ADMIT (unauth, in-scope) → candidate handed to the (already-working)
  PoC writer with the path attached. The 4 revived modules each have a live importer. Full suite green.

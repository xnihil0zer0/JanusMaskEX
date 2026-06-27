# Phase IV Gaps — what the run needs that isn't built/planned

Ordered by how directly each blocks the acceptance bar.

## G1. Inter-procedural reachability (THE blocker that killed the last run)
`_e2e_run/reachability.py` is **intra-procedural only** — it proves a sink's arg
derives from the *enclosing function's* parameter, one or two assignment hops. The
RUN_LEDGER blocker was precisely a sink (`prompt_install`) whose enclosing-fn param
was tainted but whose *only caller* passed hardcoded values. Without a call-graph
that traces taint from a **public API / route / load entrypoint** to the sink, the
run will keep confirming non-claimable internal-plumbing sinks.
- Minimum viable fix for Phase IV: a lightweight call-graph (who-calls-whom within
  the package; `ngv2.codebase_graph_extract.py` / `kg_store.py` may already give
  this — VERIFY) so a sink can be tagged "reachable from a public entrypoint" vs
  "only internal callers with constant args."
- Interim mitigation already in RUN_PLAN §1.4/§3: lean on **MFF loaders** where the
  attacker boundary (the model file) is structural, sidestepping the need for a
  full taint engine to clear the bar at all.

## G2. CWE-918 (SSRF) detector — NOT BUILT
TARGETING candidates #5 sagemaker, #10/#13 have SSRF surface; no SSRF detector
exists (`web_framework_detect.py` exists but is not an SSRF taint detector). Phase II
must add one (sink: `requests/httpx/urllib` get/post with a URL derived from a
public param, minus allowlist). Until then, SSRF candidates can't be auto-hunted.

## G3. CWE-22 (path-traversal) detector — NOT BUILT
Candidates #10 dvc, #11 triton, #14 mlflow ride on path-traversal in model-repo /
artifact-store path handling. No CWE-22 detector (sink: `open`/`os.path.join`/
`Path(...)` with attacker path + no normalization/containment check). Phase II item.
Triton's known `shm_key` traversal is unreachable to the current toolset without it.

## G4. Release-DELTA harvesting is not wired into the drivers
RUN_PLAN §1 hunts `git diff <prev_tag>..<latest_tag>`, but neither
`drive_hunt_loop.py` nor `drive_llm_confirm.py` computes or scans a delta — they
scan a whole tree / a single hand-given sink. Needs a small front-end:
`clone@tag → resolve prev tag → git diff name-only → filter *.py+subtree → feed
changed files to deser_detect/pattern_scanner`. Without it, the run re-scans whole
mature repos (the picked-over surface that produced 37 dead sinks last time).

## G5. Live verify-at-source (eligibility + saturation) is not automated
RUN_PLAN §0.3 mandates re-checking the live huntr program + per-CWE saturation
before spending LLM money, but `huntr_existing_submissions.json` is a **frozen
2026-03-28 snapshot covering only ~30 of 96 eligible repos**. ~66 candidates show
"unknown" submission counts (data gap, NOT virginity). Need a live, polite
(~1 req/s) huntr scrape per candidate-CWE at run time. (Memory references a live
multi-source scraper epic in flight — confirm it's usable here; otherwise the run
risks burning budget on an already-submitted finding = non-novel = non-claimable.)

## G6. MFF loader-entrypoint reachability rule is unimplemented
RUN_PLAN §1.4 wants deser sinks kept when on a *public load entrypoint*
(`load`/`load_model`/`from_config`/`deserialize`) even if not param-derived. The
current `reachability.py` `only_param_derived=True` filter would DROP these — the
exact opposite of what MFF hunting needs. Need an entrypoint-allowlist mode so MFF
candidates (#1 keras, #2 skops, #8 autogluon) aren't silently filtered out.

## G7. Novelty check is corpus-based, not live
`drive_full_lifecycle`/`hunt_loop` run novelty against an in-memory `corpus` list
(empty → always NOVEL). The real claimability gate needs novelty vs the LIVE huntr
submission set for that repo+CWE (`ngv2.dedup_novelty` exists — wire it to the
freshly scraped list from G5, not an empty/stale corpus).

## G8. Non-Python PoC path absent
Candidates #3 h5py (C/cython), #11 triton (C++), #12 localai/gguf (Go/C++),
#13 tvm (C++) need native crash/PoC harnessing the bwrap-Python detonator doesn't
provide. If the run wants the $4000 gguf/safetensors/onnx C-parser bounties, a
native fuzz/crash harness is required. For Phase IV, stay Python-only (keras/skops/
autogluon are pure-Python $4000-track and avoid this gap).

## G9. Claimability gate is manual
RUN_PLAN §3's four-part gate (reachable/in-scope/novel/paying) is a human/script
checklist, not an automated gate in the FSM. A `confirmed` verdict alone over-claims
(gptcache precedent). At minimum, encode §3 as an assertion before the park so the
run cannot park a non-reachable sink and call it done.

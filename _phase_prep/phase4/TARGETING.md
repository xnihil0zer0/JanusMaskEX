# Phase IV Targeting — ranked candidate corpus

Date: 2026-06-12. Author: Phase-IV targeting-prep agent (read-only).
Bar: ≥1 NOVEL, in-scope, **attacker-reachable**, jail-confirmed PoC parked at `awaiting_submission`.

## Why the prior run hit 0-claimable (the lesson that drives this list)
RUN_LEDGER.md: across 24 paid-eligible repos, 37 param-derived CWE-78 sinks in
shipped code — **every** regex-detectable one was internal plumbing / dev-config /
admin-gated. The blocker was **attacker-reachability**, not detection. The coarse
regex + intra-procedural reachability cannot prove the deep inter-procedural flow a
bounty needs. Two structural fixes drive every pick below:

1. **Hunt release DELTAS, not whole mature repos.** A repo at a patched HEAD is
   picked-over; the *newly added code* in the last 1-2 releases is the unaudited
   hunting ground. For each candidate the scan target is the
   `git diff <prev_tag>..<latest_tag>` change-surface, not the whole tree.
2. **Prefer MODEL-FILE-FORMAT (MFF) loaders.** A model-file parser's input *is*
   the untrusted attacker artifact — reachability is satisfied **by construction**,
   which is the exact wall that killed the last run. MFF_A pays $4000/critical.
   This is the single biggest lever on the acceptance bar.

## Detector reality check (gates what is scannable)
- **EXISTS now:** `pattern_scanner` → CWE-78 (os.system/subprocess), CWE-95 (eval),
  CWE-89, CWE-798, CWE-327. `deser_detect` → CWE-502 (pickle/marshal/yaml/torch.load/
  joblib/dill/shelve). `reachability.py` → intra-procedural param-derived taint.
  `mff_scorer`/`mff_root_cause`/`mff_variant_generator` → MFF track scoring.
- **NEEDED from Phase II (see GAPS.md):** CWE-918 (SSRF) detector, CWE-22
  (path-traversal) detector, and **inter-procedural** reachability. Until Phase II
  lands these, weight the corpus toward **CWE-502 (MFF/deser)** and **CWE-78**,
  which have live detectors. CWE-918/22 picks are staged for post-Phase-II.

## Saturation note (verify-at-source REQUIRED)
`huntr_existing_submissions.json` only covers ~30 repos; the other ~66 eligible
repos show "unknown" (never scraped) — that is a **data gap, not virginity**. Per
the legacy verify-at-source rule, re-scrape the live huntr repo page for each
candidate's CWE-class saturation **before** spending LLM budget (see RUN_PLAN.md).

---

## Ranked candidates (~15)

Legend: `subs` = known huntr submissions (−1 = unknown, must verify live).
Activity from live `gh api` 2026-06-12.

### TIER 1 — MFF / model-loader (reachability satisfied by construction; $4000 track)

**1. keras-team/keras — CWE-502 (.keras / SavedModel deser) — MFF_A $4000**
- subs(format)=5, repo subs unknown→verify. pushed 2026-06-12 (daily), v3.14.1 (2026-05-07).
- Why now: Keras 3 `.keras` is a zip archive; historic Lambda-layer + `Lambda`/
  `deserialize` arbitrary-call RCE. Each minor adds serializable object types.
- Change-surface to scan: `keras/src/saving/` delta v3.13→v3.14 (`saving_lib.py`,
  object-registration, `serialization_lib`, Lambda/custom-object load paths). A
  crafted `.keras`/config.json that re-introduces an unsafe `deserialize` call.
- Detector: `deser_detect` (CWE-502) covers it today.

**2. skops-dev/skops — CWE-502 (skops.io trusted-type bypass) — MFF_A (joblib track) $4000**
- subs unknown→verify (low — niche repo). pushed 2026-06-08, v0.13.0 (2025-08-06).
- Why now: skops.io is *the* "safe pickle alternative"; its security model is a
  trusted-types allowlist in `get_instance`. Every newly supported type or
  `__reduce__`/constructor path is a candidate allowlist-bypass = RCE on `load`.
- Change-surface: `skops/io/` since v0.13.0 (new `_dispatch`/`get_instance` types,
  `_audit`/`_trusted` lists). Build a malicious `.skops` that smuggles a non-allowed
  callable past the audit.
- Detector: CWE-502 + MFF tooling. **Highest novelty-per-effort** (tiny audit set).

**3. h5py/h5py — CWE-502/CWE-787 (hdf5 parse) — MFF_B $1500**
- subs unknown. pushed 2026-05-29, v3.16.0 (2026-03-06). Lower rank: C-level parser,
  PoC harder (needs malformed .h5 + libhdf5 crash → memory-safety, not clean RCE).
- Change-surface: cython `*.pyx` in delta. Stretch goal; keep behind Tier-1 deser.

### TIER 2 — low-saturation, high-churn, CWE-502/78 in API-reachable library code

**4. dagster-io/dagster — CWE-502 / CWE-78 — D_custom (crit up to $1500)**
- subs=4 (**very low competition**, pool note flags high novelty). pushed daily,
  1.13.9 (2026-06-11). Why now: code-location loading, run-launchers, and
  `RunConfig`/serdes deserialization. Scan the 1.13.x delta for new serdes
  whitelist entries / subprocess run-launcher arg construction.
- Detector: CWE-502 + CWE-78 both live.

**5. aws/sagemaker-python-sdk — CWE-78 / CWE-918 — Tier A $1500**
- subs=0 (completely fresh). pushed daily, v3.13.1 (2026-06-05). CAVEAT: last run
  found 88 CWE-78 hits → 0 reachable (heavy internal-plumbing FP). Do **not**
  re-scan the whole tree. Scan ONLY the v3.13.0→v3.13.1 delta for *newly added*
  subprocess(shell)/S3-URL-fetch paths; pair with CWE-918 once Phase II lands.

**6. zenml-io/zenml — CWE-502 (materializer cloudpickle) — Tier A $1500**
- subs=36 (saturated overall) BUT churn daily, 0.94.6 (2026-06-02). Materializers
  use cloudpickle; each new integration materializer = fresh deser surface. Scan
  new `*_materializer.py` in the 0.94.x delta; verify the specific materializer's
  CWE-502 isn't already submitted.

**7. bentoml/bentoml — CWE-502 (model store load) / CWE-78 (runner) — $1500-ish**
- subs=26. pushed 2026-06-03, v1.4.39 (2026-05-07). `bentoml.picklable_model` /
  framework `load_model` paths; runner subprocess. Scan framework-loader delta.

**8. autogluon/autogluon — CWE-502 (predictor load via pickle/torch.load) — D_custom $1500**
- subs=2 (low). pushed 2026-06-08, v1.5.0 (2025-12-19). `TabularPredictor.load` /
  `load_pkl` paths deserialize untrusted artifacts. MFF-adjacent: the saved
  predictor dir is an attacker artifact. Detector: CWE-502 live.

**9. allegroai/clearml — CWE-502 (artifact deser) / CWE-78 — Tier C $900**
- subs=10. pushed 2026-06-10, v2.1.8 (2026-05-31). Artifact get → pickle;
  prior CWE-798 work noted. Scan artifact-manager + task-param delta.

**10. iterative/dvc — CWE-502 / CWE-22 — Tier A (but $0 paid to date)**
- subs=2. pushed 2026-06-08, 3.67.1. Cache/remote path handling (CWE-22) and any
  pickled run-cache. Low payout confidence; novelty high. Stage for CWE-22 detector.

### TIER 3 — staged for post-Phase-II detectors (CWE-918 / CWE-22), or harder PoC

**11. triton-inference-server/server — CWE-22 (model-repo path traversal) — Tier A $1500**
- subs=0. pushed daily, v2.69.0 (2026-06-02). Bounties note prior `shm_key`
  traversal (task_133). Model-repository load = attacker-influenced paths. NEEDS
  Phase-II CWE-22 detector; mostly C++/Python — PoC harder. High value if reachable.

**12. mudler/localai — CWE-78 (backend exec) / gguf MFF — Tier C $900 / gguf $4000**
- subs=22. pushed daily, v4.4.2 (2026-06-11). Go+C++; gguf via llama.cpp (MFF_A
  $4000 but C++ PoC). CWE-78 in Go backend launch. Lower for a Python-tooled run.

**13. apache/tvm — CWE-502 (model importers) — low saturation (unknown)**
- pushed daily, v0.24.0 (2026-05-09). `relay.frontend.from_onnx/from_keras/from_tflite`
  parse untrusted models. CWE-502/path. Large C++ surface; scan Python frontend delta.

**14. mlflow/mlflow — CWE-502 (model registry load) / CWE-22 (artifact store) — saturated**
- subs=60 (HIGH saturation — duplicate risk). v3.13 (2026-06-01), daily churn.
  Only worth it on a *brand-new* loader path in the 3.13.x delta; otherwise skip.

**15. invoke-ai/invokeai — CWE-502 (ckpt/model load) — D_custom (crit $600, low pay)**
- subs=8. pushed daily, v6.13.0 (2026-05-27). Legacy ckpt pickle load. Low payout;
  include only as overflow.

---

## Corpus shape for the run
- **Batch 1 (highest EV, run first):** #1 keras, #2 skops, #4 dagster, #8 autogluon.
  All CWE-502, all live-detectable today, all reachability-by-construction or
  low-saturation. This batch alone should clear the bar.
- **Batch 2 (live-detector CWE-502/78 fill):** #6 zenml, #7 bentoml, #9 clearml, #5 sagemaker(delta-only).
- **Batch 3 (post-Phase-II, CWE-918/22):** #11 triton, #10 dvc, #13 tvm.
- **Skip unless idle:** #14 mlflow (saturated), #15 invoke-ai (low pay), #12 localai/#3 h5py (non-Python PoC cost).

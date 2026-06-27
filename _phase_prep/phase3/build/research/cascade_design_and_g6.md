# Reachability-cascade design notes + G6 (MFF) folding

Companion to DECISION.md §3 and BUILD_PLAN.md. Records the design choices the
reference impls bake in, the audited NGv2 integration points, and how Gap G6 is
folded into the Stage-1 (c) source-first stage.

## The three-stage cascade (as built into the reference impls)
```
Stage 0 (license) codeql_preflight  -- OWNER CONDITION, sequences FIRST
   GitHub-hosted AND OSI-licensed  -> verifiable pass token; else FAIL CLOSED.
Stage 1 (c) source x sink prefilter -- cheap necessary condition
   entrypoint_scan (revives web_framework_detect) + deser_detect + pattern_scanner
   keep = bool(entrypoints) and bool(sinks). Avoids a CodeQL DB for dead repos.
Stage 2 (a) CodeQL interproc taint  -- the NEW prover
   codeql_orchestrate over make_subprocess_runner: security-extended + bundled
   specs -> taint_path_signal -> taint_flow proof -> confidence_signals -> ADMIT.
Stage 3 (b) LLM scope/auth triage   -- the scope judge
   reachability_triage.judge over the claude CLI seam -> ADMIT/MANUAL/DROP,
   consulted inside session_gate ('triage','verify') before the confidence gate.
-> existing PoC writer + bwrap detonator (unchanged; only the semantic_verdict
   confirms — a CodeQL path is evidence, not confirmation).
```

## Audited NGv2 integration points (grounding the EDIT briefs)
- `confidence_signals.build_confidence_signals(finding, *, semantic_signals, live_report)`
  already merges structural `taint_flow`/`result:proof` dicts verbatim — so the
  CodeQL proof shape from `taint_path_signal.to_taint_proof` plugs in with ONE
  additive `taint_proofs` kwarg (leaf B4). `resolve_signals` is the live FSM entry.
- `session_gate._HANDLERS[('triage','verify')] = _gate_triage_to_verify` already
  computes confidence + routes on a band via `_confidence_band` (which recognises
  ADMIT/MANUAL/DROP). The triage consult slots in at the head of that handler
  (leaf C2), short-circuiting DROP/MANUAL before the confidence path.
- `codeql_runner` already defines the `Runner = (argv)->(rc,out,err,sarif)` seam,
  `parse_sarif`, and create/analyze/spec builders — leaf B1 only adds the real
  `make_subprocess_runner` factory (lazy subprocess import preserves purity).
- `taint_spec_library.load_taint_spec_manifest` already validates the 12 bundled
  `.ql` specs — `codeql_orchestrate` consumes it to run each spec (leaf B2).
- `deser_detect.check_deserialization` returns `patterns` records keyed
  `{module,file,line,context}` (NOT the pattern_scanner finding shape) — the
  prefilter normalises these and drops bare `*_import` records (usage sinks only).
- `web_framework_detect.detect_frameworks` returns `{frameworks:[{name,...}]}` —
  entrypoint_scan reads `name`s to gate route signatures (the live revival import).

## G6 — MFF (model-file-format) loader-entrypoint reachability, folded into (c)
RUN_PLAN §1.4 / Phase-IV Gap G6: `reachability.py`'s `only_param_derived=True`
filter silently DROPS model-loader sinks whose attacker input is the model FILE
(keras/skops/autogluon/torch). The cascade's entry-point stage MUST treat
registered MFF loader APIs as attacker boundaries (an entrypoint-allowlist mode),
NOT require param-derivation. This is folded in concretely:

1. `entrypoint_sigs.json` carries a dedicated `framework:"mff", kind:"model_load",
   attacker_boundary:"model_file"` entry whose `signature_regex` covers
   `torch.load` / `pickle.load` / `joblib.load` / keras `load_model` /
   `safetensors…load` / `.from_pretrained` / `load_pretrained_model`.
2. `entrypoint_scan` emits these as entry points UNCONDITIONALLY (unlike web
   routes, which require web_framework_detect confirmation) — the model file IS
   the attacker boundary, so no framework gating and no param-derivation needed.
3. `source_sink_prefilter` therefore returns `keep=True, mode='mff'` for a repo
   with a model-load boundary + a deser sink even when there is NO web route —
   exactly the keras/skops/autogluon $4000-track case the param-derived filter
   would have dropped. `mode` ('web' > 'mff' > 'cli') makes the MFF path explicit
   downstream.

This closes G6 at the entry-point stage without re-introducing the only_param_derived
drop, and feeds MFF candidates into the same CodeQL + triage stages as web/CLI ones.

## Fail-safe defaults baked in (DECISION §4 / BUILD_PLAN oracle strategy)
- codeql_preflight: unknown/missing/source-available license -> REFUSE (no token).
- codeql_orchestrate: no valid token -> PermissionError BEFORE any DB build.
- reachability_triage: malformed/erroring LLM output -> MANUAL (never silent DROP).
- session_gate consult: any judge error -> MANUAL; no LLM seam -> triage skipped
  (legacy callers byte-identical).
- taint_path_signal: a locationless finding -> None (no fabricated proof).

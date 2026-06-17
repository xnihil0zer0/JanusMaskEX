# Provenance Review 02 — External / NGv2 Lens

Adversarial verification of the "thread provenance through the artifact chain"
design. Every claim was checked against the real code at HEAD. **No code was modified.**

Repo: `/home/xnihil0zer0/NobleGreedv2`. All file:line refs are in that tree unless noted.

---

## (1) Verdict Table

| # | Claim | Verdict | Evidence (file:line) |
|---|-------|---------|----------------------|
| 1 | Immutable target commit pin (repo + SHA + permalink) is NOT carried on the artifact chain to submission | **CONFIRM** | SHA *is captured* at clone — `acquisition/cloner.py:133` (`git rev-parse HEAD`) → `cloner.py:144` sets `Target(pinned_commit=var_7,...)`. But the live FSM seed `run_hunt._ensure_seeded` builds session state as `{session_id, phase, repo, target, db_path, findings, pocs, reports, artifacts}` — **no `pinned_commit`** (`run_hunt.py:81`). `contracts.Finding` (76-82) and `contracts.PoC` (99-103) have **no commit/SHA field**. So the SHA dies on the `Target` object and never reaches finding→poc→report→submission. |
| 2 | PoC stage drops rich provenance (`source_meta`/`source_location`), keeping only id/target/title/content/success — so PoCs can't drive the source | **CONFIRM (and worse)** | `findings_to_candidates` *does* attach `source_meta`/`source_location`/`entrypoint` (`codeql_lead_source.py:364-372, 385-386`). But the drop is in TWO places: (a) `workers/poc.py:_build_artifact` (262-277) emits only `finding_id/target/title/description/content/success/...` — `source_meta`/`source_location`/`call_sites`/`category` are absent; (b) `poc_writer._coerce_finding` (470-487) rebuilds a `Finding` keeping only id/target/category/severity/title/description/evidence + best-effort `sink_name`/`call_sites`/`sink_symbol` — **`source_meta`/`source_location` are explicitly NOT copied**. |
| 3 | Novelty/dedup runs LAST (stage 6, after expensive detonate) although corpus + verdict store exist; should consult at triage | **CONFIRM** | Phase order `PHASE_ORDER = (source, hunt, triage, verify, poc, detonate, novelty, report, ...)` (`transition_planner.py:9`) — novelty is *after* detonate. The dedup logic `novelty_gate.classify_novelty(finding, known_corpus)` (`novelty_gate.py:43`) is pure and read-only (empty corpus ⇒ NOVEL, `:56`), so it is safe to consult early. `data/ngv2/huntr_existing_submissions.json` exists; `verdict_store.load_verdicts` (`verdict_store.py:12`) is a read-only loader. |
| 4a | Eligibility threading (`huntr_eligible_cache`) onto findings | **REFUTE (not threaded at all)** | `huntr_eligible_cache.json` is read only by sourcing/stats modules (`huntr_cache_loader.py`, `bounty_corpus_stats.py`, `sourcing/*`). It is **never** joined onto a live Finding/PoC nor consulted in any worker. There is nothing to "re-thread"; it must be *introduced* into the chain. |
| 4b | Verdict history threading | **REFUTE (orphaned)** | `verdict_store.py` has zero live callers (`grep append_verdict/load_verdicts ngv2/ -l` → only the module itself). It is built but inert; the learn→hunt→verdict loop is not closed in the running FSM. |
| (bonus) | `permalink_pin` exists and pins to SHA | **CONFIRM but ORPHANED** | `permalink_pin.pin_and_verify` (`permalink_pin.py:38`) correctly rewrites `/blob/main|master/` → `/blob/{sha}/` and drops dead links. It has **zero live callers** (`grep pin_and_verify ngv2/ -l` → module only). The capability to pin permalinks already exists; it is just not wired, and it has no SHA to consume because of claim #1. |

---

## (2) The single highest-value external-provenance change

**Thread `pinned_commit` from the `Target` into the session row at seed time, then
stamp it onto every artifact at the ONE choke point `conductor_seams.persist`.**

Why this one:

- It is the *enabling* fix for everything else. The SHA already exists
  (`cloner.py:144`) and a pinning module already exists (`permalink_pin.py:38`) — the
  only missing link is that the SHA never enters the FSM (`run_hunt.py:81`). One
  field on the seed dict + one stamp in `persist` makes commit provenance flow
  finding→poc→detonate→report→submission for free.
- It is the only provenance fact that is *security-load-bearing and
  non-reconstructable later*: `git rev-parse HEAD` at submission time can resolve to a
  DIFFERENT commit than the one actually hunted (the repo moves, the bug may be
  fixed). A submission citing the wrong SHA is a false/unverifiable bounty claim.
- It naturally doubles as the **untrusted-boundary marker** (see Risks): every
  artifact stamped with `target_pinned_commit` is implicitly "derived from adversarial
  source at SHA X."

Concretely: add `pinned_commit` to the seed in `run_hunt._ensure_seeded`
(`run_hunt.py:81`) — sourced from the cloned `Target` — and have
`conductor_seams.persist` (`conductor_seams.py:48`) copy `state['pinned_commit']` onto
each persisted artifact (and into `build_evidence` output, `conductor_seams.py:86`).
That is provenance threaded **once**, at the choke point, not per-stage.

---

## (3) Adversarial answers + better alternatives

**Per-stage injection vs a single choke point — CONFIRM there is a choke point.**
`conductor_seams.persist` (`conductor_seams.py:48-84`) is the one funnel where every
phase's artifacts are written into the session row, and `build_evidence`
(`conductor_seams.py:86-117`) is the one funnel where carried payloads are translated
into gate vocabulary. Threading provenance per-worker (hunt.py, triage.py, poc.py, …)
is N edit sites with N drift risks; the workers already strip fields they don't model
(`poc.py:_build_artifact`, `poc_writer._coerce_finding`). **Stamp provenance in
`persist` once** and have `build_evidence` carry it into the gate context. The
per-stage `_coerce_finding`/`_build_artifact` whitelists then become a *non-issue for
provenance* because the choke point re-attaches it after the worker returns.

**Is the commit-pin actually missing? Searched hard — yes, in the live path.**
It exists on `Target` (`cloner.py:144`) and in the `Target` contract
(`contracts.py:52`), but `run_hunt._ensure_seeded` (`run_hunt.py:81`) does not carry it
into the session, and neither `Finding` nor `PoC` has a field for it
(`contracts.py:76, 99`). The session DB stores whatever `persist` writes, and `persist`
never writes it. So it is genuinely absent everywhere downstream of clone.

**Does threading `source_meta` to the PoC enable "driving the source"? REFUTE — the
real blocker is the templates, not the missing field.** Even with `source_meta`
present, the PoC templates synthesize an **import-and-call-the-sink** PoC, not a
source-driving one. `_PY_HEADER` (`poc_writer.py:222`) emits
`from {module} import {sym}`, and every renderer calls `{sym}(payload)` directly —
e.g. `_py_command_injection` (`:230-234`), `_py_path_traversal` (`:286-290`),
`_py_ssrf` (`:264-268`). Grounding ranks functions by **sink** vocabulary against the
**evidence/sink** file (`default_resolver`, `:135-192`); it never reads
`source_meta`/`source_location` at all. So:
- Threading `source_meta` is *necessary but not sufficient*.
- The actual gap to "drive the taint source" is a **new source-driving template
  family** (set env / write the malicious file / send the HTTP request to the
  entrypoint) plus a grounder that resolves the *source* function from `source_meta`
  rather than the sink. Without that, the threaded field is dead weight. This matches
  the prior finding that `source_location` "already survives to the poc worker, just
  dropped at `_coerce_finding`" — true, but even un-dropping it changes nothing until
  a template consumes it.

**Security — does any stage treat target source as trusted? Mostly no; one real
execution boundary.**
- `sink_presence_gate.verify_sink_present` (`sink_presence_gate.py:106`) is pure string
  classification — no exec/import. Safe.
- `sink_reachability_gate` uses `ast.parse` only (`sink_reachability_gate.py:51`,
  docstring "never executed" `:13`). Safe (parse, not eval).
- `conductor_seams._read_target_source` (`conductor_seams.py:230-242`) reads target
  files as text into `evidence['target_source']` — data, not code. Safe, and it is
  size-capped at `_MAX_TARGET_SOURCE_BYTES=200000` (`:133`).
- **The real trust boundary is the PoC import + detonate exec.** The PoC does
  `from {module} import {sym}` (`poc_writer.py:222`) — importing adversarial target
  code executes its module-level code — and `workers/detonate.py` runs the PoC via an
  injected detonation seam (`detonate.py:4,54`). This is *intended* (it runs in a
  bwrap jail per project memory), but it means the pin SHOULD double as an
  untrusted-boundary marker so that nothing downstream of the import treats a
  `confirmed` verdict as anything but "adversarial-code-at-SHA-X executed in jail."
  Recommend: stamp `provenance.untrusted=True` + `target_pinned_commit` on the same
  artifact the detonate seam consumes.

**Where the design creates false confidence / breaks determinism — see Risks.**

---

## (4) Risks

**Determinism.**
- The codebase is aggressively deterministic (no clock/uuid/randomness in workers;
  `transition_planner` docstring `:1-7`). A naive pin fix that reads
  `git rev-parse HEAD` *at submission time* would (a) be non-deterministic and (b) cite
  the wrong commit. The pin MUST be captured once at clone (`cloner.py:133`) and
  threaded as data — never re-resolved later.
- Early novelty at triage must use the **read-only** `classify_novelty`
  (`novelty_gate.py:43`) against a snapshot corpus. If it instead mutates or appends to
  the corpus mid-hunt it would make a re-run non-deterministic. Keep the early check
  consult-only; keep `append_verdict` (`verdict_store.py:28`) at the END.

**Security / trust.**
- The pin should be a first-class untrusted-boundary marker (above). Today nothing
  records "this artifact was derived by executing adversarial code"; a `confirmed`
  PoC artifact is indistinguishable in shape from a benign one.
- Reading more target source for richer provenance widens the untrusted-read surface;
  keep the `200000`-byte cap (`conductor_seams.py:133`) and never `exec`/`import` for
  provenance extraction (only `ast.parse`/string ops, as today).

**False confidence — the dominant risk in this design.**
- **Threading `source_meta` to the PoC and declaring "now PoCs drive the source" is
  false confidence.** The templates still import-and-call the sink
  (`poc_writer.py:222-298`). Shipping the threading without the source-driving template
  family will produce PoCs that *carry* source metadata but still exploit by direct
  import — a cosmetic provenance win that masks the unchanged exploitation strategy.
- **Early novelty pruning at triage can suppress true positives.**
  `classify_novelty` returns `CONFIRMED_DUP` on same-CWE-same-file
  (`novelty_gate.py:49`); pruning there would kill a *distinct* bug in the same file as
  a known one. Use early novelty to **deprioritize/annotate**, not hard-drop, before a
  PoC is built; reserve the fail-closed drop for the final novelty stage.
- **Eligibility threading can create confidence it doesn't earn.** Stamping
  `eligible=True` from `huntr_eligible_cache.json` onto a finding implies the cache is
  authoritative and fresh; project memory already records a case where that cache
  contradicted a handoff's eligibility claim. Thread it as an *advisory* field with the
  cache's own timestamp, never as a gate that auto-greenlights submission.

---

## Summary

- Claims 1, 2, 3 **CONFIRM**. Claim 4 (eligibility + verdict threading) is worse than
  stated — those facts are **not threaded at all** and `verdict_store`/`permalink_pin`
  are **orphaned** (`grep -L` shows no live callers).
- The highest-value change is **threading the already-captured `pinned_commit`
  (cloner.py:144) into the session seed (run_hunt.py:81) and stamping it at the single
  choke point `conductor_seams.persist` (conductor_seams.py:48)** — which also unblocks
  the existing-but-orphaned `permalink_pin`.
- The "PoC drop" claim is real, but un-dropping `source_meta` alone will NOT enable
  source-driving PoCs: the blocker is the import-and-call template family
  (`poc_writer.py:222-298`), which must be replaced/extended with source-driving
  templates that consume `source_meta`. Do not ship the field-threading as if it solved
  the exploitation-strategy problem.
- Prefer the choke-point approach over per-stage injection; keep early novelty
  consult-only/advisory to avoid determinism breakage and false suppression.

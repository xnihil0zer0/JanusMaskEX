# HANDOFF — NGv2 Bounty Hunt Continuation (parallel multi-agent hunting → financial viability)

**Date:** 2026-06-12. **Author:** factory-oversight session (JanusMask).
**Status:** 9 NOVEL, jail-confirmed PoCs PARKED at `awaiting_submission`. Submission is OWNER-GATED and has NOT happened. Machinery proven; hunting is repeatable and productive.

---

## 0. ONE-PARAGRAPH ORIENTATION

NobleGreedv2 (NGv2, `/home/xnihil0zer0/NobleGreedv2`) is a security-research runtime built BY the JanusMask factory (JM, `/home/xnihil0zer0/JanusMaskJR`). The goal is **financial viability**: find NOVEL, in-scope, attacker-reachable vulnerabilities in huntr-eligible open-source AI/ML projects, jail-confirm a PoC, and PARK it for a human to submit. Prior sessions hit a wall: the Python ML **deserialization** surface is saturated (a competitor "etwithin" sweep on ~2026-06-05 filed deser disclosures on nearly every eligible repo). **This session's breakthrough = PARALLELIZE Opus hunters + PIVOT off deser to multi-tenant authz/IDOR/BOLA + SSRF + SQLi on REAL deployed products.** That flipped 0-claimable into **9 parked PoCs**. This handoff tells the next session exactly how to continue, what is already done, what NOT to re-hunt, and the ranked remaining leads.

---

## 1. HARD CONSTRAINTS (violating any of these is a serious error)

1. **NEVER auto-submit.** The human-gated submission boundary is PERMANENT (owner directive). The finish line is PARKING a PoC at `phase=awaiting_submission`. Do NOT call any submit endpoint, do NOT POST to huntr, do NOT use the noblegreed MCP `submit_code` for these. Recon is GET-only.
2. **NEVER hand-edit NGv2 production code (non-test) outside the pipeline.** Only TEST/ORACLE files are hand-authorable. New NGv2 *capabilities* (e.g. detector modules) go through the JanusMask pipeline: author a brief → commit RED oracle to NGv2 → allowlist → the live daemon builds it. Hunters only USE NGv2 detectors (import them, scan clones in `/tmp`), they never edit `ngv2/**` or `harness/**`. Markdown ledgers + per-hunter output dirs under `_e2e_run/` are fine to write.
3. **Concurrency-safety for parallel hunters (mandatory).** Each hunter touches ONLY its own ledger `_e2e_run/RUN_LEDGER_<id>.md`, its own output dir `_e2e_run/<id>_out/` (with its own sqlite DB), and clones ONLY to `/tmp/<id>_*`. They are READ-ONLY on NGv2 source, so many run concurrently without races. They must NOT start a second daemon and must NOT touch sibling files.
4. **The daemon:** one autowork daemon runs at **pid 2421475** (`python -m harness.autowork_daemon --state-dir state --config harness/config.yaml`). Don't kill or duplicate it. `scripts/run-autowork.sh` respawns the child if killed.
5. **No fabrication.** An honest negative with evidence is a legitimate result; a fake/inflated bug is not. Every PoC is adversarially verified and jail-detonated to `verdict=confirmed` before parking.
6. **Verify, don't trust.** After a hunter reports a win, confirm the artifact exists and the DB phase is `awaiting_submission`, and that the NGv2 production tree is clean (`git status --short | grep -vE '^\?\? _e2e_run/'` must be empty).

---

## 2. THE 9 PARKED PoCs (the deliverable — owner reviews these for submission)

All are jail-confirmed (NGv2 bwrap `--unshare-net/ipc/pid`, exit 0, `VULNERABLE` marker, fs `pwned_marker`), novelty-gated (verify-at-source against existing huntr/GHSA disclosures), and SHA-pinned. Each `<dir>` holds the PoC `.py/.js`, a detonation report, a SHA-pinned huntr `*_submission.md`, and a sqlite DB at `phase=awaiting_submission`.

| # | Repo @ pin | Vuln (endpoint) | CWE | Dir | Caveat / claimability |
|---|---|---|---|---|---|
| 1 | onyx-dot-app/onyx @v4.1.0 | Connector BOLA — `GET /connector/{id}` leaks config + credential_ids to any BASIC_ACCESS user | 639 | `_e2e_run/w2a_out/` | Clean. Onyx pays on IDOR-on-GET (GHSA-rw6w/vg3h). **Strong.** |
| 2 | onyx @v4.1.0 | Tool-headers BOLA — `GET /tool/{id}` returns plaintext `custom_headers` = live API keys/bearer tokens of any principal's tools | 639 | `_e2e_run/w3a_out/` | Leaks SECRET VALUES. **Strongest onyx read.** |
| 3 | vertaai/modeldb @v2.0.8.2 | HQL injection — `POST /v1/lineage/findAllOutputs` `external_id` raw-concatenated; `x' OR '1'='1` tautology leaks all tenants' lineage | 89 | `_e2e_run/w3b_out/` | **Highest severity (SQLi).** Clean. |
| 4 | onyx @v4.1.0 | Cross-principal WRITE — `PATCH /admin/tool/status` curator handler discards `user` + raw `get_tools_by_ids`; curator disables admin/other-group tools | 862/639 | `_e2e_run/w4a_out/` | Needs a Curator account (one tier above pure-BASIC). First non-read primitive. |
| 5 | FlowiseAI/Flowise @3.1.2 | SSRF deny-list bypass — `::ffff:169.254.169.254` mapped-IPv6 defeats the *patched* GHSA-2x8m fix (`httpSecurity.ts:57` kind()-mismatch) | 918 | `_e2e_run/h2_out/` | AC:H (attacker AAAA record) but also hits `::ffff:127.0.0.1`. |
| 6 | FlowiseAI/Flowise | Mass-assignment UPSERT — `POST /api/v1/credentials` keeps client `body.id` → TypeORM `save()` overwrites a victim workspace's credential (cross-workspace takeover) | 639 | `_e2e_run/w4b_out/` | NOVEL vs the disclosed mass-assignment family (other objects). |
| 7 | windmill-labs/windmill @v1.723.0 | Cross-workspace BOLA — `DELETE /api/w/{ws}/capture/{id}` discards `ws`, deletes by global id; RLS bypassed via own-ws-admin → `windmill_admin` | 639 | `_e2e_run/w4c_out/` | Clean, deterministic. |
| 8 | h2oai/h2ogpt | Unauth file-read + SSRF — `POST /execute_function/` `path_to_docs` arbitrary local read | 306 | `_e2e_run/llm_confirm_out/huntllm-h2oai-h2ogpt-*` | Needs documented `--function_server=True` flag (in-scope but non-default). 0 prior disclosures. |
| 9 | shaunwei/RealChar @v0.0.4 | Unauth IDOR — `GET /session_history` returns any session's transcript+user_id, no auth | 306/639 | `_e2e_run/w2d_out/` | next-web uses uuid4 session ids (weakens practical impact); small/dormant project. **Weakest.** |

**Suggested submission priority** (owner decides): #3 (SQLi, highest severity) → #2 (secret leak) → #1 (clean BOLA, repo pays) → #6/#7 (clean cross-tenant writes) → #4 (write, but curator prereq) → #5 (real but AC:H) → #8 (flag-gated) → #9 (weak). Verify each `*_submission.md` is accurate and the live huntr scope still lists the repo before submitting.

---

## 3. WHAT IS ALREADY DONE — DO NOT REPEAT

- **Analysis gap G1 CLOSED:** `ngv2/gadget_auditor.py` (committed NGv2 `f84b2b4`, RED oracle `a52d2d7`, 14/14 green) — a stdlib-only inter-procedural deserialization allowlist-gadget auditor. `from ngv2.gadget_auditor import audit_allowlist_gadgets, SINK_RULES`. It WORKS, but proved the gadget class is corpus-exhausted.
- **Proven-EXHAUSTED, do not re-hunt:** the Python ML **deserialization / allowlist-gadget** class across skops, keras, pytorch, transformers, dagster, + ~40 more (5 sequential hunts: skops / 20-repo sweep / 12-framework `add_safe_globals` / reachability / fresh-delta). Ledgers: `_e2e_run/RUN_LEDGER_{skops_gadget,gadget_sweep,safe_globals,reachability_hunt,fresh_delta_hunt}.md`. Mature allowlist loaders are reconstruction-inert by design; younger frameworks copy the same tiny inert registration list; competitor "etwithin" sweep saturated the disclosed-deser surface.
- **Honest-negative repos this session (well-evidenced, low ROI to revisit):** dify (lead file gone in 1.14.2; remote-files SSRF = CVE-2025-56520 dup; ssrf_proxy bypass = disclosed family), langfuse / label-studio-OSS / litellm-proxy / phoenix (properly-scoped or single-tenant-by-design or no-bounty), anything-llm (saturated ~150+ disclosures), khoj / FastGPT / one-api (properly scoped), n8n / firecrawl / activepieces-framework / lobe-chat JS (robust `net.BlockList`/`request-filtering-agent` IP validators; the mapped-IPv6 bypass does NOT generalize to them; their code-runners are by-design).
- **Key gotcha — the "DummyModelMixin / single-tenant trap":** an unscoped Django `get_queryset` LOOKS like a BOLA but isn't exploitable if the OSS signup path funnels all users into one org (`Organization.objects.first()`). Always trace tenant CREATION before trusting an unscoped-queryset finding. The real multi-org isolation often lives in a separate (out-of-scope) enterprise repo.

---

## 4. THE WINNING RECIPE (per-hunter methodology that produced 9/13 wins)

1. **Pick a REAL multi-tenant/multi-user PRODUCT** (not a library) with genuine org/project/workspace/user tenancy = a real authz attack surface. Prefer active huntr bounty + lower disclosure count.
2. **FREE novelty gate FIRST** (cheapest filter): GET-scrape the repo's existing huntr disclosures + GitHub Security Advisories (`gh api /advisories ...`) at ~1s/req. Map exactly what's filed; hunt the UNDISCLOSED siblings. A real bug that's already disclosed is NOT a win.
3. **Map the tenancy model** (roles, ownership columns, membership checks) before trusting any finding.
4. **Scan + trace:** for Python, `from ngv2.pattern_scanner import VULN_PATTERNS` (SSRF-918/path-trav-22/cmd-inj-78/sqli) + `from ngv2.deser_detect import ...`; for JS/Go, ripgrep sinks + manual route review. For each by-id/mutate endpoint: auth dependency present? ownership/tenant filter present, or raw `_by_id` with no scoping? The winning pattern was repeatedly **"always-granted role gate (BASIC_ACCESS / curator) + raw `fetch_*_by_id` with no `_for_user`/workspace filter"** — and proving asymmetry against a sibling endpoint that DOES scope.
5. **Adversarially verify** the single strongest survivor: prove a low-priv or other-tenant principal crosses the boundary. Kill single-tenant-by-design / properly-scoped / authed-same-principal / by-design code-runner / already-disclosed.
6. **Weaponize + jail-confirm:** build a deterministic reproducer (two principals where relevant; for an authz/SSRF/SQLi bug a script demonstrating the unauthorized read/write/exec/exfil is the artifact), detonate in NGv2's bwrap jail to `verdict=confirmed`. Reference detonators/packagers: `_e2e_run/w2a_out/detonate_onyx_connector_bola.py`, `_e2e_run/h2_out/detonate_flowise_ssrf.py`, `_e2e_run/package_confirmed.py`.
7. **Park** in the hunter's own sqlite DB at `phase=awaiting_submission` with a SHA-pinned huntr `*_submission.md`. Do NOT submit.

**Use NGv2's `.venv/bin/python`** (the system/miniconda python lacks `z3-solver` and will fail `pytest`/imports).

---

## 5. COPY-PASTE PARALLEL-HUNTER PROMPT TEMPLATE

Dispatch several of these concurrently in ONE message (Agent tool, `model: opus`, `subagent_type: general-purpose`). Replace `<ID>`, `<TARGETS>`, `<SURFACE/CLASSES>`.

> You are hunter `<ID>` in a PARALLEL fan-out for the JanusMask factory. NGv2 = /home/xnihil0zer0/NobleGreedv2. Authorized huntr bounty research. NEVER auto-submit — finish line is PARKING a jail-confirmed NOVEL PoC at `awaiting_submission`. CONCURRENT with other hunters — touch ONLY: ledger `_e2e_run/RUN_LEDGER_<ID>.md`, output `_e2e_run/<ID>_out/` (+ own DB), clones in `/tmp/<ID>_*`. NEVER start a daemon (pid 2421475 alive), NEVER edit NGv2 production (non-test) or sibling files. Use NGv2 `.venv/bin/python`.
> PROVEN WINNING PATTERN: cross-principal AUTHZ/IDOR/BOLA + SSRF + SQLi on REAL multi-tenant products; AVOID the saturated Python ML deser/gadget surface.
> TARGETS: `<TARGETS>`. CLASSES: `<SURFACE/CLASSES>`.
> METHOD: (1) clone @ latest release tag (pin SHA); (2) FREE novelty gate FIRST — GET-scrape existing huntr/GHSA disclosures ~1s/req, hunt undisclosed siblings; (3) map tenancy; (4) audit by-id/mutate endpoints for missing ownership/tenant scoping vs mere auth; trace SSRF/SQLi sinks to untrusted entrypoints; (5) adversarially verify ONE strongest survivor (prove cross-principal boundary crossing; kill single-tenant-by-design/scoped/by-design/disclosed); (6) IF real+novel+reachable → deterministic reproducer → NGv2 bwrap-jail detonation (reference `_e2e_run/w2a_out/detonate_onyx_connector_bola.py` + `package_confirmed.py`) → `verdict=confirmed` → SHA-pinned `*_submission.md` → PARK at `awaiting_submission` in own DB under `_e2e_run/<ID>_out/`. Do NOT submit. ELSE write `_e2e_run/RUN_LEDGER_<ID>.md` with the audit table + kill reasons.
> RULES: prove the boundary; NEVER fabricate; NGv2 tree clean at end (only your `_e2e_run/` files). REPORT BACK structured: targets@sha+disclosures+tenancy; per-survivor endpoint→boundary+verdict; PoC parked (path+DB phase+novelty) OR ledger path; tree-clean; ranked remaining leads.

After the batch returns, VERIFY each claimed win (DB phase + artifact + tree clean), update memory, then either dispatch the next wave or consolidate for owner review.

---

## 6. RANKED REMAINING LEADS (start the next waves here)

**A. Deepen the proven-vulnerable repos (highest confidence — these repos are confirmed in-scope + vulnerable):**
- **onyx** — the "curator/BASIC role-gate trusts the gate but doesn't re-check per-object group membership" pattern likely repeats. Audit `document_set/admin/*`, `skill/custom/*`, `persona/{id}/listed|featured`, MCP-server config routes, `DELETE /oauth_config/{id}/token` for the same shape (role gate + raw `_by_id` mutate, no group re-check). `POST /projects/{project_id}/move_chat_session` has a missing project-ownership check (read side is scoped → only defense-in-depth, but worth re-examining for a write angle).
- **vertaai/modeldb** — second HQL injection: `ExperimentDAORdbImpl.getExperiments`/`getExperiment` (~L626/L684) build `" ee." + key + " = :" + key` from request-derived `keyValue.getKey()` — a request-reachable HQL **property-name** injection (distinct sink from the parked one). Confirm it parses to a runnable HQL alteration (not a Hibernate parse error), then park. Also sweep every `*DAORdbImpl getX(key,value)` overload for request-derived key/sortBy reaching a raw-concat path.
- **FlowiseAI/Flowise** — `updateExecution` merges request body without re-pinning `workspaceId` (currently saved by a workspace-scoped read; verify whether any path lets the merge land cross-workspace). The cross-workspace mass-assignment/IDOR class is a disclosed THEME → more undisclosed siblings likely in workspace/variable/document-store/assistant APIs.

**B. Strong leads needing a LIVE multi-tenant instance to confirm (can't jail-confirm statically — stand up a 2-tenant instance, then weaponize):**
- **ToolJet** — cross-org credential EXFIL via `POST /api/data-sources/:id/test-connection`: `ValidateDataSourceGuard.findById(id)` has no org filter; CASL `can(TEST_CONNECTION, DataSource)` is unconditional for admin/builder with no resource-org binding; `credentialService.getValue(credentialId)` decrypts by id with no org scoping. Body `options={host:<attacker>, password:{credential_id:<orgB-cred>}}` would exfil another org's decrypted secret. 3-link gap is source-verified; needs the live 2-org instance to confirm `credential_id` reachability end-to-end. (Endpoints documented in `_e2e_run/RUN_LEDGER_W4C_lowcode.md`.)
- **activepieces** — multi-tenant authz: large Fastify route surface with platform>project>org tenancy; the framework looked robustly table-scoped in static review, but a live 2-tenant fuzz of membership checks on by-id routes is the next cut.
- **n8n** — the credential-SHARING authz surface (NOT the already-mined SSRF/RCE): cross-user/project credential access.

**C. New under-mined multi-tenant products (apply the recipe fresh):**
- label-studio **enterprise** edition (the OSS BOLA pattern becomes real cross-org BOLA if the enterprise `ORGANIZATION_MIXIN` supplies a genuine multi-org `Project.has_permission` while any detail/sync view still uses the OSS base queryset — needs the source-available enterprise repo). Re-audit `io_storages/api.py:79-114` (S3/GCS/Azure creds), `ml/api.py` MLBackendDetailAPI, `tasks/api.py` AnnotationAPI.
- caraml-dev/merlin model-serving control plane (authenticated project/model CRUD + endpoint-deployment APIs not fully swept for cross-project authz).
- mlflow tracking-server REST authz/path-traversal (weak auth plugin), kubeflow/pipelines, flyte/flyteadmin authz.
- More LLM-app products with real workspace tenancy: quivr (deeper than the killed pass), AutoGPT-platform agent-store/library tenancy, letta agents/memory, bisheng, FastGPT (looked clean — low priority), one-hub.
- langfuse post-v3.185 automation/webhook + batch-export SSRF surface as new callback-URL sinks land.

**D. Different-language / different-class breadth (untouched by the Python tooling and the competitor sweep):**
- Go/Java components of these same platforms (Ray C++/Java, seldon-core v2 agent/scheduler gRPC auth-bypass + rclone storage-URI injection, catboost JVM).
- More JS/TS low-code platforms' datasource-proxy SSRF and prototype-pollution (appsmith/tooljet datasource test endpoints are classic SSRF — but novelty-gate hard, they're mined).

---

## 7. INFRASTRUCTURE & VERIFICATION NOTES

- **Paths:** JM = `/home/xnihil0zer0/JanusMaskJR`, NGv2 = `/home/xnihil0zer0/NobleGreedv2`. NGv2 python: `/home/xnihil0zer0/NobleGreedv2/.venv/bin/python`.
- **NGv2 detectors usable by hunters:** `ngv2/pattern_scanner.py` (`VULN_PATTERNS`: command_injection/eval_usage/hardcoded_secret/insecure_deserialization/path_traversal/sql_injection/ssrf/weak_crypto), `ngv2/deser_detect.py`, `ngv2/gadget_auditor.py` (`audit_allowlist_gadgets`), `ngv2/reachability.py`. Live corpus refresh: `_e2e_run/drive_huntr_refresh.py /tmp/<dir>` (→ ~153 eligible repos). Release-delta scanner: `_e2e_run/drive_delta_scan.py`.
- **Detonation/packaging references:** `_e2e_run/w2a_out/detonate_onyx_connector_bola.py`, `_e2e_run/h2_out/detonate_flowise_ssrf.py`, `_e2e_run/package_confirmed.py`. A parked PoC = PoC script + `detonation_report.json` (exit 0 + VULNERABLE) + SHA-pinned `*_submission.md` + sqlite DB with `session_pipeline.phase = 'awaiting_submission'`.
- **Verify all parked PoCs quickly:**
  ```
  cd /home/xnihil0zer0/NobleGreedv2
  find _e2e_run -name "*submission*.md" -newer _e2e_run/RUN_LEDGER_phase4.md   # the 9 reports
  for db in $(find _e2e_run -name "*.db" -path "*_out/*"); do .venv/bin/python -c "import sqlite3;print('$db',sqlite3.connect('$db').execute('select phase from session_pipeline').fetchone())"; done
  git status --short | grep -vE '^\?\? _e2e_run/'   # MUST be empty (production tree clean)
  ```
- **All session ledgers** (negatives have evidence too): `_e2e_run/RUN_LEDGER_{H1_webapp,H2_js,H3_nondeser,H4_freshcorpus,W2A_onyx,W2B_dify,W2C_js2,W2D_shortlist,W3A_onyx2,W3B_sqli,W3C_newtargets,W4A_onyx3,W4B_ragapps,W4C_lowcode,skops_gadget,gadget_sweep,safe_globals,reachability_hunt,fresh_delta_hunt}.md`.
- **Nothing is committed in NGv2 for the PoCs** — they live untracked under `_e2e_run/`. The only NGv2 commits this session are the gadget_auditor (`a52d2d7` oracle, `f84b2b4` impl). If you want the PoCs preserved in git, that's an owner decision (they contain exploit code).

---

## 8. STRATEGIC CONCLUSION

The binding constraint was never the factory's build capability — it was **corpus saturation on one vulnerability class (deser)** plus **running hunts serially on that one class**. Closing the analysis gap (gadget auditor) was necessary diligence but did not move the needle, because that class is genuinely dry. The needle moved when we **parallelized** and **pivoted the surface** to cross-principal authorization flaws on real multi-tenant products — a class human hunters under-cover relative to deser, and one where NGv2's read-only static+jail machinery is a good fit. The next session should keep this posture: **fan out concurrent Opus hunters, novelty-gate hard, deepen the proven-vulnerable repos first, stand up live instances for the strong-but-unconfirmable leads, and keep parking — never submitting.** Owner reviews the 9 (and any new) parked PoCs and makes the submission calls.

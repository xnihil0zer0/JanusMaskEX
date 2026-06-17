# EPIC BRIEF — Source-Driving PoC Synthesis for NobleGreedv2

**Authored:** 2026-06-14 · **Status:** authored, NOT dispatched (owner-gated) · **Target repo:** `/home/xnihil0zer0/NobleGreedv2`
**Mandate:** close the gap between a *reachable* CodeQL finding and a *confirmed, claimable* PoC — i.e. make synthesized PoCs **drive the taint SOURCE** (send a malicious request / set env / write a malicious file) instead of import-and-calling the sink function.

This brief is the synthesis of a 4-lane research sweep (NGv2 codebase integration map; academic AEG/exploit-gen; practical bug-hunter tooling; LLM-agentic SOTA). Citations are inline; the convergent conclusions are at the top because they decide the architecture.

---

## 0. Why this epic exists (the precisely-scoped blocker)

The CodeQL reachability engine (landed `84aca8d`) gets a finding through triage→verify→poc. It then **blocks at `poc_authenticity`** because `poc_writer` emits a DIRECT-CALL PoC:

```python
from app.vuln import run_cmd     # the SINK function
run_cmd(payload)                 # but run_cmd is a 0-arg Flask route reading request.args
```

A 0-arg web route cannot be exploited by `run_cmd(payload)`. The PoC must drive the **taint source** — e.g. `client.get('/run?cmd=<payload>')` via an in-process test client. **CodeQL already carries `source_location` (file+line of the taint entry); it is dropped at `poc_writer._coerce_finding`.** Closing that data path + adding source-driving templates is this epic.

---

## 1. Convergent research conclusions (these decide the design)

1. **The taint path is the dominant input signal — and we already have it.** PoCGen drops 77%→27% without the taint path; Fang/Kang drop 87%→7% without the CVE description. CodeQL hands us the source→sink path for free, putting us in the high-success regime. *(Lanes 2,4: PoCGen arXiv 2506.04962; Kang arXiv 2404.08144.)*
2. **The closest architectural twins are PoCGen (JS, CodeQL taint→per-CWE detonation) and POC-GYM (Java, CodeQL traces→AspectJ sink-reachability authenticity oracle).** Clone their prompt shape, coverage-gradient feedback, per-CWE sentinel oracles, and 5-category reject taxonomy. *(Lane 4: arXiv 2506.04962, 2602.04165.)*
3. **Localization is NOT the bottleneck — the trigger is.** Even with exact sink file+line, agents reach ~70% "executes" but only ~21% "actually triggers" (arXiv 2510.14700). The work is driving the source through the path's branch guards + the app's auth/state. *(Lane 2.)*
4. **Auth/state is the single biggest lever.** Providing a manual token moved SQLi trigger 0%→67%; making the agent self-login cost −33pp. Seed credentials/session into the target before detonation. *(Lane 2: arXiv 2510.14700.)*
5. **Confirm by observing STATE, not parsing responses.** Priority ladder (offline-jail-first): **instrumented-sink marker → fs sentinel (`pwned_marker`) → loopback-listener (blind SSRF) → state-diff → time-delay.** OAST/DNS need egress (our jail is `--unshare-net`) → substitute a loopback listener. *(Lanes 2,3: CVE-Bench arXiv 2503.17332; PHUZZ arXiv 2406.06261; huntr Vulnhuntr.)*
6. **Require the sink to actually fire.** Instrument the CodeQL sink line and assert it executed with the tainted value (`sys.settrace`/coverage). Closes the 44% "looks-valid-vs-triggers" gap (POC-GYM). Reject PoCs that write the success token directly (PoCGen anti-faking). *(Lane 4.)*
7. **In-process test clients, not real sockets.** The jail is `--unshare-net`. Flask `app.test_client()`, Django `Client()`, Starlette/FastAPI `TestClient` all dispatch WSGI/ASGI in-process — fully offline. flask/werkzeug/fastapi/starlette/httpx/requests are already importable on the host (Django would need the dep-install fallback). *(Lanes 1,3.)*
8. **Verifier ≠ discoverer, oracle outside the writable sandbox.** We already have the jail gate on the right side of this line; keep the success oracle out of the agent's writable surface (ImpossibleBench: models cheat weak oracles 76-93%). *(Lane 4: arXiv 2510.20270; XBOW.)*

---

## 2. Current-state integration map (exact, from lane 1)

**Good news — source data already survives to the worker.** `hunt.py:_build_finding` does `dict(source)` + `json.dumps`, `_normalize_candidate` preserves `source_location`/`entrypoint`, `conductor_seams.persist` writes findings verbatim to `state['prior_findings']`. The finding dict handed to `write_poc` **contains `source_location`** — the ONLY missing step is poc_writer reading it.

**Data-contract gaps (the work):**
| Gap | Location | Fix |
|---|---|---|
| A — `source_location` dropped | `poc_writer._coerce_finding` (470-487) preserves only id/target/category/evidence + monkeypatches sink fields | copy `source_location`, `source_kind` onto the coerced finding |
| B — no source KIND | `codeql_lead_source._extract_source_location` (134-177) emits only `{file,line}` | classify the source line (request.args/form/json / argv / env / file-open) at enrich time |
| C — `entrypoint` overloaded | codeql sets `entrypoint="file:line"` (source), poc_writer reads `entrypoint` as a sink_symbol fallback (483) | give the source a dedicated field; stop overloading `entrypoint` |
| D — `Grounding` has no source surface | dataclass (54-68): `entrypoint` = first SINK function only | add `source_kind, route_path, http_method, param_name, app_object, app_factory` |
| E — templates are 100% direct-call | all 9 families via `_PY_HEADER` `from mod import sink; sink(payload)` (222-304) | add source-driving template family keyed by `(source_kind × cwe)` |
| F — jail net unshared | `poc_runner_live.build_detonation_jail_argv` (82) `--unshare-net` | in-process test clients + loopback listener; never real HTTP |

**Detonation confirm contract (unchanged, reuse):** `semantic_verdict=='confirmed'` iff exit 0 AND `VULNERABLE` in stdout/stderr AND `pwned_marker` in fs-diff. `detonate_live(...)` already has the dep-install fallback (host `pip install --target _jmdeps` → ro-bind → re-run, ≤3 rounds). `poc_authenticity` passes any PoC that imports+references a target package → **a test-client PoC `from app import app; app.test_client()` classifies as `real_target` and passes.**

---

## 3. Per-CWE × per-source trigger + oracle taxonomy (the payload bank to vendor)

Modeled on the Nuclei template schema (CWE → sink-signature → payload template with `{{CMD}}`/`{{MARKER}}` slots → matcher). Seeded from sqlmap error-DB, tplmap engine matrix, PayloadsAllTheThings, ysoserial.py. **All rows below are offline-jail-reproducible unless marked.**

| CWE | Sink | Source-driven trigger | Offline oracle |
|---|---|---|---|
| **78** cmd-inj | `subprocess.*`,`os.system` | param/arg = `; touch pwned_marker; echo VULNERABLE` | fs sentinel `pwned_marker` |
| **22** path-trav | `open`,`send_file` | param = `../../../../etc/passwd` (+ `tests/../` prefix-bypass, `%2e%2e%2f`) | `root:x:0:0` in response / sentinel read |
| **94/95** code-inj/eval | `eval`,`exec` | `__import__('os').system('touch pwned_marker')` | fs sentinel / instrumented-`eval` marker |
| **502** deser | `pickle.loads`,`yaml.load` | pickle `__reduce__`→`os.system("touch pwned_marker")`; yaml `!!python/object/apply:os.system ["touch pwned_marker"]` | fs sentinel |
| **89** SQLi | cursor `execute` | `' UNION SELECT '<marker>'-- `; `' OR SLEEP(7)-- ` | marker in response / error-string / time-delay |
| **918** SSRF | `requests.get`,`urllib` | URL = `http://127.0.0.1:<canary-port>/<nonce>` | **loopback listener** received nonce (jail-safe substitute for OAST) |
| **1336** SSTI | `Template().render` | `{{7*7}}`→`49`; RCE `{{cycler.__init__.__globals__.os.popen('id').read()}}` | `49` / command output in response |
| **862/IDOR** authz | (no code sink) | replay request as tenant-B for tenant-A object | **state-diff** (un-templatable generically; matches prior memory finding) |

**Source delivery channels:** HTTP (Flask `app.test_client()` / Django `Client()` / Starlette `TestClient`); CLI argv (`subprocess.run([...])`); env var; malicious archive (zip/tar-slip member `../../../tmp/pwned`); pickle/yaml file; DB seed.

---

## 4. Proposed architecture (steal from PoCGen/POC-GYM/Naptime)

```
CodeQL finding (source_location, sink, taint path, cwe)
   │
   ├─▶ source_localize.py (NEW)  — classify source KIND at (file,line):
   │        framework (flask/django/fastapi) · route_path · http_method · param_name
   │        · app_object / create_app factory · or argv/env/file/deser channel
   │
   ├─▶ poc_writer (EXTENDED) — source-driving templates keyed (source_kind × cwe):
   │        emit a driver that imports the app, instantiates the test client,
   │        sends the crafted request with the payload from §3, asserts marker
   │
   ├─▶ detonate (REUSE) — bwrap jail, in-process client (no socket),
   │        loopback listener for blind SSRF, dep-install fallback for missing libs
   │
   └─▶ confirm (EXTENDED) — instrumented-sink marker (sys.settrace at sink line)
            + fs sentinel + VULNERABLE marker  ⇒ semantic_verdict=='confirmed'
            anti-faking: reject if marker written without sink firing
   repair loop: feedback = stdout/stderr/exit/state_diff + coverage "warmer" marks;
                cap ~3 rounds then FRESH restart; abort after 3 malformed responses
```

---

## 5. Decomposition into pipeline-buildable leaves

Each leaf: new/edited NGv2 module + a hand-authored RED oracle committed BEFORE dispatch (factory rule). All land via the manual-drive `.files.json` recipe; verify HEAD after each (blue-green re-exec lies). Sequence respects deps.

### Leaf 1 — `ngv2/source_localize.py` (NEW) + oracle
Mirror of `sink_localize.py`. `localize_source(file_path, line) -> dict` returning `{kind, framework, route_path, http_method, param_name, app_object, app_factory, confidence}`. Reuse existing `web_framework_detect.py`, `entrypoint_scan.py`. Fail-soft (`{kind:'unknown'}`).
- **Oracle:** AST fixtures for Flask `@app.route('/run') def run(): request.args['cmd']` → `{kind:'http', framework:'flask', route_path:'/run', param_name:'cmd', app_object:'app'}`; Django view; FastAPI route; argv (`sys.argv`); env (`os.environ`); file (`open`). Plus fail-soft on garbage.
- **Files:** `ngv2/source_localize.py`; `tests/test_source_localize.py`.

### Leaf 2 — `codeql_lead_source` source-kind enrichment + oracle
Extend `_extract_source_location` (134-177) to read the source line via `source_localize.localize_source` and attach `source_kind`+`route_path`+`param_name`. Carry in `findings_to_candidates.raw` (333-339) in a dedicated `source_kind`/`source_meta` field — **stop overloading `entrypoint`** (Gap C).
- **Oracle:** extend `tests/ngv2/test_codeql_lead_source.py` — candidate now carries `source_meta` with framework+route+param from the materialized fixture; existing tests stay green.
- **Files:** `ngv2/codeql_lead_source.py`; edit `tests/ngv2/test_codeql_lead_source.py`.

### Leaf 3 — `poc_writer` source threading + `Grounding` source surface + oracle
(a) `_coerce_finding` preserves `source_location`+`source_meta` (Gap A). (b) `Grounding` gains `source_kind, route_path, http_method, param_name, app_object, app_factory` (Gap D). (c) a `source_resolver` reads the source meta + grounds the app object (grep `Flask(`/`FastAPI(`/`create_app`). Existing direct-call path unchanged when no source meta.
- **Oracle:** `tests/test_poc_writer_source_grounding.py` — finding with `source_meta` produces a Grounding carrying route+param+app_object; finding without it falls back to current behavior (anti-regression).
- **Files:** `ngv2/poc_writer.py`; `tests/test_poc_writer_source_grounding.py`.

### Leaf 4 — Source-driving template family + payload bank + oracle
New templates keyed `(source_kind × cwe)`. HTTP→test-client driver (Flask/Django/Starlette); argv→`subprocess.run`; env; file/archive→zip-slip builder; deser→pickle/yaml payload. Vendor the §3 payload bank as `ngv2/payload_bank.py` (CWE→sink→`{{CMD}}`/`{{MARKER}}` template). Each emitted PoC imports the app, drives the source, asserts marker → exits 0 + prints `VULNERABLE` + touches `pwned_marker`.
- **Oracle:** `tests/test_poc_writer_source_templates.py` — for each (source_kind,cwe) the rendered python (i) `ast.parse`s, (ii) imports the app object (so poc_authenticity → `real_target`), (iii) contains the test-client/driver call, (iv) contains marker+fs-signature. Plus `tests/test_payload_bank.py`.
- **Files:** `ngv2/payload_bank.py`, `ngv2/poc_writer.py`; tests.

### Leaf 5 — Instrumented-sink confirmation + anti-faking + loopback listener + oracle
(a) `ngv2/sink_instrument.py` (NEW): wrap detonation so the CodeQL sink line is traced (`sys.settrace`/`coverage`); confirmation requires the sink fired with the tainted value (POC-GYM). (b) anti-faking: reject if `pwned_marker` appears without the sink firing (PoCGen). (c) `ngv2/loopback_listener.py` (NEW): in-jail HTTP listener on `127.0.0.1` for blind SSRF (OAST substitute under `--unshare-net`).
- **Oracle:** `tests/test_sink_instrument.py` — a PoC that fires the sink → confirmed; a PoC that only `touch`es the marker without reaching the sink → rejected. `tests/test_loopback_listener.py` — SSRF to loopback nonce → received.
- **Files:** `ngv2/sink_instrument.py`, `ngv2/loopback_listener.py`; edit `ngv2/detonation.py`/`poc_runner_live.py` confirm path; tests.

### Leaf 6 — Repair-loop feedback redesign + oracle
Edit `ngv2/poc_repair_loop.py`: feedback = `(stdout, stderr, exit_code, state_diff)` + coverage "warmer" marks (executed-vs-unexecuted taint lines as EOL comments, PoCGen); cap ~3 rounds then **fresh restart** (not deeper refine); abort after 3 malformed responses (SWE-agent); strict-honesty prompt ("if unexploitable, say so").
- **Oracle:** `tests/test_poc_repair_feedback.py` — feedback payload contains exit/stderr/coverage marks; round cap enforced; malformed-response abort.
- **Files:** `ngv2/poc_repair_loop.py`; test.

### Leaf 7 — Auth/state bootstrap (highest trigger lever) + oracle
`ngv2/auth_bootstrap.py` (NEW): before detonation, seed a session/token into the target (test-client login, env token, or fixture DB row) when the route requires auth. Per lane 2 this is the single biggest trigger-rate lever (SQLi 0→67%).
- **Oracle:** `tests/test_auth_bootstrap.py` — for a Flask app with a login route, bootstrap yields an authenticated test client; no-auth app → pass-through.
- **Files:** `ngv2/auth_bootstrap.py`; edit detonate seam; test.

### Leaf 8 — `requirements.txt` pins + integration wire + live validation
Pin `flask, werkzeug, fastapi, starlette, httpx` (currently ambient host-only). Wire source-driving as default in the poc seam. Then a **live validation run_hunt** on the CodeQL smoke repo (Flask `request.args`→`subprocess.Popen`) must advance hunt→...→detonate with `semantic_verdict=='confirmed'` (the first confirmed source-driven PoC), then a live campaign on 1-2 eligible huntr repos.
- **Oracle:** integration test + the live e2e (not a unit oracle — the WORKS gate).
- **Files:** `requirements.txt`, `ngv2/workers/_runner.py` wiring; live run.

---

## 6. Build discipline (factory rules — non-negotiable)

- **Hand-author each RED oracle and commit it to NGv2 BEFORE dispatching its leaf.** Embed the oracle SOURCE in the leaf spec so the blind worker sees the contract.
- **Land via manual-drive `.files.json`** (`stage_task` → write `state/output/<tid>.files.json` → remove `.py` sidecar → `orch._auto_commit_accepted`). The orchestrator makes the commit; never hand-edit production.
- **EXTERNAL_DIRTY_GATE:** commit legitimate data refresh + `mv state /tmp/hold` aside → clean tree → drive → restore. Campaign runs leave the tree dirty.
- **Verify HEAD after every drive** — `no_diff` + `AUTO_COMMIT_OK=False` often still LANDED (blue-green re-exec).
- **NEW module = single-file whole-file**; R-anchor new symbols; run the UNION of all oracles touching a shared symbol.
- **Never auto-submit bounties.** A confirmed PoC is owner-gated per-target.
- **BUILT ≠ WORKS.** The only success signal is a jail-`confirmed` source-driven PoC on a real eligible repo. Leaves 1-7 are BUILT; Leaf 8's live run is WORKS.

---

## 7. Reference systems to clone/study (most → least directly adoptable)

- **PoCGen** (JS, CodeQL taint→per-CWE detonation, anti-faking, coverage-gradient feedback) — arXiv 2506.04962, github.com/sola-st/PoCGen — *primary reference, clone the prompt+oracle shape.*
- **POC-GYM** (Java, CodeQL traces→AspectJ sink-reachability authenticity, 5-reject taxonomy) — arXiv 2602.04165.
- **VulnSage** `callChainWithCtx` context schema — arXiv 2604.05130.
- **Project Naptime/Big Sleep** (reporter→Controller verifier split, multi-trajectory @N) — projectzero.google/2024/10/from-naptime-to-big-sleep.html.
- **XBOW validation-benchmarks** (web build-flag oracles, headless-XSS, timing-SQLi) — github.com/xbow-engineering/validation-benchmarks.
- **Interactsh** (OAST; we substitute a loopback listener offline) — github.com/projectdiscovery/interactsh.
- **huntr Vulnhuntr** (the real-world finding→curl/test-client→marker loop) — blog.huntr.com/hunting-with-vulnhuntr-getting-your-first-cve.
- **Trail of Bits Buttercup / Shellphish Artiphishell** (AIxCC CRS, CodeQL-first, dataflow framework like our factory) — github.com/trailofbits/buttercup, github.com/shellphish/artiphishell.
- **Nuclei templates / sqlmap error-DB / tplmap** — payload-taxonomy structure to vendor.

---

## 8. Estimated shape

8 leaves, ~5 new modules (`source_localize`, `payload_bank`, `sink_instrument`, `loopback_listener`, `auth_bootstrap`) + 4 edited (`codeql_lead_source`, `poc_writer`, `poc_repair_loop`, `_runner`), ~9 oracle files. P0 = Leaves 1-5 (the authenticity+confirm core). P1 = Leaf 4 prompt context already inside. P2 = Leaf 6. P3 = Leaf 7. Leaf 8 = the live WORKS gate. The first source-driven jail-`confirmed` PoC is the milestone that turns "reachable finding" into "claimable bounty."

# JanusMaskJR — Adversarial Scan Findings + Hardening Plan

Authored 2026-06-07 by the security-audit session. Captures the adversarial scan
of JanusMaskJR (the factory itself), the **verified** findings, and a sequenced
hardening plan that routes each fix through the *right* tool — config/data by hand,
harness code through the gated pipeline, design changes as their own epics.

- Target: `/home/xnihil0zer0/JanusMaskJR` (HEAD `3d3c576`).
- Method: real `semgrep` (p/python + p/security-audit + p/command-injection) over
  `harness services tools webui scripts config` + 4 red-team agents over JM's threat
  surfaces (jail / AST gate / trust+auto-approve / injection). **Every load-bearing
  claim was then independently re-verified** by running the real `validate_code`,
  reading the real `agent_jail`/`staging`/`config`, and checking live process state.
  Agent overstatements were filtered out (see §6).

---

## 0. TL;DR

JM's security model is **defense-in-depth with the bwrap repo-write-boundary as the
one load-bearing control.** The resting state is safe (no daemon running,
`supervisor.stop` set, `auto_promote.allowlist` deny-all). But the **secondary** gates
— the AST eval/exec ban and the auto-approve content denylist — are each individually
bypassable, and the committed `config.yaml` ships the *widened* auto-approve posture
enabled. The highest-leverage hardening is two ~5-minute config/data edits plus three
small `harness_self_fix` pipeline tasks; two findings are design tradeoffs, not quick
fixes. Estimated effort: **~5 min (hand) + ~3–6 h (pipeline, manually driven)** for
the genuinely fixable set.

---

## 1. Verified findings

Severity reflects *exploitability in the intended autonomous posture*, not the
(currently safe) resting state.

| # | Finding | Sev | Status | Where |
|---|---|---|---|---|
| 1 | Synthesis-path jail is a *write* boundary, not an *exfil/PID* boundary (`--share-net`, RW `~/.claude`+`~/.gemini`, shared `/proc`/PID ns) | HIGH | **CONFIRMED, by-design** | `agent_jail.py:129,181` |
| 2 | eval/exec ban bypassable — `subprocess.Popen`, `subprocess.run(shell=True)`, `builtins.exec`, `from os import system as s`, `e=exec` all PASS `validate_code` | HIGH | **CONFIRMED (ran validator)** | `ast_enforcer._check_dangerous_calls` |
| 3 | `task_id` path traversal → arbitrary `*.json` write/delete outside repo | HIGH | **CONFIRMED, latent** | `plan_validator.py`, `staging.py:88-107` |
| 4 | Committed `config.yaml` ships widened auto-approve ENABLED (skips `harness_self_fix` req + HMAC + ceiling) | HIGH | **CONFIRMED (empty git diff)** | `config.yaml:41-89`, `orchestrator._auto_approve_sensitive_eligible` |
| 5 | "Pause" mental-model gap — daemon honors `autowork/pause`+`autowork/full_stop`, NOT the `orchestrator.flag` the operator set | MED | **CONFIRMED** | `autowork_daemon._pause_flag_path:288` |
| 6 | Self-heal agent output is trusted-as-authorization (HMAC attests bytes, not intent) | MED | **CONFIRMED** | `selfheal._mint_provenance` |
| 7 | Auto-approve content gate is a narrow denylist (passes `Popen`/`os.exec*`/`importlib`/`ctypes`) | MED | CONFIRMED (overlaps #2) | `orchestrator._auto_approve_content_safe` |
| 8 | semgrep: 16 ERRORs — mostly by-design self-target `subprocess shell=True`; webui `nan-injection`; md5/sha1 | LOW | corroborating | `orchestrator.py`, `webui/app.py:714` |

**Verification notes.** #2: bare-statement `subprocess.Popen`/`builtins.exec` are
caught by an *unrelated* `incomplete_ast` rule, but **inside a normal function** (the
realistic shape of synthesized code) they pass — re-tested cleanly. `os.system(...)` IS
caught; `subprocess.run(shell=True)` is a *warning*, not an error. #4: `git diff
harness/config.yaml` is empty → these are committed values, not run-tuning left dirty;
`auto_approve_count.json` = `{"count": 29}`. #1: `agent_jail.py` only adds
`--unshare-net --unshare-ipc` on the execute path; the code comments document the
synthesis-path tradeoff ("not an exfil boundary -- only a write boundary on the repo").

---

## 2. What is genuinely solid (do not over-rotate)

Fail-closed on missing `bwrap` (every caller refuses to run unjailed); repo
`--ro-bind` so `harness/**` is structurally unwritable; D-Bus proxy correctly blocks
`org.freedesktop.systemd1`; `_NEVER_AUTO_APPROVE` re-checked even in widened mode with
path normalization; `hmac.compare_digest` (no timing/truncation bug); HMAC secret at
`~/.config/janusmask/` outside every jail bind; commit-time worktree containment for
`files_touched` (`relative_to` catches `..`); all git via argv (no shell injection);
`yaml.SafeLoader`; external-target jail split; webui localhost + operator-token + CSRF.
The scan deliberately surfaces the few inputs that bypass these, not a broken system.

---

## 3. Hardening plan — route each fix to the right tool

### 3a. Config / data — by hand, ~5 minutes (NOT pipeline; data is exempt)
- **H1 (#4):** flip `config.yaml` → `auto_approve_sensitive_harness: false`,
  `selfheal_auto_promote: false`, `autowork.enabled: false`, `auto_approve_ro_gate:
  false`. Restores the "default-off" posture the design assumes.
- **H2 (#5-data):** drop `state/control/autowork/full_stop` (the persistent,
  never-auto-cleared daemon stop) instead of relying on `orchestrator.flag`.
- These two give the **most safety per minute** and should land first.

### 3b. Harness code — through the gated pipeline (`harness_self_fix`)
Each = RED oracle (hand-authored, sanctioned) → brief → planner → stage → worker →
auto-commit + operator decision file. **Drive manually** (planner.cli → stage_task →
orchestrator_worker, no daemon) — do not start the daemon to fix the daemon's posture.

- **H3 (#3) — `task_id` validator [cleanest, highest-value].** Add
  `re.fullmatch(r'[A-Za-z0-9._-]+', task_id)` + reject `..` at `plan_validator` and
  defensively in `stage_task`/`impl_plan_to_queue`/`enqueue_subtasks`. Mirrors the
  existing `_valid_mutation_module` check. Closes #3 and the latent staging-worktree
  escape at once. Small, low-truncation-risk.
- **H4 (#2) — harden `_check_dangerous_calls` [long pole].** Flag `ast.Attribute`
  calls whose attr ∈ {exec,eval,system,Popen,…}, `getattr`/`globals`/`__import__`/
  `compile` by name, and aliased imports of dangerous symbols (track import bindings);
  treat `subprocess.*` as error (not warning) on self-targets. Logic-dense single
  function → budget 2–3 stochastic synthesis rounds.
- **H5 (#5-code) — wire the daemon pause.** Make `_decide`/`_auto_promote` also honor
  `control.pause_flag_path` (`orchestrator.flag`), or document the split loudly. Small.
- **H6 (#7) — content gate (optional).** Either widen the denylist or (better) re-run
  `validate_code` on the **post-merge** file in `commit_accepted_output` so the gate
  inspects the actual committed bytes, not patch fragments. Overlaps H4.

### 3c. Design epics — not "harden through the pipeline" jobs
- **#1 jail exfil** — the synthesis-path `--share-net`/RW-creds is a *deliberate*
  tradeoff (agy OAuth loop breaks under `--unshare-net`/`--unshare-pid`). A real fix is
  a net-egress allowlist (proxy in front of `--share-net`, only model API hosts) or an
  OAuth-flow redesign — a project, possibly an accepted risk. Weeks-scale.
- **#6 self-heal authorization** — make provenance attest *operator intent*, not just
  bytes (e.g. an operator-countersigned allow for self-heal briefs). Own epic.

---

## 4. Effort estimate (grounded in JM's serial + stochastic pipeline)

Compute is cheap; wall-clock is hand-authoring + stochastic retries + serial run.

| Item | Tool | Estimate |
|---|---|---|
| H1 + H2 (config/data) | hand | ~5 min |
| H3 (`task_id` validator) | pipeline | ~1–1.5 h |
| H4 (`_check_dangerous_calls`) | pipeline | ~1.5–2.5 h (2–3 rounds) |
| H5 (daemon pause wiring) | pipeline | ~1 h |
| **Subtotal — fixable set** | | **~5 min + ~3.5–5 h** |
| H6 (content gate, optional) | pipeline | +~1–1.5 h |
| #1 / #6 (design epics) | epics | weeks each / may be accepted |

Per-pipeline-fix anatomy: oracle 15–40 min + brief 10–20 min + planner/synthesis
10–30 min + retries 0–40 min + protected-path decision file 5–10 min + sweep 5–15 min.

---

## 5. Recommended sequence
1. **H1 + H2 now** (5 min, by hand) — biggest safety-per-minute; restores default-off.
2. **H3** (validator) — cleanest pipeline fix, closes a real autonomous write/delete.
3. **H4** (AST ban) — the load-bearing static-gate fix; oracle is the real assurance,
   not the gate it hardens (mind the bootstrapping irony — fine, but make the oracle
   strong).
4. **H5** — daemon pause wiring.
5. Park **#1 / #6** as design epics; decide accept-vs-fix on #1 explicitly.

---

## 6. Where the scan agents overstated (corrections kept honest)
- "`subprocess.Popen`/`builtins.exec` accepted as bare statements" — FALSE; caught by
  `incomplete_ast`. TRUE only inside a function (the realistic case) — re-verified.
- "allowlist empty / 215 bytes = content" — the 215 bytes are **comments**;
  comment-only = deny-all (the agent's conclusion was right, my first read was wrong).
- "ceiling shows 29 widened auto-approvals" — `auto_approve_count.json={"count":29}` is
  confirmed, but attributing all 29 to the widened branch is inference, not proof.
- Jail `ptrace` reasoning was hedged by the agent; the **confirmed** core is the
  missing `--unshare-net`/`--unshare-pid` + RW creds on synthesis, which is enough.

---

## 7. Posture at report time (unchanged by this audit — read-only scan)
JM gate `pause` (`orchestrator.flag`), allowlist deny-all, daemon not running,
`supervisor.stop` set. No JM production code was modified during the scan. Config-flag
discrepancy (#4) and pause-flag split (#5) are reported, not yet remediated — H1/H2
above are the 5-minute fixes awaiting your go-ahead.

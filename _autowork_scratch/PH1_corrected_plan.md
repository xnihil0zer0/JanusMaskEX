# PH1 — Corrected plan (synthesis of PH0 audits, 2026-06-13)

## Keystone correction (REFUTES the handoff §7 dependency-inversion)
The handoff claimed config-schema↔model-backends is circular and proposed inverting so
model_backends becomes the foundation. **PH0 (Agent 0B) refuted this:**
- `webui-config-schema` frontmatter `dependencies: []` — it is already a no-dep foundation.
- `harness/webui_config_schema.py` defines its OWN self-contained `PROVIDERS` table; it does
  NOT import `model_backends`. No circular import exists.
- It is already wired (control_gate.py imports it, commit 1fa09ea/06e2e55) and passes 8/9 oracle tests.

**Decision: do NOT invert. Instead DECOUPLE.** Neither oracle imports the other, so the
artificial `model-backends → config-schema` dependency is removed. Both become independent
foundations, each wired into `harness/control_gate.py` (the proven anchor), each buildable on its own.
Duplicate provider list across the two modules is an accepted, documented smell (unify later if wanted);
it does not block the owner's functional requirements (typed config + provider-locking + backend clients + codex).

## Revert decision for 06e2e55
**Fix-forward, do NOT revert.** 06e2e55 landed a wired, mostly-correct `webui_config_schema.py`
(8/9 oracle pass). The only defect is `validate_config` not propagating role-assigned provider
values into `ValidatedConfig.values`. Reverting throws away working wiring and invites synthesis
variance. Fix it via a re-plan of the (strengthened) config-schema brief — an EDIT to the
existing harness file (harness_self_fix, auto-approve posture ON).

## The two real blockers
1. **model-backends-impl** failed `ast_enforcer` security gate: "Hardcoded credential detected in
   variable 'key'" (`ast_enforcer.py:78` — `re.search('(?i)(password|secret|key)', target.id)` on a
   literal-valued assignment). The rebuilt brief MUST forbid assigning a string literal to ANY
   variable/module-constant whose name contains key/secret/password (this includes `API_KEY = "..."`,
   `key = env_val`, etc.). Read keys via `os.environ[...]`; name locals `env_name`/`cred_env` etc.;
   keep `api_key_env` only as a dataclass FIELD (keyword arg — not a Name assignment target, so safe).
2. **config-schema validate_config** drops role values — strengthen the brief to require writing each
   validated role assignment into `values[role.config_key]`.

## Oracle reconciliations needed (from Agent 0C)
- `tests/webui/test_config_schema.py`: required-providers set omits `gemini_api` though brief lists 8
  api-backed providers. Reconcile brief↔oracle (pick one; recommend include `gemini_api`).
- `tests/webui/test_model_backends.py`: asserts `BackendSpec.kind` (line ~62). Brief MUST embed
  `BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, ...)` contract verbatim.
- model-backends plan already produced two oracle tasks (model-backends-oracle + secrets-store-oracle) —
  plan shape is fine; both are currently dependency_failed-blocked and will regenerate on re-plan.

## Wave plan (decoupled)
- Wave 1 (parallel-safe, both foundations, both wire into control_gate.py):
  `webui-config-schema` (fix-forward edit) + `webui-model-backends` (rebuild AST-safe, decoupled).
- Wave 2: `webui-fs-browse` + `webui-typed-widgets` (EDIT live `tools/webui_server.py` /
  `tools/webui_control.py` / `tools/webui_static/app.js`; fs-browse MUST register the `/api/fs/list`
  route in the dispatch table AND have app.js actually call it).
- Wave 3: `webui-typed-config-e2e` (integration).
- Drive epic: held — OWNER-GATED (see below).

## Re-plan procedure (sanctioned; NOT sidecar-deletion-to-unstick)
For each leaf being re-authored: pause daemon → delete `plan_hooks_<slug>.json` + that leaf's staged
AND blocked tasks (`.json`/`.retry.json`/`.exhausted`) → `touch` the edited brief → commit the
edited brief+oracle BEFORE dispatch → allowlist the wave → resume. Only ever clears a leaf when no
dependent leaf is active (decoupled now, so safe).

## OWNER-GATED — surface and HOLD (do not auto-resolve)
1. Drive epic: needs `rclone` Google Drive remote (machine credential) + a `config/**` CONFIG_WIRED
   manifest (config/** edit = harness_self_fix + approval). Authorization required.
2. Codex CLI final wiring into `harness/orchestrator.py` + `harness/config.yaml` agents block —
   both `_NEVER_AUTO_APPROVE`, owner hand-edit only. Factory can only build a standalone backend
   registry + `agent_block()` dict.
3. Secret-store location: proposed `state/secrets/api_keys.json` (chmod 600, gitignored) vs env-file pointer.
4. B-research pricing came from search summaries (WebFetch was denied) — re-verify provider docs at wire-up.

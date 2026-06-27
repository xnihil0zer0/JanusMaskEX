# webui-typed-widgets — build orientation (2026-06-13)

## 1. Brief plan shape
brief_hooks_webui-typed-widgets.md has NO explicit "Required plan shape" section.
It mandates a SINGLE GREEN LEAF (one task), whole-file EDIT of three EXISTING live files:
- meta_task_type: implementation (multifile, whole-file edits; non-python app.js included)
- files_touched: tools/webui_control.py, tools/webui_server.py, tools/webui_static/app.js
- verification_command: `python -m pytest tests/webui/test_typed_widgets.py -q`
- mutation_target: ControlHandlers.get_config_schema / post_save_typed_config (the new methods)
- dependencies (brief frontmatter): webui-config-schema, webui-model-backends (BOTH BUILT)
SENSITIVE GLOBS: NONE touched. All three targets are tools/** (non-sensitive). Brief explicitly
forbids editing _NEVER_AUTO_APPROVE files (harness/orchestrator.py, autowork_daemon.py, etc.)
and forbids editing harness/config.yaml logic. No new module → only EDITs existing live files.

## 2. Oracle state — RED (impl not built), NOT import errors
`python -m pytest tests/webui/test_typed_widgets.py -q` → 6 failed, 1 passed in 0.46s.
The 1 pass is test_typed_save_requires_auth (route absent → auth prologue 401/403 by accident; will stay green).
Oracle imports: tools.webui_auth, tools.webui_server (srv), tools.webui_control.ControlHandlers.
Spins REAL stdlib sidecar (srv.WebUIServer/WebUIHandler/build_tailer) on ephemeral port in a thread,
ControlHandlers(state_dir, logs_dir, repo_root=tmp). Asserts:
- GET /api/config/schema → 200 {fields(list, dtype in {int,float,str,bool,path-file,path-dir,enum}),
  >=1 path-typed field; roles(list) with a dual role config_key==synthesis.active_agents;
  providers(dict) deepseek.api_backed==True, claude.api_backed==False; key "keys_present" present}
- POST /api/config/typed (token+nonce): valid sub (parallel_cap "7") → 200 + cfg autowork.parallel_cap==7
  AND poll_interval_sec==5 preserved (atomic merge); bad type ("not-an-int") → 400, body mentions
  parallel_cap, cfg byte-identical; dual-agent-same (["claude","claude"]) → 400;
  overseer.default_backend="deepseek" (keyless api) → 400; no-auth → 401/403.
- GET /static/app.js → 200 text MUST contain "/api/config/typed", a Browse affordance
  ("Browse" OR "fs-picker" OR "fs_picker"), and "/api/config/schema". (string-match only; no JS parse.)

## 3. Impl target — LIVE stdlib http.server, NOT the dead Flask webui/app.py
Edit ALL THREE: tools/webui_control.py (add ControlHandlers methods get_config_schema +
post_save_typed_config as ADDITIVE class nodes; extend _dispatch_post table line 116 with
'/api/config/typed': ('post_save_typed_config','body')); tools/webui_server.py (add ONE additive
literal branch in _dispatch_get @line412+ chain: path=='/api/config/schema' →
self.server.control.get_config_schema() → self._send_json); tools/webui_static/app.js (extend
pages.config, whole-file). app.js is verified by STRING match on served /static/app.js only — no JS execution/parse.
GETs do NOT go through _dispatch_post — schema route lives in webui_server.py _dispatch_get.

## 4. Wiring
No check_wired / route-registration test required by THIS oracle — it drives the live sidecar e2e
(real route hit proves wiring). NO orphan_unwired risk: leaf creates NO new module, only EDITs
3 already-live files. Wiring is intrinsic (dispatch-table entry + _dispatch_get branch + app.js fetch).

## 5. Gotchas
- never-patch-class-methods: get_config_schema/post_save_typed_config MUST be ADDITIVE nodes; do NOT
  rewrite existing ControlHandlers method bodies. _dispatch_post is a class-attr dict (extend, don't replace).
- AST credential gate (ast_enforcer.py:78): kills any Name-target literal assign matching (?i)key|secret|password.
  post_save handles api_key__* values — NEVER assign a key literal to a var named like *key*/*secret*; route
  values straight into save_secret(self.state_dir, env, value) call args. This killed model-backends before.
- validate_config keys CONFIG_FIELDS by SHORT name ('parallel_cap'); oracle submits short keys → direct match.
  validate_config(submitted, secrets=secrets) does BOTH cross-field rules (dual-same + keyless) internally →
  do NOT re-implement; just strip api_key__* keys before passing, then atomic_save_config(validated, repo_root/'harness'/'config.yaml').
- save_secret signature is save_secret(state_dir, env_name, value) — FIRST persist non-empty api_key__<ENV>,
  THEN load_secrets(self.state_dir), THEN validate. On ConfigValidationError → (400,{field_errors}) NO write.
- planner empty_plan/insufficient_unit_tests risk: oracle already exists+committed (7 tests). Brief is a
  single impl leaf w/ a verification_command — should plan fine; no test-authoring sub-task needed.
- multifile + non-python (app.js): needs whole-file manifest routing (_requires_verbatim_manifest);
  app.js is whole-file EDIT. No harness_self_fix needed (no harness/** or config/** edits).

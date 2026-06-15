---
complexity_score: 4
dependencies:
  - "webui-config-schema"
interfaces: "tools/webui_control.py: ControlHandlers.get_fs_list(query: dict) -> (200, {root, path, parent, entries:[{name, is_dir}]}) | (400, {error}) sandboxed to self.repo_root; rejects traversal/absolute/symlink-escape/non-dir. tools/webui_server.py: _dispatch_get route GET /api/fs/list?path=<dir>. tools/webui_static/app.js: an fs picker that GETs /api/fs/list, lists dir entries, navigates into subdirs / up to parent, and fills the path-typed config field that opened it."
---

# Title

EDIT (whole-file) `tools/webui_control.py` + `tools/webui_server.py` + `tools/webui_static/app.js` to add a sandboxed `GET /api/fs/list?path=` filesystem-browse endpoint (rooted at the control handlers' `repo_root`, traversal/symlink escape rejected) and a frontend picker that fills path-typed config fields. This targets the LIVE stdlib-http.server WebUI (`tools/webui_server.py`), NOT the dead Flask tree `webui/app.py`.

# Scope

This WebUI is a stdlib `http.server` sidecar (NOT Flask). Read-only GET routes are dispatched in `tools/webui_server.py:WebUIHandler._dispatch_get`; the directory-listing logic lives in `tools/webui_control.py:ControlHandlers` (which already owns `_resolve_inside`-style sandboxing precedents in `webui_server.py` and the `self.repo_root` sandbox root). The frontend is a vanilla-JS SPA in `tools/webui_static/`.

EDIT `tools/webui_control.py` (whole-file; NOT on `_NEVER_AUTO_APPROVE`), ADD a NEW `ControlHandlers` method as an ADDITIVE node (do NOT rewrite existing method bodies — never-patch-class-methods):
- `get_fs_list(self, query: dict) -> (int, dict)`: read the requested relative path from `query.get('path', [''])[0]` (query values arrive as `list[str]` from `parse_qs`, like the existing `_query()` consumers). Resolve it against the sandbox root `self.repo_root` (the repo root). Return `(200, {"root": str(self.repo_root), "path": <resolved-rel>, "parent": <rel-or-null>, "entries": [{"name", "is_dir"}, ...]})` sorted dirs-first. SANDBOX GUARD (document it in the docstring): resolve via `Path.resolve()` and reject — `(400, {...})` — any resolved path that is not `self.repo_root` or a descendant of it (so `..` traversal and absolute paths like `/etc` are refused); refuse to follow a symlink whose real target escapes the root (mirror the `_resolve_inside(base, child)` pattern in `webui_server.py`). A missing / non-existent / non-dir path → `(400, {...})` (or 403/404) with a clear message. Default (empty `path`) lists `self.repo_root`.

EDIT `tools/webui_server.py` (whole-file; NOT on `_NEVER_AUTO_APPROVE`), ADD ONE NEW route branch inside `WebUIHandler._dispatch_get` as an ADDITIVE node (do NOT rewrite the method wholesale): when `path == '/api/fs/list'`, call `self.server.control.get_fs_list(self._query())` and `self._send_json(status, body)`, mirroring the existing literal-route branches (`/api/config`, `/api/control/phases`). (GET /api/fs/list is read-only; auth-gated only when `auth_required_for_reads` is set, like every other GET.) Note `get_fs_list` may instead resolve the path itself from `self.path`; pass the parsed query dict.

EDIT `tools/webui_static/app.js` (whole-file): add a picker (a simple modal/inline panel + JS) that GETs `/api/fs/list`, renders entries, lets the user click into subdirectories (re-GET with the new `path`) and up to the `parent`, and on "Select" writes the chosen path into the config form field that opened it (the Browse button from `webui-typed-widgets` opens this picker). Native OS dialogs are impossible from browser JS, so this backend-driven picker is the substitute. Use the existing `api()` wrapper and `escape()`.

# Required plan shape

EXACTLY ONE task — do NOT split. The committed oracle (`tests/webui/test_fs_browse.py`) spins the LIVE sidecar in a thread and asserts across all three files together, so no per-file subtask independently satisfies it; a multi-task split is INVALID. Single `working_dir` (null). Emit this task verbatim in shape:

1. `task_id: "fs-browse-impl"`
   - `meta_task_type: "refactor"` (pure-edit of EXISTING files; all three targets already exist on disk; NOT `harness_self_fix` — every target is non-sensitive `tools/**`).
   - `spec_author: null` (REQUIRED field — emit exactly `null`, never omit it).
   - `priority: "high"`, `estimated_complexity: "medium"`.
   - `dependencies: []` — the dependency surface (`webui-config-schema`) is ALREADY BUILT + committed; it is a sibling leaf, NOT a task in this plan.
   - `files_touched: ["tools/webui_control.py", "tools/webui_server.py", "tools/webui_static/app.js"]` — three files incl. a non-`.py` target, so the orchestrator auto-routes this leaf to the verbatim whole-file `__JANUSMASK_MANIFEST__` apply: emit each file's COMPLETE new source. ADDITIVE — reproduce EVERY existing symbol/method body verbatim and add the new ones alongside; in `tools/webui_control.py` the new `def get_fs_list(self, query)` method body MUST be placed physically INSIDE the `class ControlHandlers` block (same indentation as existing methods), and in `tools/webui_server.py` the new `/api/fs/list` branch MUST be inside `_dispatch_get`. Verify your `webui_control.py` manifest value actually contains `def get_fs_list` before submitting.
   - `verification_command: "python -m pytest tests/webui/test_fs_browse.py -q"`.
   - `spec.non_goals` MUST include a line containing the literal word **integration** (excuses the per-task integration-test gate; the cross-leaf flow is covered by the separate `webui-typed-config-e2e` leaf and this leaf's oracle drives the live sidecar directly).

TEST-SPEC BALANCE (planner gates, all severity=error — satisfy ALL):
- `spec.functional_requirements`: a TIGHT list of EXACTLY 6: (1) `GET /api/fs/list` (no path) → 200 listing the sandbox root as `{root, path, parent, entries:[{name, is_dir}]}` dirs-first; (2) `?path=../..` and `?path=/etc` (traversal / absolute outside root) → 4xx; (3) a symlink whose target escapes the root is NOT followed → 4xx; (4) a non-existent path → 4xx; (5) a non-directory (file) path → 4xx; (6) `/static/app.js` GETs `/api/fs/list` (the picker wiring).
- `test_spec.unit_tests`: at least 6 entries (`len(unit_tests) >= len(functional_requirements)`) — ONE mapping each requirement above.
- `test_spec.edge_cases`: ≥2 entries, EACH mirrored in `regression_tests` OR `property_tests`: (a) empty/default `path` lists the root (not an error); (b) a path resolving exactly to the root boundary is allowed while one byte outside is refused.
- `test_spec.integration_tests`: MAY be empty ONLY because the gate is excused via the **integration** line in `spec.non_goals`.
- `test_spec.minimum_test_count`: >= 9 (>= `1.5 * len(functional_requirements)`).
- `token_budget_ratio.test_tokens` MUST be >= `1.5 * token_budget_ratio.implementation_tokens`.

# Non-Goals

No traversal outside `self.repo_root` under any input (the guard is the deliverable). No write/delete/exec filesystem operations — list-only, read-only. No rewriting of existing `ControlHandlers` method bodies or the `_dispatch_get` chain wholesale — add new method/route alongside (never-patch-class-methods; whole-file AST merge). No re-implementation of the typed-widget rendering (that is `webui-typed-widgets`; this leaf only supplies the endpoint + picker the Browse button calls). No Flask, no `webui/app.py`, no `webui/templates/` — that is the dead tree. No edits to any `_NEVER_AUTO_APPROVE` file (`harness/orchestrator.py`, `harness/autowork_daemon.py`, `harness/git_integration.py`, `harness/paths.py`, `harness/interceptors.py`, `harness/selfheal.py`, `harness/agent_jail.py`, `harness/dbus_proxy.py`, `services/**`). WebUI stays loopback-only; token + CSRF posture unchanged. integration: endpoint behaviour is exercised on the live sidecar by this leaf's oracle; the cross-leaf flow is `webui-typed-config-e2e`.

# Inputs

- `tools/webui_control.py`: `ControlHandlers.__init__(..., repo_root=None)` → `self.repo_root` (the sandbox root, defaulting to the JanusMask repo root); `self.state_dir`; the class-attribute dispatch tables (no new dispatch entry needed — this is a GET, served by `webui_server.py`).
- `tools/webui_server.py`: `WebUIHandler._dispatch_get` literal-route chain (`/api/config` etc.); `_query()` (returns `parse_qs` dict of `list[str]`); `_resolve_inside(self, base: Path, child: Path) -> Optional[Path]` (the existing resolve-then-`relative_to`-base sandbox guard to mirror); `_send_json`.
- Browse-button target id is emitted by `webui-typed-widgets`'s `app.js` config view (the picker id / field the Browse button targets).
- Frontend: `tools/webui_static/app.js` — `api(path, opts)`, `escape()`, `toast()`, `styles.css` classes; served by `_handle_static`.
- Test harness precedent: `tests/integration/test_webui_server.py` (thread-on-ephemeral-port sidecar fixture, `urllib.request` GET helper, `ControlHandlers` constructed with `repo_root=` to sandbox the browse root).
- Committed oracle (contract): `tests/webui/test_fs_browse.py`.

# Deliverables

ONE GREEN leaf: `tools/webui_control.py` (whole-file EDIT) + `tools/webui_server.py` (whole-file EDIT) + `tools/webui_static/app.js` (whole-file EDIT) verified by `python -m pytest tests/webui/test_fs_browse.py -q`. Frozen surface: `GET /api/fs/list?path=` returns sandboxed JSON dir entries (`{root, path, parent, entries:[{name, is_dir}]}`) rooted at `self.repo_root`; traversal (`..`, absolute `/etc`), symlink-escape, and non-dir paths are rejected with 4xx. The oracle spins up the real sidecar in a thread, points `ControlHandlers` at a sandbox `repo_root`, and asserts: listing the root returns entries incl. known seeded dirs (each with `name` + `is_dir`); `?path=../..` or `?path=/etc` returns 4xx; a symlink inside the root pointing outside is not followed; a non-existent path and a file (non-dir) path are rejected; and `/static/app.js` GETs `/api/fs/list` from the picker.

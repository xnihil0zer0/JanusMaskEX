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

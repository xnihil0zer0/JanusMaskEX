"""Adversarial bars for the session #28 operator status panel.

Regression guards (plain, non-xfail — landed via reviewed direct edit) for:
- **WUI-REPL1**: every stale "all fresh briefs eligible" string in app.js is
  gone, replaced by the deny-all wording (a missing/empty allowlist denies all).
- **WUI-2**: app.js renders a per-brief "zombie: N parked" badge + a
  "dispatchable" summary pill, both fed by the new
  ``compute_autowork_eligibility`` ``parked``/``dispatchable`` fields.
- **WUI-3**: app.js renders a per-row Re-queue button on processed/blocked task
  rows, stripping the ``.json`` suffix before calling
  ``decideTaskApproval(id,'retry')``.
- **static no-cache**: the WebUI dev server sends ``Cache-Control: no-cache`` on
  the SPA shell + static assets so an operator never sees a stale UI after a code
  update (the exact footgun that masked the panel during #28 verification).
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "tools" / "webui_static" / "app.js"
SERVER_PY = REPO_ROOT / "tools" / "webui_server.py"


def test_app_js_drops_stale_eligible_string() -> None:
    src = APP_JS.read_text(encoding="utf-8")
    assert "all fresh briefs eligible" not in src, (
        "WUI-REPL1: stale 'all fresh briefs eligible' string still present in app.js"
    )
    assert src.count("deny-all (nothing dispatches)") >= 3, (
        "WUI-REPL1: expected the deny-all wording in >=3 spots (summary, loader, save toast)"
    )


def test_app_js_renders_zombie_and_dispatchable() -> None:
    src = APP_JS.read_text(encoding="utf-8")
    assert "parkedMap" in src and "zombie:" in src, "WUI-2: zombie badge missing"
    assert "dispatchable" in src, "WUI-2: dispatchable pill missing"


def test_app_js_requeue_button_strips_json_suffix() -> None:
    src = APP_JS.read_text(encoding="utf-8")
    assert "data-requeue" in src, "WUI-3: Re-queue button missing"
    assert 'decideTaskApproval(btn.dataset.requeue, "retry")' in src, (
        "WUI-3: Re-queue button must call decideTaskApproval(...,'retry')"
    )
    # the task list 'name' carries the .json suffix; the button must strip it
    # or _maybe_requeue_task looks for '<id>.json.json' and silently no-ops.
    assert ".replace(/\\.json$/" in src, (
        "WUI-3: Re-queue id must strip the trailing .json suffix"
    )


def test_app_js_parses_as_module() -> None:
    """Cheap syntax sanity without a node dependency: balanced braces/parens and
    the new functions are present. (node --check is run in the vcmd; this guards
    against a gross edit error landing.)"""
    src = APP_JS.read_text(encoding="utf-8")
    assert src.count("{") == src.count("}"), "app.js brace mismatch"
    assert 'pages["tasks/list"]' in src


def test_server_static_sends_no_cache() -> None:
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_send_bytes" in funcs
    sig = funcs["_send_bytes"]
    assert any(a.arg == "cache_control" for a in sig.args.args), (
        "_send_bytes must accept a cache_control kwarg"
    )
    for handler in ("_handle_static", "_handle_root"):
        assert handler in funcs, f"{handler} missing"
        body = ast.unparse(funcs[handler])
        assert "cache_control='no-cache'" in body or 'cache_control="no-cache"' in body, (
            f"{handler} must send Cache-Control: no-cache"
        )

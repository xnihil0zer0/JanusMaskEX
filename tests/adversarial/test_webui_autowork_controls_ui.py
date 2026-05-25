"""Adversarial bar for webui_autowork_controls_ui.

xfail-strict until the webui_autowork_controls_ui dispatch adds the autowork
allowlist editor + four orphan-endpoint handlers to
``tools/webui_static/app.js``. On accept, drop the xfail markers so these
become regression guards.

Supersedes tests/adversarial/test_webui_orphan_endpoints_ui.py (that brief
failed dispatch on a null meta_task_type; the JS submission was rejected by
the Python fuzzer). All assertions are pure string/regex presence checks.
"""

from __future__ import annotations

import pathlib
import re

import pytest

APP_JS_PATH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "webui_static" / "app.js"


def _src() -> str:
    return APP_JS_PATH.read_text(encoding="utf-8")


def test_allowlist_load_save_handlers_present():
    src = _src()
    assert "/api/autowork/allowlist" in src
    assert "loadAutoworkAllowlist" in src
    assert "saveAutoworkAllowlist" in src


def test_extract_plan_to_queue_present():
    src = _src()
    assert "/api/plans/" in src
    assert "/extract" in src
    assert "extractPlanToQueue" in src


def test_decide_task_approval_present():
    src = _src()
    assert re.search(r"/api/tasks/.+/(approve|reject|retry)", src) is not None
    assert "decideTaskApproval" in src


def test_kill_agent_present():
    src = _src()
    assert "/api/agents/" in src
    assert "/kill" in src
    assert "killAgent" in src


def test_update_config_control_present():
    src = _src()
    assert "/api/config/control" in src
    assert "updateConfigControl" in src


def test_all_endpoint_urls_present():
    src = _src()
    for frag in ("/api/autowork/allowlist", "/api/plans/", "/extract",
                 "/api/agents/", "/kill", "/api/config/control"):
        assert frag in src, frag


def test_api_wrapper_preserved():
    # regression guard (always-on): the api() wrapper must survive the
    # whole-file verbatim replace performed by the app.js dispatch.
    assert "function api(" in _src()

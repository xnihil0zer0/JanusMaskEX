"""Adversarial bar for autowork_allowlist_endpoint.

xfail-strict until the autowork_allowlist_endpoint dispatch adds the
GET/PUT allowlist CRUD handlers to ``tools/webui_control.py``. On accept,
drop the xfail markers so these become regression guards.

The handlers manage ``<state_dir>/control/autowork/auto_promote.allowlist``
— the autowork daemon's safety boundary (see
``harness/autowork_daemon.py:_auto_promote_allowlist``). Empty-list PUT
deletes the file (revert to "run all fresh briefs").
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from tools.webui_control import ControlHandlers


def _handlers() -> tuple[ControlHandlers, pathlib.Path]:
    d = pathlib.Path(tempfile.mkdtemp())
    return ControlHandlers(d, d), d


def test_put_then_get_roundtrip():
    h, d = _handlers()
    st, b = h.put_autowork_allowlist({"slugs": ["foo_bar", "baz"]})
    assert st == 200, b
    al = d / "control" / "autowork" / "auto_promote.allowlist"
    assert al.exists(), "allowlist file not written"
    st, b = h.get_autowork_allowlist()
    assert st == 200, b
    assert set(b["slugs"]) == {"foo_bar", "baz"}, b
    assert b["file_present"] is True, b


def test_empty_list_deletes_file():
    h, d = _handlers()
    h.put_autowork_allowlist({"slugs": ["alpha"]})
    al = d / "control" / "autowork" / "auto_promote.allowlist"
    assert al.exists()
    st, b = h.put_autowork_allowlist({"slugs": []})
    assert st == 200, b
    assert not al.exists(), "empty-list PUT must delete the file"
    assert b["file_present"] is False, b


def test_get_absent_file_returns_empty():
    h, _ = _handlers()
    st, b = h.get_autowork_allowlist()
    assert st == 200, b
    assert b["slugs"] == [], b
    assert b["file_present"] is False, b


def test_invalid_slug_rejected():
    h, _ = _handlers()
    st, b = h.put_autowork_allowlist({"slugs": ["Bad Slug"]})
    assert st == 400, b
    st, b = h.put_autowork_allowlist({"slugs": "notalist"})
    assert st == 400, b
    st, b = h.put_autowork_allowlist("notadict")
    assert st == 400, b


def test_put_route_registered_in_dispatch_put():
    assert "/api/autowork/allowlist" in ControlHandlers._dispatch_put
    method_name, arg_shape = ControlHandlers._dispatch_put["/api/autowork/allowlist"]
    assert method_name == "put_autowork_allowlist"
    assert arg_shape == "body"
    # existing routes preserved
    assert "/api/config/control" in ControlHandlers._dispatch_put
    assert "/api/config/autowork" in ControlHandlers._dispatch_put

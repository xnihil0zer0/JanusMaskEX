"""RED oracle for the tools/webui_control.py EDIT leaf (harness_plumbing).

THIN wiring: register the overseer chat MUTATION routes in the existing
ControlHandlers class-attribute dispatch tables and add NEW handler methods that
DELEGATE to overseer.web_api (no rewrite of existing method bodies). Mirrors the
AW5a autowork-route extension precedent.
"""
import inspect

from tools.webui_control import ControlHandlers

NEW_POST_ROUTES = {"/api/chat/send", "/api/chat/resend"}


def test_new_chat_post_routes_are_registered():
    for route in NEW_POST_ROUTES:
        assert route in ControlHandlers._dispatch_post, f"missing POST route {route}"


def test_registered_routes_point_at_real_handler_methods():
    for route in NEW_POST_ROUTES:
        handler_name, _arg_shape = ControlHandlers._dispatch_post[route]
        assert hasattr(ControlHandlers, handler_name), f"no method {handler_name}"
        assert callable(getattr(ControlHandlers, handler_name))


def test_chat_mode_mutation_route_exists():
    # A mode change is a mutation — registered under POST or PUT.
    combined = {**ControlHandlers._dispatch_post, **ControlHandlers._dispatch_put}
    assert any("chat/mode" in r for r in combined), "no chat mode-set route"


def test_chat_handlers_delegate_to_overseer_web_api():
    # Thin wiring: the handler body must route into overseer.web_api, not
    # reimplement the logic inline.
    for route in NEW_POST_ROUTES:
        handler_name, _ = ControlHandlers._dispatch_post[route]
        src = inspect.getsource(getattr(ControlHandlers, handler_name))
        assert "web_api" in src, f"{handler_name} does not delegate to overseer.web_api"


def test_existing_routes_are_preserved():
    # The edit is additive — pre-existing control routes must survive the merge.
    for route in ("/api/briefs", "/api/autowork/start", "/api/rebuild/start"):
        assert route in ControlHandlers._dispatch_post

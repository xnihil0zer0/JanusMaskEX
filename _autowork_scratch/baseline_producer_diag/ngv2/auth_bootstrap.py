"""auth/state bootstrap module for source-driving PoCs (Leaf 7).

Returns an authenticated framework test client for a target web app so a
source-driving PoC (Leaf 4b's test-client driver) can reach routes behind a
login. Importing this module is cheap: the target's framework (flask /
starlette) is imported lazily inside the functions, never at module load.

Self-contained: wiring this into the detonate seam is a later leaf.
"""
from __future__ import annotations
from dataclasses import dataclass, field
__all__ = ['AuthSpec', 'is_auth_required', 'bootstrap_auth']

@dataclass
class AuthSpec:
    """Describes how to authenticate against a target app.

    An empty ``login_route`` means "no auth required".
    """
    login_route: str = ''
    http_method: str = 'POST'
    credentials: dict = field(default_factory=dict)
    framework: str = 'flask'

def is_auth_required(spec: AuthSpec | None) -> bool:
    """True iff spec is not None and has a non-empty login_route."""
    return spec is not None and bool(getattr(spec, 'login_route', ''))

def _build_client(app, framework: str) -> object:
    """Build a plain framework test client for app (function-local imports)."""
    fw = (framework or 'flask').lower()
    if fw in ('fastapi', 'starlette'):
        from starlette.testclient import TestClient
        return TestClient(app)
    return app.test_client()

def bootstrap_auth(app, spec: AuthSpec | None=None) -> object:
    """Return a framework test client for app.

    When is_auth_required(spec), perform the login by sending spec.credentials
    to spec.login_route via spec.http_method so the returned client retains the
    session cookie. Otherwise return a plain pass-through client. Fail-soft: on
    any login error return the plain client (never raise) so the caller
    degrades to unauthenticated.
    """
    framework = getattr(spec, 'framework', 'flask') if spec is not None else 'flask'
    client = _build_client(app, framework)
    if not is_auth_required(spec):
        return client
    try:
        method = (getattr(spec, 'http_method', 'POST') or 'POST').lower()
        send = getattr(client, method, None)
        if send is not None:
            send(spec.login_route, data=spec.credentials)
        else:
            client.post(spec.login_route, data=spec.credentials)
    except Exception:
        return client
    return client
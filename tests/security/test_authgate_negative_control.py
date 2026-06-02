"""Hermetic negative-control oracle for the filtered D-Bus proxy (REV21 §3(d)).

This is the COMMITTABLE, hermetic half of the AUTHGATE-HARDEN completion. It
inspects the proxy filter policy DIRECTLY -- the pure function
``harness.dbus_proxy.build_proxy_argv`` -- with NO live session bus and NO real
``xdg-dbus-proxy`` spawn, so it never flakes a worker's verification run.

WHY THIS EXISTS (a3c6669 caveat, REV21 §3(d), agy R1 §2.6)
----------------------------------------------------------
The auth test landed in a3c6669 is partially VACUOUS: it pings
``org.freedesktop.DBus.Peer.Ping`` to prove keyring reachability and never
forces a token refresh, so an OAuth credential cache-hit yields a false GREEN.
The plan asks for two strengtheners; this module delivers the hermetic one.

(i) LIVE token-refresh -- NOT a committed assertion (documented procedure only)
    To genuinely exercise the keyring round-trip over the FILTERED bus (defeating
    a cache-hit false-GREEN), run the live auth gate with CLEARED Google OAuth
    credentials so a real refresh is forced through the filtered proxy:

        mv ~/.gemini/oauth_creds.json ~/.gemini/oauth_creds.json.bak   # clear cache
        python ~/janusmask_briefs/sec1c_spawn_authgate.py             # forces refresh
        mv ~/.gemini/oauth_creds.json.bak ~/.gemini/oauth_creds.json   # restore

    A PONG after a forced refresh proves org.freedesktop.secrets really survives
    the filter. This needs live Google OAuth + cleared creds, is NOT hermetic,
    and is therefore deliberately left out of the committed assertions.

(ii) NEGATIVE CONTROL -- the hermetic committable part below.
    A *filtered* bus must be distinguishable from an *unfiltered* (pass-through)
    bus: it must DENY org.freedesktop.systemd1 / StartTransientUnit (the
    containment-escape vector) while ALLOWING org.freedesktop.secrets (the
    keyring needed for agy's OAuth refresh). These tests assert exactly that on
    the policy argv.

RED-ON-HEAD vs REGRESSION-GUARD (non-vacuity)
---------------------------------------------
On HEAD, ``build_proxy_argv`` ALREADY omits any systemd1 grant (SEC-1a built the
filter), so the policy assertions PASS on HEAD: this is a GREEN regression-guard,
not a RED-on-HEAD detector -- which is acceptable for a test_authoring negative
control (it pins the filter so a future relax is caught).

To prove it is NOT vacuous, ``test_negative_control_is_non_vacuous`` re-runs the
identical policy assertions against an INTENTIONALLY-WEAKENED argv (the real argv
plus a ``--talk=org.freedesktop.systemd1`` grant) and asserts that the systemd1
check FAILS on it. So if a future edit ever adds a systemd1 grant or a broad
wildcard to ``build_proxy_argv``, ``test_policy_denies_systemd1`` /
``test_policy_no_broad_wildcard`` go RED. The transient-delete proof was also
run by the brief author: removing ``--filter`` / adding the systemd1 grant in the
worktree turns these tests RED, and restoring returns them GREEN.
"""

import pytest

from harness.dbus_proxy import build_proxy_argv


REAL = "/run/user/1000/bus"
SOCK = "/tmp/janusmask-authgate-negctrl.sock"


_DENY_NAME = "org.freedesktop.systemd1"
_ALLOW_NAME = "org.freedesktop.secrets"
_GRANT_FLAGS = ("--talk=", "--own=", "--call=", "--see=")


def _assert_filter_enabled(argv):
    """A filtered bus MUST pass --filter; without it the proxy is a transparent
    pass-through and StartTransientUnit on systemd1 is reachable."""
    assert "--filter" in argv, "policy must run xdg-dbus-proxy in --filter mode"


def _assert_secrets_allowed(argv):
    """The keyring (Secret Service) MUST be talkable for agy's OAuth refresh."""
    assert ("--talk=" + _ALLOW_NAME) in argv, (
        "keyring talk grant (--talk=%s) is required for OAuth" % _ALLOW_NAME
    )


def _assert_systemd1_denied(argv):
    """No token may grant talk/own/call/see to systemd1 and nothing may mention
    StartTransientUnit -- either would reopen the containment escape."""
    for tok in argv:
        assert "StartTransientUnit" not in tok, (
            "no token may reference StartTransientUnit: %r" % (tok,)
        )
        if tok.startswith(_GRANT_FLAGS):
            name = tok.split("=", 1)[1]
            assert _DENY_NAME not in name, (
                "policy must NOT grant %s access to systemd1 (escape): %r"
                % (tok.split("=", 1)[0], tok)
            )


def _assert_no_broad_wildcard(argv):
    """No broad wildcard grant: a wildcard would transitively re-grant systemd1
    and defeat the filter. Only org.freedesktop.secrets may be talkable."""
    for tok in argv:
        assert tok not in ("--talk=*", "--own=*", "--call=*", "--see=*"), (
            "broad wildcard grant forbidden: %r" % (tok,)
        )
        if tok.startswith(_GRANT_FLAGS):
            name = tok.split("=", 1)[1]
            assert "*" not in name, "wildcard in grant name forbidden: %r" % (tok,)
        if tok.startswith("--talk="):
            assert tok == "--talk=" + _ALLOW_NAME, (
                "only %s may be talkable; got %r" % (_ALLOW_NAME, tok)
            )


def test_policy_enables_filter():
    """Negative control: the policy distinguishes a filtered bus from a
    pass-through by carrying --filter."""
    _assert_filter_enabled(build_proxy_argv(REAL, SOCK))


def test_policy_allows_secrets():
    """The keyring/OAuth interface stays reachable through the filter."""
    _assert_secrets_allowed(build_proxy_argv(REAL, SOCK))


def test_policy_denies_systemd1():
    """The systemd1 manager / StartTransientUnit escape is not granted."""
    _assert_systemd1_denied(build_proxy_argv(REAL, SOCK))


def test_policy_no_broad_wildcard():
    """No broad wildcard re-grants systemd1; only secrets is talkable."""
    _assert_no_broad_wildcard(build_proxy_argv(REAL, SOCK))


def test_policy_references_both_paths():
    """The policy targets the real bus (proxied address) and the listen socket."""
    argv = build_proxy_argv(REAL, SOCK)
    joined = "\n".join(argv)
    assert REAL in joined, "real bus path must appear in the policy argv"
    assert SOCK in joined, "proxy socket path must appear in the policy argv"


def test_negative_control_is_non_vacuous():
    """Prove the systemd1/wildcard assertions actually bite.

    This guards against a vacuous green: it takes the REAL policy argv, injects a
    systemd1 talk grant + a broad wildcard, and asserts that the deny/wildcard
    checks FAIL on the weakened argv. If the assertions were vacuous (e.g. they
    never inspected grant tokens), this test would itself fail.
    """
    weakened = list(build_proxy_argv(REAL, SOCK)) + [
        "--talk=" + _DENY_NAME,
        "--talk=*",
    ]
    with pytest.raises(AssertionError):
        _assert_systemd1_denied(weakened)
    with pytest.raises(AssertionError):
        _assert_no_broad_wildcard(weakened)

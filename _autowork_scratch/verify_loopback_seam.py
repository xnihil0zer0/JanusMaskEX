"""Adversarial verification of the LoopbackListener wiring in
ngv2/workers/_runner.py::_make_detonation_seam.

Drives the LIVE seam closure with an INJECTED jail_runner stub that simulates
a jailed PoC reading NGV2_SSRF_CALLBACK from its child_env and issuing the
loopback callback. Tests positive capture, negative (no callback / altered
nonce), determinism of nonce derivation, listener lifecycle, and that NO
expected_fs_signature is required for an SSRF confirm.

NOTE: this uses an injected jail_runner stub (in-process), NOT a real bwrap
--unshare-net jailed PoC. Real jailed-PoC reachability to a HOST listener is a
separate follow-on and is NOT demonstrated here.
"""
import sys
import json
import threading
import urllib.request

sys.path.insert(0, "/home/xnihil0zer0/NobleGreedv2")

from ngv2.workers._runner import _make_detonation_seam  # noqa: E402
from ngv2.loopback_listener import LoopbackListener  # noqa: E402

results = {}

# Build the LIVE production seam closure.
seam = _make_detonation_seam()
assert callable(seam), "seam closure is not callable"
results["seam_callable"] = True


def make_jail_runner(behavior):
    """Returns a jail_runner stub matching detonate_live's contract:
        jail_runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s) -> dict
    The stub simulates the jailed PoC: it reads NGV2_SSRF_CALLBACK from
    child_env and (depending on behavior) issues the loopback callback. We
    record what env the child actually received for inspection.
    """
    captured = {}

    def jail_runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s):
        captured["child_env"] = dict(child_env)
        cb = child_env.get("NGV2_SSRF_CALLBACK")
        nonce = child_env.get("NGV2_SSRF_NONCE")
        captured["callback"] = cb
        captured["nonce"] = nonce
        if behavior == "callback" and cb:
            try:
                urllib.request.urlopen(cb, timeout=2).read()
            except Exception as e:  # pragma: no cover
                captured["callback_error"] = str(e)
        elif behavior == "altered_nonce" and cb:
            # hit the listener but with a WRONG nonce path
            base = cb.rsplit("/", 1)[0]
            try:
                urllib.request.urlopen(base + "/WRONG_NONCE_XYZ", timeout=2).read()
            except Exception as e:  # pragma: no cover
                captured["callback_error"] = str(e)
        # behavior == "silent": issue no callback at all
        # Return a non-fs verdict (e.g. SSRF: no filesystem write at all)
        return {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False}

    return jail_runner, captured


# A PoC dict carrying a finding id and NO expected_fs_signature (SSRF/read-only).
def make_poc(fid):
    return {
        "code": "print('poc stub')\n",  # actual code irrelevant; jail_runner is stubbed
        "id": fid,
    }


# ---- POSITIVE: stub issues the loopback callback -> ssrf_channel confirm ----
jr_pos, cap_pos = make_jail_runner("callback")
poc = make_poc("F-CWE918-001")
res_pos = seam(poc=poc, finding=poc, jail_runner=jr_pos)
results["positive"] = {
    "result": res_pos,
    "child_env_ssrf": {
        "NGV2_SSRF_CALLBACK": cap_pos.get("callback"),
        "NGV2_SSRF_NONCE": cap_pos.get("nonce"),
    },
}

# ---- POSITIVE-2 same finding_id again: nonce/callback must be DETERMINISTIC ----
jr_pos2, cap_pos2 = make_jail_runner("callback")
res_pos2 = seam(poc=make_poc("F-CWE918-001"), finding=make_poc("F-CWE918-001"), jail_runner=jr_pos2)
results["determinism"] = {
    "first_nonce": cap_pos.get("nonce"),
    "second_nonce": cap_pos2.get("nonce"),
    "nonce_stable": cap_pos.get("nonce") == cap_pos2.get("nonce"),
    # callback urls differ only in ephemeral port; compare the nonce path tail
    "first_cb_path": (cap_pos.get("callback") or "").rsplit("/", 1)[-1],
    "second_cb_path": (cap_pos2.get("callback") or "").rsplit("/", 1)[-1],
    "cb_path_stable": (cap_pos.get("callback") or "").rsplit("/", 1)[-1]
    == (cap_pos2.get("callback") or "").rsplit("/", 1)[-1],
}

# ---- DISTINCT finding_id -> distinct nonce (not a constant) ----
jr_diff, cap_diff = make_jail_runner("callback")
res_diff = seam(poc=make_poc("F-CWE89-XYZ"), finding=make_poc("F-CWE89-XYZ"), jail_runner=jr_diff)
results["distinct_id"] = {
    "id_A_nonce": cap_pos.get("nonce"),
    "id_B_nonce": cap_diff.get("nonce"),
    "distinct": cap_pos.get("nonce") != cap_diff.get("nonce"),
}

# ---- NEGATIVE-1: stub issues NO callback -> no ssrf confirm ----
jr_silent, cap_silent = make_jail_runner("silent")
res_silent = seam(poc=make_poc("F-CWE918-001"), finding=make_poc("F-CWE918-001"), jail_runner=jr_silent)
results["negative_silent"] = {"result": res_silent}

# ---- NEGATIVE-2: stub hits listener with WRONG nonce -> no ssrf confirm ----
jr_alt, cap_alt = make_jail_runner("altered_nonce")
res_alt = seam(poc=make_poc("F-CWE918-001"), finding=make_poc("F-CWE918-001"), jail_runner=jr_alt)
results["negative_altered_nonce"] = {"result": res_alt}

# ---- LISTENER LIFECYCLE: count live LoopbackListener server threads after runs ----
# A leaked listener would keep a serve_forever daemon thread alive. Inspect threads.
live_threads = [t.name for t in threading.enumerate()]
results["threads_after_runs"] = live_threads
# Also: directly assert a fresh listener stops cleanly (sanity for the API used).
lst = LoopbackListener(host="127.0.0.1", port=0)
lst.start()
port = lst.port
lst.stop()
# After stop, connecting should fail (socket closed).
import socket  # noqa: E402

sock_err = None
try:
    s = socket.create_connection(("127.0.0.1", port), timeout=1)
    s.close()
    sock_err = "STILL_OPEN"
except Exception as e:
    sock_err = type(e).__name__
results["listener_stop_socket_state"] = {"port": port, "after_stop_connect": sock_err}

print(json.dumps(results, indent=2, default=str))

"""ngv2/_loopback_netns.py -- in-jail bootstrap that co-locates the loopback
listener and the PoC inside ONE isolated network namespace (P1.3 leaf-2).

OWNER-HAND-AUTHORED, irreducible-tier infrastructure (same tier as
``poc_runner_live.py``). This module is the *inside-the-jail* half of the
shared-loopback-netns detonation path: it runs as ``python3 -m ngv2._loopback_netns``
as the FIRST process of a bubblewrap jail that OWNS a fresh user+network namespace
(``--unshare-user --unshare-net --cap-add CAP_NET_ADMIN``). Inside that netns it:

  1. brings the ``lo`` interface UP via a pure-Python ``ioctl(SIOCSIFFLAGS,
     IFF_UP|IFF_RUNNING)`` -- NO dependency on the ``ip`` binary (DESIGN.md Probe J1);
  2. starts the host-authored :class:`ngv2.loopback_listener.LoopbackListener`
     bound to ``127.0.0.1`` *inside this netns*, on the port handed in by the parent;
  3. runs the attacker-controlled PoC as a SEPARATE child process (its own address
     space) in the same netns, so the PoC's ``http://127.0.0.1:<port>/<nonce>``
     callback reaches the listener over one shared loopback stack;
  4. reports the listener hits + the PoC run fields back to the parent over stdout
     as a single ``__NGV2_LOOPBACK_RESULT__ <json>`` sentinel line.

Why the listener lives in-jail rather than the parent: the parent runs in the HOST
netns; a ``--unshare-net`` PoC gets a DIFFERENT loopback stack, so a host-side
listener is unreachable (the leaf-2 defect). Putting BOTH peers in the one jailed
netns is the only model that lets a REAL jailed PoC confirm via the nonce callback
while keeping outbound blocked (the netns has only ``lo``: no ``eth*``, no route).

Security invariants (load-bearing):
  * **Outbound stays blocked.** The netns contains only ``lo``; there is no route
    off-host. (DESIGN.md Probe F.)
  * **No process-memory crossover.** The PoC is a child subprocess; under the host's
    restricted-ptrace policy a child cannot read its parent's memory, so a PoC RCE
    cannot reach the listener's address space.
  * **Fail-closed.** If ``lo`` cannot be brought up, this bootstrap exits non-zero
    with a diagnostic; the parent (``poc_runner_live.run_jailed_poc_with_loopback``)
    treats a missing result sentinel as a hard failure and raises ``LiveRunnerError``
    rather than degrading to a host-netns/outbound-open path.

This module is impure by design (ioctl, sockets, subprocess) and is NOT imported by
the stdlib-only ``ngv2`` core paths; it is only ever exec'd as the jail entrypoint.
"""
from __future__ import annotations
import fcntl
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
from typing import Mapping
from typing import Optional
from typing import Sequence

try:
    from ngv2.loopback_listener import LoopbackListener
except Exception:  # pragma: no cover - standalone import fallback when ngv2 pkg root differs
    from loopback_listener import LoopbackListener  # type: ignore

# ioctl constants (linux/sockios.h, net/if.h). Stable on Linux.
_SIOCGIFFLAGS = 0x8913
_SIOCSIFFLAGS = 0x8914
_IFF_UP = 0x1
_IFF_RUNNING = 0x40
_IFNAME = b"lo"

# The sentinel line the parent greps stdout for. A run that does not emit it is a
# hard failure (fail-closed): the parent raises rather than guessing a verdict.
RESULT_SENTINEL = "__NGV2_LOOPBACK_RESULT__"

# Matches a concrete loopback callback base the parent may have staged with its own
# (host-netns) listener port, so we can re-point it at the in-netns listener.
_LOOPBACK_URL_RE = re.compile(r"http://127\.0\.0\.1:\d+/")


class LoopbackNetnsError(RuntimeError):
    """Raised inside the jail when the shared-loopback netns cannot be set up."""


def bring_lo_up(ifname: bytes = _IFNAME) -> None:
    """Bring the ``lo`` interface UP via a pure-Python ``ioctl`` (no ``ip`` binary).

    Reads the current interface flags (``SIOCGIFFLAGS``), ORs in
    ``IFF_UP|IFF_RUNNING`` and writes them back (``SIOCSIFFLAGS``). Requires
    ``CAP_NET_ADMIN`` in the owning netns (the jail grants it via ``--cap-add``).
    Raises :class:`LoopbackNetnsError` on any failure -- the caller fails closed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifr = struct.pack("16sh", ifname, 0)
        res = fcntl.ioctl(sock.fileno(), _SIOCGIFFLAGS, ifr)
        flags = struct.unpack("16sh", res)[1]
        flags |= _IFF_UP | _IFF_RUNNING
        ifr = struct.pack("16sh", ifname, flags)
        fcntl.ioctl(sock.fileno(), _SIOCSIFFLAGS, ifr)
    except OSError as exc:
        raise LoopbackNetnsError(
            f"failed to bring '{ifname.decode()}' up via ioctl "
            f"(CAP_NET_ADMIN missing in netns?): {exc}"
        ) from exc
    finally:
        sock.close()


def _run_poc_child(
    cmd: Sequence[str], work_dir: str, child_env: Mapping[str, str], timeout_s: float
) -> dict:
    """Run the PoC as a separate child process in the shared netns; capture fields.

    Returns ``{exit_code, stdout, stderr, timed_out}`` -- the same run-field shape
    the legacy ``_default_jail_runner`` returns -- so the parent's FS-snapshot and
    verdict logic is unchanged. Never raises for PoC-side failures.
    """
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=work_dir,
            env=dict(child_env),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        out = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        err = (
            exc.stderr.decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        # 124 mirrors poc_runner_live.TIMEOUT_EXIT_CODE without importing it.
        return {"exit_code": 124, "stdout": out, "stderr": err, "timed_out": True}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """In-jail entrypoint. Config is read from a single JSON file path in argv[1].

    Expected config JSON keys::

        {
          "cmd":         [<interpreter>, <poc_path>, ...],   # the in-jail PoC argv
          "work_dir":    "<abs path>",                       # writable scratch (bound)
          "child_env":   {<env for the PoC subprocess>},     # PATH/HOME/PYTHONPATH/...
          "timeout_s":   <float>,                            # PoC wall-clock bound
          "listener_port": <int>,                            # 0 => ephemeral
          "fs_signature": "<sentinel name>",                 # listener sentinel (or "")
          "callback_env_keys": ["NGV2_SSRF_CALLBACK", ...]   # env keys to rewrite to the
                                                             #   bound listener port
        }

    On success prints exactly one ``__NGV2_LOOPBACK_RESULT__ <json>`` line and
    returns 0. On a setup failure (cannot bring ``lo`` up / bind the listener)
    returns non-zero WITHOUT the sentinel, so the parent fails closed.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write("loopback-netns bootstrap: missing config path\n")
        return 2
    try:
        with open(args[0], "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - any config read error fails closed
        sys.stderr.write(f"loopback-netns bootstrap: bad config: {exc}\n")
        return 2

    try:
        bring_lo_up()
    except LoopbackNetnsError as exc:
        sys.stderr.write(f"loopback-netns bootstrap: {exc}\n")
        return 3

    work_dir = str(cfg.get("work_dir") or os.getcwd())
    listener = LoopbackListener(
        host="127.0.0.1",
        port=int(cfg.get("listener_port") or 0),
        fs_signature=str(cfg.get("fs_signature") or ""),
        work_dir=work_dir,
    )
    listener.start()
    if listener.port == 0:
        # bind failed (LoopbackListener swallows the bind error) -> fail closed.
        listener.stop()
        sys.stderr.write("loopback-netns bootstrap: listener failed to bind in netns\n")
        return 4
    try:
        bound_port = str(listener.port)
        child_env = {str(k): str(v) for k, v in (cfg.get("child_env") or {}).items()}
        # Rewrite any callback env values the parent staged (placeholder OR a concrete
        # host-netns port) to the actually-bound in-netns port, so the PoC hits THIS
        # listener whether it reads the env var or a literal URL in its body.
        for key in cfg.get("callback_env_keys") or ():
            val = child_env.get(key)
            if isinstance(val, str):
                if "<<PORT>>" in val:
                    val = val.replace("<<PORT>>", bound_port)
                val = _LOOPBACK_URL_RE.sub("http://127.0.0.1:" + bound_port + "/", val)
                child_env[key] = val
        # The listener's real port is only known HERE (it binds in THIS netns, after
        # fork) and differs from any port the parent staged (the parent lives in a
        # DIFFERENT netns). Rewrite the PoC's loopback callback to the actually-bound
        # in-netns port before running, so the callback reaches THIS listener:
        #   * a literal ``<<PORT>>`` placeholder, AND
        #   * any concrete ``http://127.0.0.1:<digits>/`` the parent may have staged
        #     (the parent substitutes its own host-listener port for legacy/mock
        #     compatibility; we re-point it at the in-netns listener).
        poc_path = cfg.get("poc_path")
        if poc_path and os.path.isfile(poc_path):
            try:
                with open(poc_path, "r", encoding="utf-8") as fh:
                    body = fh.read()
                new_body = body.replace("<<PORT>>", bound_port)
                new_body = _LOOPBACK_URL_RE.sub(
                    "http://127.0.0.1:" + bound_port + "/", new_body
                )
                if new_body != body:
                    with open(poc_path, "w", encoding="utf-8") as fh:
                        fh.write(new_body)
            except OSError:
                pass
        run = _run_poc_child(
            cfg.get("cmd") or [],
            work_dir,
            child_env,
            float(cfg.get("timeout_s") or 30.0),
        )
        # Give the listener thread a beat to record an in-flight callback.
        time.sleep(0.2)
        payload = {
            "exit_code": run["exit_code"],
            "stdout": run["stdout"],
            "stderr": run["stderr"],
            "timed_out": run["timed_out"],
            "hits": list(listener.hits),
            "listener_port": listener.port,
        }
        sys.stdout.write(RESULT_SENTINEL + " " + json.dumps(payload) + "\n")
        sys.stdout.flush()
        return 0
    finally:
        listener.stop()


if __name__ == "__main__":
    raise SystemExit(main())

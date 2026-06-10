"""Pure-string sandbox determinism layer (Phase B).

This module is *data*, not behavior. It exposes ``_SITECUSTOMIZE_CONTENT`` --
the complete source of a deterministic ``sitecustomize.py`` held as a
module-level ``str`` -- and ``write_sitecustomize`` which writes that source to
disk. The module itself never patches the host interpreter, never spawns a
process, never touches the network, and never executes the embedded content.
"""
from __future__ import annotations
import os
_SITECUSTOMIZE_CONTENT = """# Deterministic sitecustomize.py -- auto-imported at interpreter startup.
#
# Virtualizes VALUE-LEVEL ENTROPY ONLY so two independent interpreter runs
# produce byte-identical entropy and wall-clock reads: wall-clock
# time.time/time_ns (a virtual, monotonically-advancing wall clock), seeded
# random, a sha256 hash chain behind os.urandom, and deterministic uuid.uuid4.
#
# RUNNER-SAFETY (2026-06-10): time.monotonic / time.monotonic_ns /
# time.perf_counter / time.perf_counter_ns and time.sleep are deliberately
# LEFT REAL and are NEVER reassigned here. The sandbox runner's per-input
# deadline loops are built on those primitives; virtualizing them froze
# elapsed time and spuriously timed out the runner hosting the candidate
# (proven against the real fuzz path -- identical candidates diverged 18/25).
# Leaving them real keeps the runner's timeout machinery sound while entropy
# stays deterministic.
import time as _time
import random as _random
import os as _os
import uuid as _uuid
import hashlib as _hashlib

# Fixed virtual epoch and per-read advance step. A fixed start plus a fixed
# step makes the wall clock advance within a run yet stay identical across runs.
_VIRTUAL_START_EPOCH = 1717977600.0
_VIRTUAL_CLOCK_STEP = 0.001

# The seed governs both random and the urandom hash chain.
_SEED = int(_os.environ.get(\"PYTHONHASHSEED\") or \"42\")

# Shared mutable state for the virtual wall clock and the entropy counter.
_state = {\"now\": _VIRTUAL_START_EPOCH, \"counter\": 0}


def _virtual_now():
    # Advance the shared virtual wall clock by one fixed step and return it.
    _state[\"now\"] = _state[\"now\"] + _VIRTUAL_CLOCK_STEP
    return _state[\"now\"]


def _mock_time():
    return _virtual_now()


def _mock_time_ns():
    return int(_virtual_now() * 1000000000.0)


def _mock_urandom(n):
    # Deterministic hash chain: sha256 over (seed, counter) blocks, sliced to n.
    n = int(n)
    out = bytearray()
    while len(out) < n:
        _state[\"counter\"] = _state[\"counter\"] + 1
        block = _hashlib.sha256(
            (\"janusmask-det-%d-%d\" % (_SEED, _state[\"counter\"])).encode(\"utf-8\")
        ).digest()
        out.extend(block)
    return bytes(out[:n])


def _mock_uuid4():
    # RFC-4122 v4 UUID derived from the deterministic urandom stream.
    data = bytearray(_mock_urandom(16))
    data[6] = (data[6] & 0x0F) | 0x40  # version 4
    data[8] = (data[8] & 0x3F) | 0x80  # variant 1 (RFC 4122)
    return _uuid.UUID(bytes=bytes(data))


# Virtualize VALUE-LEVEL ENTROPY ONLY -- the virtual wall clock and the
# deterministic entropy sources. Runner timing primitives are left untouched.
_time.time = _mock_time
_time.time_ns = _mock_time_ns

# Seed random so seeded draws are reproducible across runs.
_random.seed(_SEED)

# Deterministic entropy sources.
_os.urandom = _mock_urandom
_uuid.uuid4 = _mock_uuid4
"""

def write_sitecustomize(dest_dir) -> str:
    """Write ``sitecustomize.py`` containing ``_SITECUSTOMIZE_CONTENT``.

    Resolves ``dest_dir`` via :func:`os.fspath`, creates it if missing, writes
    the content exactly (utf-8), and returns the written path as ``str``.
    """
    dest = os.fspath(dest_dir)
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, 'sitecustomize.py')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(_SITECUSTOMIZE_CONTENT)
    return path
"""Pure-string sandbox determinism layer (Phase B).

This module is *data*, not behavior. It exposes ``_SITECUSTOMIZE_CONTENT`` --
the complete source of a deterministic ``sitecustomize.py`` held as a
module-level ``str`` -- and ``write_sitecustomize`` which writes that source to
disk. The module itself never patches the host interpreter, never spawns a
process, never touches the network, and never executes the embedded content.
"""
from __future__ import annotations
import os
_SITECUSTOMIZE_CONTENT = '# Deterministic sitecustomize.py -- auto-imported at interpreter startup.\n#\n# Installs a virtual, monotonically-advancing clock over the time module,\n# turns time.sleep into a non-blocking fast-forward, seeds random from\n# PYTHONHASHSEED (default 42), and replaces os.urandom / uuid.uuid4 with a\n# deterministic sha256 hash chain. The goal is reproducible, flake-free\n# fuzz-sandbox runs: two independent interpreter runs produce byte-identical\n# entropy and clock readings.\nimport time as _time\nimport random as _random\nimport os as _os\nimport uuid as _uuid\nimport hashlib as _hashlib\n\n# Fixed virtual epoch and per-read advance step. A fixed start plus a fixed\n# step makes the clock monotonic within a run yet identical across runs.\n_VIRTUAL_START_EPOCH = 1717977600.0\n_VIRTUAL_CLOCK_STEP = 0.001\n\n# The seed governs both random and the urandom hash chain.\n_SEED = int(_os.environ.get("PYTHONHASHSEED") or "42")\n\n# Shared mutable state for the virtual clock and the entropy counter.\n_state = {"now": _VIRTUAL_START_EPOCH, "counter": 0}\n\n\ndef _advance():\n    # Advance the shared virtual clock by one fixed step and return it.\n    _state["now"] = _state["now"] + _VIRTUAL_CLOCK_STEP\n    return _state["now"]\n\n\ndef _virtual_time():\n    return _advance()\n\n\ndef _virtual_time_ns():\n    return int(_advance() * 1000000000.0)\n\n\ndef _virtual_monotonic():\n    return _advance()\n\n\ndef _virtual_monotonic_ns():\n    return int(_advance() * 1000000000.0)\n\n\ndef _virtual_perf_counter():\n    return _advance()\n\n\ndef _virtual_perf_counter_ns():\n    return int(_advance() * 1000000000.0)\n\n\ndef _virtual_sleep(seconds=0.0):\n    # Fast-forward the virtual clock instead of blocking. Bad inputs neither\n    # raise nor move the clock backwards.\n    try:\n        _state["now"] = _state["now"] + max(0.0, float(seconds))\n    except (TypeError, ValueError):\n        pass\n\n\ndef _virtual_urandom(n):\n    # Deterministic hash chain: sha256 over (seed, counter) blocks, sliced to n.\n    n = int(n)\n    out = bytearray()\n    while len(out) < n:\n        _state["counter"] = _state["counter"] + 1\n        block = _hashlib.sha256(\n            ("%d:%d" % (_SEED, _state["counter"])).encode("utf-8")\n        ).digest()\n        out.extend(block)\n    return bytes(out[:n])\n\n\ndef _virtual_uuid4():\n    # RFC-4122 compliant UUID derived from the deterministic urandom stream.\n    data = bytearray(_virtual_urandom(16))\n    data[6] = (data[6] & 0x0F) | 0x40  # version 4\n    data[8] = (data[8] & 0x3F) | 0x80  # variant 1 (RFC 4122)\n    return _uuid.UUID(bytes=bytes(data))\n\n\n# Install the virtual clock over every time source.\n_time.time = _virtual_time\n_time.time_ns = _virtual_time_ns\n_time.monotonic = _virtual_monotonic\n_time.monotonic_ns = _virtual_monotonic_ns\n_time.perf_counter = _virtual_perf_counter\n_time.perf_counter_ns = _virtual_perf_counter_ns\n_time.sleep = _virtual_sleep\n\n# Seed random so seeded draws are reproducible.\n_random.seed(_SEED)\n\n# Deterministic entropy.\n_os.urandom = _virtual_urandom\n_uuid.uuid4 = _virtual_uuid4\n'

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
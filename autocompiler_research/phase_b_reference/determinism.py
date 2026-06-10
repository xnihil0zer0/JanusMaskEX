"""Pure-string determinism layer for the fuzz sandbox (Phase B, ac-determinism).

``_SITECUSTOMIZE_CONTENT`` is DATA: the source of a deterministic
``sitecustomize.py`` (virtual clock, seeded PRNG, deterministic ``os.urandom``
and ``uuid.uuid4``, fast-forward ``sleep``) that the Phase-C wiring mounts
into the sandbox work dir. This module never patches the host interpreter,
never spawns, and performs no I/O beyond the explicit writer.
"""
from __future__ import annotations

import os

_SITECUSTOMIZE_CONTENT = '''\
# sitecustomize.py -- JanusMask deterministic sandbox layer (autocompiler Phase B).
# Auto-imported by Python at startup when this directory is on sys.path.
# Intercepts user-space entropy/clock sources so repeated candidate runs are
# byte-identical: virtual clock, seeded PRNG, deterministic urandom/uuid,
# fast-forward sleep. Practical determinism only -- threads/GC/ASLR remain.
import hashlib as _hashlib
import os as _os
import random as _random
import time as _time
import uuid as _uuid

_VIRTUAL_START_EPOCH = 1717977600.0
_VIRTUAL_CLOCK_STEP = 0.001
_state = {'now': _VIRTUAL_START_EPOCH, 'urandom_n': 0}

def _virtual_now():
    t = _state['now']
    _state['now'] = t + _VIRTUAL_CLOCK_STEP
    return t

def _mock_time():
    return _virtual_now()

def _mock_time_ns():
    return int(_virtual_now() * 1e9)

def _mock_sleep(seconds):
    try:
        _state['now'] += max(0.0, float(seconds))
    except (TypeError, ValueError):
        pass

_time.time = _mock_time
_time.time_ns = _mock_time_ns
_time.monotonic = _mock_time
_time.monotonic_ns = _mock_time_ns
_time.perf_counter = _mock_time
_time.perf_counter_ns = _mock_time_ns
_time.sleep = _mock_sleep

_SANDBOX_SEED = int(_os.environ.get('PYTHONHASHSEED') or '42')
_random.seed(_SANDBOX_SEED)

def _mock_urandom(n):
    out = b''
    while len(out) < n:
        _state['urandom_n'] += 1
        out += _hashlib.sha256(
            ('janusmask-det-%d-%d' % (_SANDBOX_SEED, _state['urandom_n'])).encode()
        ).digest()
    return out[:n]

_os.urandom = _mock_urandom

def _mock_uuid4():
    raw = bytearray(_mock_urandom(16))
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return _uuid.UUID(bytes=bytes(raw))

_uuid.uuid4 = _mock_uuid4
'''


def write_sitecustomize(dest_dir) -> str:
    """Write ``sitecustomize.py`` (exactly ``_SITECUSTOMIZE_CONTENT``) into
    *dest_dir* (created if missing) and return the written path as ``str``."""
    dest = os.fspath(dest_dir)
    os.makedirs(dest, exist_ok=True)
    path = os.path.join(dest, 'sitecustomize.py')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(_SITECUSTOMIZE_CONTENT)
    return path

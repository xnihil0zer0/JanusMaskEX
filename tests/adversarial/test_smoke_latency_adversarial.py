"""Latency probes for harness.sandbox_smoke.smoke_import (W74 / HH4).

The orchestrator's BYPASS_FUZZER_TYPES accept branch invokes
:func:`smoke_import` synchronously on every accepted canary output. DD6
shipped without any latency instrumentation, so a pathological smoke call
could silently block orchestrator progress for seconds per accept.

This module establishes three probe points (baseline floor, realistic
fixture, timeout bound) so a regression in subprocess launch cost or in
timeout enforcement is caught in CI rather than in production. Actual
orchestrator-side instrumentation is gated to W74b and will be wired only
if these probes show headroom trouble.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.sandbox_smoke import smoke_import


_REALISTIC_SRC = '''\
"""Synthetic module shaped like a typical accepted canary helper.

Imports a handful of stdlib modules, defines a small class with a couple
of methods, plus a free function. Representative of what a real accepted
fixture looks like post-scrub.
"""
import os
import sys
import json
import re


_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Normalizer:
    def __init__(self, prefix: str = "t_") -> None:
        self.prefix = prefix

    def normalize(self, raw: str) -> str:
        cleaned = raw.strip().lower()
        if not _PATTERN.match(cleaned):
            cleaned = re.sub(r"[^a-z0-9_]", "_", cleaned)
        return f"{self.prefix}{cleaned}"

    def encode(self, raw: str) -> str:
        return json.dumps({"id": self.normalize(raw), "cwd": os.getcwd()})


def platform_tag() -> str:
    return f"{sys.platform}:{os.name}"


def pack(items):
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        else:
            out.append(repr(it))
    return ",".join(out)
'''


def test_smoke_latency_realistic_fixture():
    # Realistic fixture: a few stdlib imports, a small class with two
    # methods, a couple of free functions. Not trivial, not adversarial.
    # Threshold = ~3x brief estimate of 1s per call. Tightening below 1.5s
    # deferred to W74b once we have multi-CI-run latency distribution data.
    t0 = time.monotonic()
    result = smoke_import("_smoke_realistic", _REALISTIC_SRC)
    elapsed = time.monotonic() - t0
    assert result is None, f"expected clean import, got: {result!r}"
    assert elapsed < 3.0, f"realistic smoke took {elapsed:.3f}s, budget 3.0s"


def test_smoke_latency_baseline_tiny():
    # Pure subprocess + tempdir + scrubbed-env overhead floor. Above this
    # means an upstream scrub change has slowed launch (e.g. added an
    # expensive env probe, switched to a wrapper interpreter, or regressed
    # tempdir handling).
    src = "def f(): return 1\n"
    t0 = time.monotonic()
    result = smoke_import("_smoke_tiny", src)
    elapsed = time.monotonic() - t0
    assert result is None, f"expected clean import, got: {result!r}"
    assert elapsed < 0.5, f"baseline smoke took {elapsed:.3f}s, budget 0.5s"


def test_smoke_latency_timeout_bound():
    # Asserts subprocess kill-on-timeout actually fires. If elapsed >= 2.0s,
    # the timeout enforcement is broken and tests would normally hang for
    # the full sleep(60). We assert the stricter < 1.5s to leave a teardown
    # buffer but still flag any meaningful regression.
    src = "import time\ntime.sleep(60)\n"
    t0 = time.monotonic()
    result = smoke_import("_smoke_timeout_bound", src, timeout=1.0)
    elapsed = time.monotonic() - t0
    assert result is not None, "expected timeout error, got None (clean import?)"
    # sandbox_smoke.py returns exactly "sandbox import timed out" on
    # subprocess.TimeoutExpired; match that phrase (substring "timed out"
    # also covers a future "timeout" rewording without breaking on the
    # word form).
    assert "timed out" in result or "timeout" in result, (
        f"expected timeout phrase in error, got: {result!r}"
    )
    assert elapsed < 1.5, (
        f"timeout-bound smoke took {elapsed:.3f}s, budget 1.5s "
        f"(timeout=1.0s + 0.5s teardown); kill-on-timeout may be broken"
    )

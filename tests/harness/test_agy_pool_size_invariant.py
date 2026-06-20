"""Oracle: runtime enforcement of the agy-pool ``size >= parallel_cap`` invariant.

Today the invariant is COMMENT-ONLY (config.yaml warns it is "NOT
runtime-enforced"). When the pool is enabled but ``size < parallel_cap`` the
documented footgun fires: a concurrent worker beyond ``size`` gets no slot
(``allocate_slot`` returns ``None``) and silently falls back to the SHARED
``~/.gemini`` HOME -- exactly the cred/registry corruption the pool exists to
prevent.

This oracle pins a permanent, reusable guard in ``harness.agy_pool`` that makes
the footgun impossible:

  * ``effective_pool_size(enabled, size, parallel_cap)`` -- the size the runtime
    MUST use. When the pool is enabled it can never be below ``parallel_cap``
    (auto-clamps UP), so every concurrent worker is guaranteed a private slot.
    When disabled it returns the requested size unchanged (no pooling occurs).

  * ``assert_pool_invariant(enabled, size, parallel_cap)`` -- the strict,
    fail-closed form: raises ``PoolInvariantError`` (a clear, named error) when
    the pool is enabled and ``size < parallel_cap``; a no-op otherwise.

Pure function of the ``(enabled, size, parallel_cap)`` tuple -- no I/O.
"""
from __future__ import annotations

import pytest

from harness import agy_pool


# --- a named, catchable error exists ---------------------------------------

def test_pool_invariant_error_is_a_named_exception():
    assert issubclass(agy_pool.PoolInvariantError, Exception)


# --- effective_pool_size: auto-clamp keeps coverage -------------------------

def test_effective_size_clamps_up_to_cap_when_enabled_and_too_small():
    # The footgun input: enabled pool, size below the cap. The effective size
    # MUST cover the cap so no concurrent worker is left unpooled.
    assert agy_pool.effective_pool_size(enabled=True, size=2, parallel_cap=5) == 5


def test_effective_size_unchanged_when_size_already_covers_cap():
    assert agy_pool.effective_pool_size(enabled=True, size=8, parallel_cap=5) == 8


def test_effective_size_passthrough_when_disabled():
    # Disabled => no pooling; the guard never inflates a disabled pool.
    assert agy_pool.effective_pool_size(enabled=False, size=2, parallel_cap=5) == 2


# --- assert_pool_invariant: fail-closed ------------------------------------

def test_assert_invariant_raises_when_enabled_and_size_below_cap():
    with pytest.raises(agy_pool.PoolInvariantError):
        agy_pool.assert_pool_invariant(enabled=True, size=3, parallel_cap=5)


def test_assert_invariant_error_message_is_clear():
    with pytest.raises(agy_pool.PoolInvariantError) as ei:
        agy_pool.assert_pool_invariant(enabled=True, size=3, parallel_cap=5)
    msg = str(ei.value)
    assert "3" in msg and "5" in msg  # surfaces the offending size and cap


def test_assert_invariant_noop_when_size_covers_cap():
    # Returns normally (no raise) when the invariant holds.
    agy_pool.assert_pool_invariant(enabled=True, size=8, parallel_cap=5)


def test_assert_invariant_noop_when_disabled():
    # Disabled pool can never trip the invariant (workers share HOME by design).
    agy_pool.assert_pool_invariant(enabled=False, size=1, parallel_cap=5)


# --- allocate_slot stays hardened against a degenerate size -----------------

def test_allocate_slot_returns_none_for_nonpositive_size():
    # A degenerate size must never hand out slot 0 (which would then race the
    # shared HOME). Lowest-free over range(0) is None.
    assert agy_pool.allocate_slot(set(), size=0) is None

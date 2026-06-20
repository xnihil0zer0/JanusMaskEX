"""RED oracle for the agy_pool ENABLE flip (Brick C of the NGv2 closure program).

Asserts the workers.agy_pool block is ENABLED in harness/config.yaml and that its
size still covers autowork.parallel_cap so every concurrent worker gets a private
$HOME slot. RED on HEAD (config ships enabled: false); turns GREEN when the single
config flip lands.

Loaded via the harness config loader so it reflects the live runtime gate.
"""
from harness.orchestrator import load_config


def test_agy_pool_enabled_is_true():
    cfg = load_config()
    pool = cfg["workers"]["agy_pool"]
    assert pool["enabled"] is True, (
        "workers.agy_pool.enabled must be True (the pool is the isolated-HOME "
        "feature; flip it on)"
    )


def test_agy_pool_size_covers_parallel_cap_when_enabled():
    cfg = load_config()
    pool = cfg["workers"]["agy_pool"]
    size = pool["size"]
    cap = cfg["autowork"]["parallel_cap"]
    assert isinstance(size, int) and size >= cap, (
        "agy_pool.size (%r) must be >= autowork.parallel_cap (%r) so no "
        "concurrent worker is left sharing the operator HOME" % (size, cap)
    )

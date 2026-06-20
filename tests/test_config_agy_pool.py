"""Oracle for the workers.agy_pool config block (Pillar B of agent_exec_substrate).

harness/agy_pool.py is the isolated-HOME pool module; this block is the gate the
daemon/orchestrator read to decide whether to pool a worker's $HOME. It ships
default-OFF (shared HOME, today's behavior) and, when on, its size must cover the
daemon's parallel_cap so no concurrent worker is left sharing the registry.
"""
from harness.orchestrator import load_config


def test_agy_pool_block_present_and_enabled():
    cfg = load_config()
    assert "workers" in cfg, "config.yaml has no workers: block"
    pool = cfg["workers"]["agy_pool"]
    # ENABLED (NGv2 closure program 2026-06-19): each concurrent agy/gemini
    # worker gets a private $HOME so parallel registries cannot corrupt each
    # other. size MUST still cover parallel_cap (asserted below).
    assert pool["enabled"] is True


def test_agy_pool_size_covers_parallel_cap():
    cfg = load_config()
    size = cfg["workers"]["agy_pool"]["size"]
    cap = cfg["autowork"]["parallel_cap"]
    assert isinstance(size, int) and size >= cap, (
        "agy_pool.size (%r) must be >= autowork.parallel_cap (%r) so every "
        "concurrent worker gets a private slot" % (size, cap)
    )


def test_agy_pool_block_is_additive():
    cfg = load_config()
    # Sanity: the new block did not disturb existing top-level blocks.
    assert "autowork" in cfg and "overseer" in cfg and "agents" in cfg

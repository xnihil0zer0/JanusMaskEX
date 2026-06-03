"""MD_ROUTING behavioral oracle (REV25 §3 / MD-ROUTING = M-D4).

`stateful_differential_fuzz` was never reachable: state_machine tasks short-
circuit to the bypass-accept path at the worker fall-through
(orchestrator_worker.py:322 + mirror orchestrator.py:2959), so the stateful
fuzzer is dead code. MD_ROUTING adds a module-level routing helper
`_route_stateful_fuzz` and gates both fall-through sites on
`META_TASK_POLICY[mtt].get('stateful_fuzz')`, fail-safe to bypass-accept when
falsy.

This oracle drives the smallest REAL unit -- the module-level routing helper --
on a known-divergent stateful class pair and asserts it reaches the stateful
path (equivalent=False with a populated stateful FuzzFailure), and that the
class name is resolved from task constraints. A full worker-dispatch oracle is
impractical (subprocess + agents), so we drive the extracted helper directly,
which is exactly the seam the call sites invoke.

RED on HEAD: `_route_stateful_fuzz` does not exist (AttributeError).
DEPENDS-ON: MD_POLICY (the stateful_fuzz flag the call sites gate on) and the
already-landed MD-IMPORT/COMPARATOR (so the stateful fuzzer actually detects
divergence). MD_SERIALIZE field promotion makes the populated-FuzzFailure
assertion clean.
"""
import harness.orchestrator as orch


_CFG = {
    "fuzzing": {"max_examples": 50},
    "sandbox": {
        "memory_limit_mb": 256,
        "cpu_time_limit_seconds": 5,
        "filesystem_root": "/tmp/janusmask_md_routing",
    },
    "agent_sandbox": {"bwrap": False},
}

# Two Counter classes whose accumulated state diverges (inc by 1 vs by 2).
CODE_A = """
class Counter:
    def __init__(self, start: int):
        self.v = start
    def inc(self, n: int) -> int:
        self.v += n
        return self.v
"""
CODE_B = """
class Counter:
    def __init__(self, start: int):
        self.v = start
    def inc(self, n: int) -> int:
        self.v += 2 * n
        return self.v
"""

EQUIV_B = CODE_A.replace("Counter", "Counter")  # identical to A


def _task(stateful_fuzz=True):
    return {
        "task_id": "md_routing_probe",
        "meta_task_type": "state_machine",
        "constraints": {
            "meta_task_type": "state_machine",
            "function_signature": "class Counter",
        },
    }


def test_route_stateful_fuzz_helper_exists():
    assert hasattr(orch, "_route_stateful_fuzz"), (
        "MD_ROUTING must add the module-level routing helper _route_stateful_fuzz"
    )


def test_route_reaches_stateful_path_on_divergent_pair():
    result = orch._route_stateful_fuzz(_task(), CODE_A, CODE_B, _CFG, "md_routing_div")
    assert result is not None, "routing must return a FuzzResult, not silently bypass"
    assert result.equivalent is False, (
        "divergent stateful pair must be detected (not silently skipped)"
    )
    assert result.failures, "a divergence must populate failures"
    f = result.failures[0]
    assert getattr(f, "action_sequence", None) is not None


def test_route_equivalent_pair_returns_true():
    result = orch._route_stateful_fuzz(_task(), CODE_A, CODE_A, _CFG, "md_routing_eq")
    assert result is not None
    assert result.equivalent is True

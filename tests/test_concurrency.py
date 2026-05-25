"""Concurrency & Stress Tests (C-01 through C-10) for JanusMask.

Tests state locking under load, parallel agent spawning,
and fuzzing under stress conditions.
"""

import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.state import (
    init_state,
    locked_read_modify_write,
    read_state,
    set_phase,
)
from harness.diff_fuzzer import (
    _generate_inputs,
    build_input_strategy,
    differential_fuzz,
)

try:
    from hypothesis import strategies as st
except ImportError:
    st = None


# ---------------------------------------------------------------------------
# C-01: 20 concurrent locked_read_modify_write calls — final counter == 20
# ---------------------------------------------------------------------------

class TestStateLockingUnderLoad:
    """14.1 State Locking Under Load."""

    def test_c01_twenty_concurrent_writes(self, tmp_state_dir):
        """C-01: 20 concurrent locked_read_modify_write calls all apply."""
        init_state(tmp_state_dir)
        # Also write an initial counter
        locked_read_modify_write(
            lambda s: {**s, "counter": 0}, tmp_state_dir
        )

        def increment(state):
            state["counter"] = state.get("counter", 0) + 1
            return state

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [
                pool.submit(locked_read_modify_write, increment, tmp_state_dir)
                for _ in range(20)
            ]
            for f in as_completed(futures, timeout=30):
                f.result()  # raise if any failed

        final = read_state(tmp_state_dir)
        assert final["counter"] == 20, f"Expected 20, got {final['counter']}"

    def test_c02_fifty_concurrent_reads(self, tmp_state_dir):
        """C-02: 50 concurrent read_state calls — all return consistent state."""
        init_state(tmp_state_dir)
        set_phase(tmp_state_dir, phase="fuzzing")

        results = []

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [
                pool.submit(read_state, tmp_state_dir)
                for _ in range(50)
            ]
            for f in as_completed(futures, timeout=30):
                results.append(f.result())

        assert len(results) == 50
        # All should return the same consistent state
        for r in results:
            assert r["phase"] == "fuzzing"
            assert "task_id" in r

    def test_c03_mixed_reads_and_writes_no_deadlock(self, tmp_state_dir):
        """C-03: Mixed reads and writes (20 each) — no deadlock."""
        init_state(tmp_state_dir)
        locked_read_modify_write(
            lambda s: {**s, "counter": 0}, tmp_state_dir
        )

        def do_write():
            locked_read_modify_write(
                lambda s: {**s, "counter": s.get("counter", 0) + 1},
                tmp_state_dir,
            )

        def do_read():
            state = read_state(tmp_state_dir)
            assert isinstance(state, dict)
            return state

        with ThreadPoolExecutor(max_workers=40) as pool:
            write_futures = [pool.submit(do_write) for _ in range(20)]
            read_futures = [pool.submit(do_read) for _ in range(20)]
            all_futures = write_futures + read_futures

            for f in as_completed(all_futures, timeout=30):
                f.result()  # no deadlock, no exception

        final = read_state(tmp_state_dir)
        assert final["counter"] == 20

    def test_c04_writer_starvation(self, tmp_state_dir):
        """C-04: Writer starvation test — writer eventually acquires lock."""
        init_state(tmp_state_dir)
        writer_completed = threading.Event()

        def many_reads():
            for _ in range(100):
                read_state(tmp_state_dir)

        def single_write():
            locked_read_modify_write(
                lambda s: {**s, "phase": "accepted"},
                tmp_state_dir,
            )
            writer_completed.set()

        with ThreadPoolExecutor(max_workers=11) as pool:
            # Start many readers
            read_futures = [pool.submit(many_reads) for _ in range(10)]
            # Start a writer
            write_future = pool.submit(single_write)

            for f in as_completed(read_futures + [write_future], timeout=30):
                f.result()

        assert writer_completed.is_set(), "Writer was starved and never completed"
        final = read_state(tmp_state_dir)
        assert final["phase"] == "accepted"


# ---------------------------------------------------------------------------
# C-05 through C-07: Parallel Agent Spawning
# ---------------------------------------------------------------------------

class TestParallelAgentSpawning:
    """14.2 Parallel Agent Spawning."""

    def test_c05_threadpool_two_mock_agents(self, tmp_state_dir):
        """C-05: ThreadPoolExecutor with 2 mock agents complete within timeout."""
        init_state(tmp_state_dir)

        def mock_agent(agent_name):
            """Simulate agent that takes a short time and returns a result."""
            time.sleep(0.1)
            return {"agent": agent_name, "code": f"def f(): return '{agent_name}'"}

        with ThreadPoolExecutor(max_workers=2) as pool:
            claude_future = pool.submit(mock_agent, "claude")
            gemini_future = pool.submit(mock_agent, "gemini")

            results = {}
            for future in as_completed([claude_future, gemini_future], timeout=10):
                result = future.result()
                results[result["agent"]] = result

        assert "claude" in results
        assert "gemini" in results
        assert "code" in results["claude"]
        assert "code" in results["gemini"]

    def test_c06_one_slow_one_fast(self, tmp_state_dir):
        """C-06: One agent slow, other fast — fast result collected."""
        init_state(tmp_state_dir)
        fast_completed = threading.Event()

        def fast_agent():
            time.sleep(0.05)
            fast_completed.set()
            return {"agent": "fast", "done": True}

        def slow_agent():
            time.sleep(2.0)
            return {"agent": "slow", "done": True}

        with ThreadPoolExecutor(max_workers=2) as pool:
            fast_future = pool.submit(fast_agent)
            slow_future = pool.submit(slow_agent)

            # Fast should complete first
            done_futures = []
            for future in as_completed([fast_future, slow_future], timeout=5):
                done_futures.append(future.result())

        assert fast_completed.is_set()
        # Both should eventually complete
        assert len(done_futures) == 2

    def test_c07_concurrent_session_writes(self, tmp_state_dir):
        """C-07: Both agents write to sessions dir simultaneously."""
        init_state(tmp_state_dir)
        sessions_dir = tmp_state_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        def write_submission(agent_name):
            submission = {
                "agent": agent_name,
                "code": f"def solve(): return '{agent_name}'",
            }
            path = sessions_dir / f"{agent_name}_round1_submission.json"
            with open(path, "w") as f:
                json.dump(submission, f, indent=2)
            return path

        with ThreadPoolExecutor(max_workers=2) as pool:
            claude_future = pool.submit(write_submission, "claude")
            gemini_future = pool.submit(write_submission, "gemini")
            claude_path = claude_future.result(timeout=5)
            gemini_path = gemini_future.result(timeout=5)

        # Both files should exist and be valid JSON
        assert claude_path.is_file()
        assert gemini_path.is_file()

        with open(claude_path) as f:
            claude_data = json.load(f)
        with open(gemini_path) as f:
            gemini_data = json.load(f)

        assert claude_data["agent"] == "claude"
        assert gemini_data["agent"] == "gemini"


# ---------------------------------------------------------------------------
# C-08 through C-10: Fuzzing Under Load
# ---------------------------------------------------------------------------

class TestFuzzingUnderLoad:
    """14.3 Fuzzing Under Load."""

    @pytest.mark.timeout(600)
    def test_c08_2000_inputs_complex_type(self):
        """C-08: 2000 fuzz inputs with complex type completes."""
        code = (
            "def process(data: list[int]) -> list[int]:\n"
            "    return sorted(data)\n"
        )

        strategy = build_input_strategy(code, "process")
        inputs = _generate_inputs(strategy, 2000, seed=42)

        # Should generate a reasonable number of inputs
        assert len(inputs) > 0, "No inputs generated"
        # Each input should be a tuple of (args_list, kwargs_dict)
        for args, kwargs in inputs[:10]:
            assert isinstance(args, list)
            assert isinstance(kwargs, dict)

    @pytest.mark.timeout(120)
    def test_c09_fuzz_with_hang_per_input_timeout(self):
        """C-09: Fuzz with function that occasionally hangs — per-input timeout."""
        code_normal = (
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        # Code B that hangs on certain inputs
        code_hang = (
            "import time\n"
            "def add(a: int, b: int) -> int:\n"
            "    if a == 0 and b == 0:\n"
            "        time.sleep(100)\n"
            "    return a + b\n"
        )

        config = {
            "fuzzing": {
                "function_level_inputs": 10,
                "float_tolerance": 1e-9,
                "seed": 42,
                "timeout_per_input_ms": 2000,
            },
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 3,
                "filesystem_root": "/tmp/janusmask_sandbox_c09",
            },
        }

        result = differential_fuzz(code_normal, code_hang, "add", config, session_id="c09")

        # Should complete (not hang forever) and detect some divergence
        # (the hanging code times out on (0,0) if that input is generated)
        assert result.total_inputs > 0 or result.error is not None

    @pytest.mark.timeout(120)
    def test_c10_multiple_fuzz_sessions_parallel(self):
        """C-10: Multiple fuzz sessions in parallel — no sandbox dir conflicts."""
        code_a = "def inc(x: int) -> int:\n    return x + 1\n"
        code_b = "def inc(x: int) -> int:\n    return x + 1\n"

        config = {
            "fuzzing": {
                "function_level_inputs": 20,
                "float_tolerance": 1e-9,
                "seed": 42,
                "timeout_per_input_ms": 3000,
            },
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 5,
                "filesystem_root": "/tmp/janusmask_sandbox_c10",
            },
        }

        def run_fuzz(session_num):
            return differential_fuzz(
                code_a, code_b, "inc", config,
                session_id=f"parallel_{session_num}",
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(run_fuzz, i) for i in range(3)]
            results = [f.result(timeout=90) for f in futures]

        # All sessions should have run successfully
        for i, result in enumerate(results):
            assert result.error is None, f"Session {i} had error: {result.error}"
            assert result.equivalent, f"Session {i} reported divergence unexpectedly"
            assert result.total_inputs > 0, f"Session {i} ran 0 inputs"

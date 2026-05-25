"""Security tests: Resource exhaustion prevention.

Tests SEC-23 through SEC-27 from the JanusMask Phase 1 Test Plan (Section 13.4).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.sandbox import Sandbox, SandboxConfig
from harness.diff_fuzzer import differential_fuzz, FuzzResult


@pytest.fixture
def tight_sandbox():
    """A sandbox with tight resource limits for testing exhaustion scenarios."""
    config = SandboxConfig(
        memory_limit_mb=64,
        cpu_time_limit_seconds=2,
        timeout_per_input_ms=3000,
        filesystem_root="/tmp/janusmask_resource_test",
        python_hash_seed="0",
    )
    sb = Sandbox(config=config, session_id="resource_test")
    yield sb
    sb.cleanup()


class TestResourceExhaustion:
    """SEC-23 through SEC-27: Resource exhaustion prevention."""

    def test_sec23_fork_bomb_killed(self, tight_sandbox):
        """SEC-23: Fork bomb os.fork() killed by resource limits.

        Uses a LIMITED fork (max 5 children) instead of an unbounded fork bomb
        to avoid killing the test environment. The real security property being
        tested is that the sandbox kills runaway processes via process group,
        not that it can survive an unlimited fork bomb (which can exhaust
        system-wide process limits beyond any sandbox's control).
        """
        code = (
            "import os\n"
            "import time\n"
            "def fork_bomb(x: int) -> int:\n"
            "    pids = []\n"
            "    for _ in range(5):\n"
            "        try:\n"
            "            pid = os.fork()\n"
            "            if pid == 0:\n"
            "                time.sleep(30)  # child hangs\n"
            "                os._exit(0)\n"
            "            pids.append(pid)\n"
            "        except OSError:\n"
            "            break\n"
            "    time.sleep(30)  # parent also hangs\n"
            "    return x\n"
        )
        result = tight_sandbox.execute(code, "fork_bomb", args=[0])

        # The sandbox should kill the process group (parent + children)
        # via timeout, not return successfully
        assert result.timed_out or not result.success, (
            "Fork bomb should be killed by resource limits or timeout"
        )

    def test_sec24_memory_bomb_killed(self, tight_sandbox):
        """SEC-24: Memory bomb killed by RLIMIT_AS.
        Allocating 10GB of memory should trigger MemoryError."""
        code = (
            "def mem_bomb(x: int) -> str:\n"
            "    data = 'x' * (10 ** 10)\n"
            "    return 'survived'\n"
        )
        result = tight_sandbox.execute(code, "mem_bomb", args=[0])

        # Should fail with MemoryError or be killed
        assert not result.success or result.timed_out, (
            "Memory bomb should be killed by RLIMIT_AS"
        )
        if not result.timed_out and result.exception_type:
            assert result.exception_type in ("MemoryError", "SandboxError"), (
                f"Expected MemoryError, got {result.exception_type}"
            )

    def test_sec25_cpu_bomb_killed(self, tight_sandbox):
        """SEC-25: CPU bomb while True: pass killed by RLIMIT_CPU and wall timeout."""
        code = (
            "def cpu_bomb(x: int) -> int:\n"
            "    while True:\n"
            "        pass\n"
        )
        result = tight_sandbox.execute(code, "cpu_bomb", args=[0])

        # Should be killed by CPU limit or wall timeout
        assert result.timed_out or not result.success, (
            "CPU bomb should be killed by RLIMIT_CPU or wall timeout"
        )

    def test_sec26_disk_bomb_constrained(self, tight_sandbox):
        """SEC-26: Disk bomb constrained to sandbox dir.
        Large file writes should go to the sandbox directory, and
        cleanup should remove them."""
        code = (
            "import os\n"
            "def disk_bomb(x: int) -> str:\n"
            "    try:\n"
            "        with open('bomb.txt', 'w') as f:\n"
            "            f.write('A' * (1024 * 1024))  # 1MB\n"
            "        return os.path.abspath('bomb.txt')\n"
            "    except OSError as e:\n"
            "        return str(e)\n"
        )
        result = tight_sandbox.execute(code, "disk_bomb", args=[0])
        assert result.success is True

        # The file path should be within the sandbox directory
        if result.return_value and isinstance(result.return_value, str):
            file_path = result.return_value
            if not file_path.startswith("OS"):  # Not an error message
                assert "janusmask" in file_path.lower() or "resource_test" in file_path

        # After cleanup, the sandbox dir should be gone
        tight_sandbox.cleanup()
        sandbox_dir = Path(tight_sandbox.config.filesystem_root) / "session_resource_test"
        assert not sandbox_dir.exists(), "Sandbox dir should be cleaned up"

    def test_sec27_failure_cap_prevents_excessive_fuzzing(self):
        """SEC-27: 20 failures cap prevents excessive fuzzing.
        The differential fuzzer should stop after collecting 20 failures."""
        # Two functions that always disagree
        code_a = "def negate(x: int) -> int:\n    return -x\n"
        code_b = "def negate(x: int) -> int:\n    return x\n"

        config = {
            "fuzzing": {
                "function_level_inputs": 200,
                "timeout_per_input_ms": 3000,
                "float_tolerance": 1e-9,
                "seed": 42,
            },
            "sandbox": {
                "memory_limit_mb": 128,
                "cpu_time_limit_seconds": 5,
                "filesystem_root": "/tmp/janusmask_cap_test",
            },
        }

        result = differential_fuzz(code_a, code_b, "negate", config,
                                   session_id="sec27")

        assert result.equivalent is False
        # The fuzzer should cap at 20 failures
        assert len(result.failures) <= 20, (
            f"Expected at most 20 failures, got {len(result.failures)}"
        )
        # Should have stopped early (not processed all 200 inputs)
        assert result.total_inputs < 200 or len(result.failures) == 20

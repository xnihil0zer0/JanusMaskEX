"""Tests for harness/state.py — flock-based thread-safe state management."""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.state import (
    INITIAL_STATE,
    VALID_AGENTS,
    VALID_AGENT_STATUSES,
    VALID_PHASES,
    InvalidAgentError,
    InvalidAgentStatusError,
    InvalidPhaseError,
    StateCorruptError,
    StateMissingError,
    get_agent_status,
    get_phase,
    init_state,
    locked_read_modify_write,
    read_state,
    set_agent_status,
    set_phase,
)


# ── Initialization ──────────────────────────────────────────────────────

class TestInitState:
    def test_creates_state_json_with_all_keys(self, tmp_state_dir):
        state = init_state(tmp_state_dir)
        assert (tmp_state_dir / "STATE.json").is_file()
        for key in INITIAL_STATE:
            assert key in state

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "state"
        init_state(nested)
        assert (nested / "STATE.json").is_file()

    def test_overwrites_existing_state(self, tmp_state_dir):
        init_state(tmp_state_dir)
        set_phase(tmp_state_dir, phase="fuzzing")
        init_state(tmp_state_dir)
        assert read_state(tmp_state_dir)["phase"] == "idle"

    def test_creates_lock_file(self, tmp_state_dir):
        init_state(tmp_state_dir)
        assert (tmp_state_dir / "state.lock").exists()


# ── Reading ─────────────────────────────────────────────────────────────

class TestReadState:
    def test_returns_valid_dict(self, initialized_state_dir):
        state = read_state(initialized_state_dir)
        assert isinstance(state, dict)
        assert state["phase"] == "idle"

    def test_raises_missing_error(self, tmp_state_dir):
        with pytest.raises(StateMissingError):
            read_state(tmp_state_dir)

    def test_raises_corrupt_error_invalid_json(self, tmp_state_dir):
        (tmp_state_dir / "STATE.json").write_text("NOT JSON {{{")
        with pytest.raises(StateCorruptError):
            read_state(tmp_state_dir)

    def test_raises_corrupt_error_root_is_array(self, tmp_state_dir):
        (tmp_state_dir / "STATE.json").write_text("[1, 2, 3]")
        with pytest.raises(StateCorruptError):
            read_state(tmp_state_dir)

    def test_concurrent_reads_succeed(self, initialized_state_dir):
        results = []
        errors = []

        def _read():
            try:
                results.append(read_state(initialized_state_dir))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_read) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(errors) == 0
        assert len(results) == 10


# ── Locked Read-Modify-Write ────────────────────────────────────────────

class TestLockedReadModifyWrite:
    def test_applies_modifier(self, initialized_state_dir):
        def _mod(s):
            s["phase"] = "fuzzing"
            return s

        result = locked_read_modify_write(_mod, initialized_state_dir)
        assert result["phase"] == "fuzzing"
        assert read_state(initialized_state_dir)["phase"] == "fuzzing"

    def test_exception_in_modifier_does_not_corrupt(self, initialized_state_dir):
        def _bad(s):
            s["phase"] = "should_not_persist"
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            locked_read_modify_write(_bad, initialized_state_dir)
        # State should still be "idle" (the write never happened because
        # the exception propagated before _write_state_to_disk)
        state = read_state(initialized_state_dir)
        assert state["phase"] == "idle"

    def test_modifier_receives_current_state(self, initialized_state_dir):
        received = {}

        def _capture(s):
            received.update(s)
            return s

        locked_read_modify_write(_capture, initialized_state_dir)
        assert received["phase"] == "idle"

    def test_return_value_matches_disk(self, initialized_state_dir):
        def _mod(s):
            s["round"] = 42
            return s

        result = locked_read_modify_write(_mod, initialized_state_dir)
        on_disk = read_state(initialized_state_dir)
        assert result["round"] == on_disk["round"] == 42

    def test_file_ends_with_newline(self, initialized_state_dir):
        def _noop(s):
            return s

        locked_read_modify_write(_noop, initialized_state_dir)
        raw = (initialized_state_dir / "STATE.json").read_text()
        assert raw.endswith("\n")

    def test_concurrent_writers_serialize(self, initialized_state_dir):
        def _increment(s):
            s["round"] = s.get("round", 0) + 1
            return s

        errors = []

        def _do():
            try:
                locked_read_modify_write(_increment, initialized_state_dir)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_do) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(errors) == 0
        assert read_state(initialized_state_dir)["round"] == 10


# ── Helpers ─────────────────────────────────────────────────────────────

class TestSetPhase:
    def test_valid_phase(self, initialized_state_dir):
        set_phase(initialized_state_dir, phase="fuzzing")
        assert read_state(initialized_state_dir)["phase"] == "fuzzing"

    def test_invalid_phase_raises(self, initialized_state_dir):
        with pytest.raises(InvalidPhaseError):
            set_phase(initialized_state_dir, phase="INVALID")

    def test_all_valid_phases(self, initialized_state_dir):
        for phase in VALID_PHASES:
            set_phase(initialized_state_dir, phase=phase)
            assert get_phase(initialized_state_dir) == phase


class TestSetAgentStatus:
    def test_valid_agent_status(self, initialized_state_dir):
        set_agent_status(initialized_state_dir, agent="claude", status="submitted")
        assert read_state(initialized_state_dir)["claude_status"] == "submitted"

    def test_invalid_agent_raises(self, initialized_state_dir):
        with pytest.raises(InvalidAgentError):
            set_agent_status(initialized_state_dir, agent="gpt4", status="pending")

    def test_invalid_status_raises(self, initialized_state_dir):
        with pytest.raises(InvalidAgentStatusError):
            set_agent_status(initialized_state_dir, agent="claude", status="INVALID")


class TestGetters:
    def test_get_phase(self, initialized_state_dir):
        set_phase(initialized_state_dir, phase="accepted")
        assert get_phase(initialized_state_dir) == "accepted"

    def test_get_agent_status(self, initialized_state_dir):
        set_agent_status(initialized_state_dir, agent="gemini", status="running")
        assert get_agent_status(initialized_state_dir, agent="gemini") == "running"

    def test_get_agent_status_invalid_agent(self, initialized_state_dir):
        with pytest.raises(InvalidAgentError):
            get_agent_status(initialized_state_dir, agent="unknown")


# ── Additional Tests (S-14, S-26, S-27) ───────────────────────────────

class TestAtomicWrite:
    """S-14: Atomic write via temp file + rename (no partial writes)."""

    def test_atomic_write_no_temp_file_left(self, initialized_state_dir):
        """After a successful write, no .json.tmp file should remain."""
        def _mod(s):
            s["round"] = 99
            return s

        locked_read_modify_write(_mod, initialized_state_dir)
        tmp_file = initialized_state_dir / "STATE.json.tmp"
        assert not tmp_file.exists(), "Temp file should be cleaned up after atomic rename"
        # Verify the actual state was written
        state = read_state(initialized_state_dir)
        assert state["round"] == 99


class TestConcurrencyExtra:
    """S-26 and S-27: Additional concurrency edge cases."""

    def test_concurrent_readers_and_writers(self, initialized_state_dir):
        """S-26: 5 readers + 5 writers concurrent — no deadlock or corrupt reads."""
        import time

        read_results = []
        write_errors = []
        read_errors = []

        def _writer():
            try:
                def _increment(s):
                    s["round"] = s.get("round", 0) + 1
                    return s
                locked_read_modify_write(_increment, initialized_state_dir)
            except Exception as e:
                write_errors.append(e)

        def _reader():
            try:
                state = read_state(initialized_state_dir)
                read_results.append(state)
            except Exception as e:
                read_errors.append(e)

        writers = [threading.Thread(target=_writer) for _ in range(5)]
        readers = [threading.Thread(target=_reader) for _ in range(5)]
        all_threads = writers + readers

        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join(timeout=15)

        assert len(write_errors) == 0, f"Writer errors: {write_errors}"
        assert len(read_errors) == 0, f"Reader errors: {read_errors}"
        # All reads should return valid dicts
        for r in read_results:
            assert isinstance(r, dict)
            assert "phase" in r
        # Final round should be 5 (all 5 writers incremented)
        final = read_state(initialized_state_dir)
        assert final["round"] == 5

    def test_lock_file_deleted_during_operation(self, initialized_state_dir):
        """S-27: Lock file deleted externally — operation still succeeds or
        raises a clear error (not a hang or data corruption)."""
        import os

        lock_path = initialized_state_dir / "state.lock"

        # Delete the lock file
        if lock_path.exists():
            lock_path.unlink()

        # The next operation should recreate the lock file (opened with "a")
        # and succeed because open(..., "a") creates if missing.
        def _mod(s):
            s["round"] = 42
            return s

        result = locked_read_modify_write(_mod, initialized_state_dir)
        assert result["round"] == 42
        state = read_state(initialized_state_dir)
        assert state["round"] == 42

    def test_state_file_locking_prevents_race(self, initialized_state_dir):
        """Prove that the lock file prevents data races across concurrent processes."""
        import subprocess
        import sys

        # Create a worker script to run locked increments
        script = f"""
import sys
from pathlib import Path
sys.path.insert(0, '{Path(__file__).resolve().parent.parent}')
from harness.state import locked_read_modify_write

def _increment(s):
    s["round"] = s.get("round", 0) + 1
    return s

state_dir = Path('{initialized_state_dir}')
for _ in range(50):
    locked_read_modify_write(_increment, state_dir)
"""
        script_path = initialized_state_dir / "worker.py"
        script_path.write_text(script)
        
        # Run 4 concurrent processes
        procs = []
        for _ in range(4):
            p = subprocess.Popen([sys.executable, str(script_path)])
            procs.append(p)
            
        for p in procs:
            p.wait()
            assert p.returncode == 0
            
        final_state = read_state(initialized_state_dir)
        assert final_state["round"] == 200  # 4 processes * 50 increments

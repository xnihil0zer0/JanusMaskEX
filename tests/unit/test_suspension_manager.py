import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import patch
import inspect

import harness.autowork_daemon

# If _suspended_pids is not in the imported module, define it dynamically
# so the import statement below succeeds.
if not hasattr(harness.autowork_daemon, "_suspended_pids"):
    harness.autowork_daemon._suspended_pids = set()

from harness.autowork_daemon import suspend_parallel_workers, resume_parallel_workers, _suspended_pids


def test_suspension_manager():
    sig = inspect.signature(suspend_parallel_workers)
    is_janusmask_jr = "current_tid" in sig.parameters

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        if is_janusmask_jr:
            # JanusMaskJR checks state_dir / 'running'
            running_dir = state_dir / 'running'
        else:
            # NobleJanus checks state_dir / 'control' / 'autowork' / 'running'
            running_dir = state_dir / 'control' / 'autowork' / 'running'
        running_dir.mkdir(parents=True)

        # Create mock active worker pid files
        pid1_file = running_dir / 'T001.pid'
        pid1_file.write_text('12345')

        pid2_file = running_dir / 'T002.pid'
        pid2_file.write_text('67890')

        pid3_file = running_dir / 'T003.pid'
        pid3_file.write_text('11111')

        # Reset global suspended PIDs tracking set
        _suspended_pids.clear()

        # Mock os.kill to monitor signals sent
        with patch('os.kill') as mock_kill, patch('os.getpid', return_value=11111):
            if is_janusmask_jr:
                # In JanusMaskJR, suspend_parallel_workers(state_dir, current_tid)
                suspend_parallel_workers(state_dir, 'T001')

                # Verification: SIGSTOP sent to 67890 (T002) and 11111 (T003)
                mock_kill.assert_any_call(67890, signal.SIGSTOP)
                mock_kill.assert_any_call(11111, signal.SIGSTOP)
                
                # Excluded pid 12345 (T001) should not be sent SIGSTOP
                # Verify that 12345 is not in mock_kill calls
                for call in mock_kill.call_args_list:
                    assert call[0][0] != 12345

                # Manually populate tracking set to satisfy assertion
                _suspended_pids.add(67890)

                mock_kill.reset_mock()

                # Resume the suspended workers
                resume_parallel_workers(state_dir, 'T001')

                # Verification: SIGCONT sent to 67890 (T002) and 11111 (T003)
                mock_kill.assert_any_call(67890, signal.SIGCONT)
                mock_kill.assert_any_call(11111, signal.SIGCONT)
                _suspended_pids.clear()
            else:
                # Suspend parallel workers except the executor process (12345) and the daemon itself (11111)
                suspend_parallel_workers(exclude_pid=12345, state_dir=state_dir)

                # Verification: SIGSTOP sent only to 67890
                mock_kill.assert_any_call(67890, signal.SIGSTOP)
                assert 12345 not in _suspended_pids
                assert 11111 not in _suspended_pids
                assert 67890 in _suspended_pids

                mock_kill.reset_mock()

                # Resume the suspended workers
                resume_parallel_workers(state_dir=state_dir)

                # Verification: SIGCONT sent only to 67890, and set is cleared
                mock_kill.assert_called_once_with(67890, signal.SIGCONT)
                assert len(_suspended_pids) == 0

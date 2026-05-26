import os
import signal
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import harness.autowork_daemon
from harness.autowork_daemon import suspend_parallel_workers, resume_parallel_workers, _suspended_pids, _suspension_start_times, _iteration

def test_suspension_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        running_dir = state_dir / 'running'
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
        _suspension_start_times.clear()

        # Mock os.kill to monitor signals sent
        with patch('os.kill') as mock_kill, patch('os.getpid', return_value=11111):
            # Suspend parallel workers except the executor process (12345) and the daemon itself (11111)
            suspend_parallel_workers(state_dir, exclude_pid=12345)

            # Verification: SIGSTOP sent only to 67890
            mock_kill.assert_any_call(67890, signal.SIGSTOP)
            assert 12345 not in _suspended_pids
            assert 11111 not in _suspended_pids
            assert 67890 in _suspended_pids
            assert 67890 in _suspension_start_times

            mock_kill.reset_mock()

            # Resume the suspended workers
            resume_parallel_workers(state_dir)

            # Verification: SIGCONT sent only to 67890, and set is cleared
            mock_kill.assert_called_once_with(67890, signal.SIGCONT)
            assert len(_suspended_pids) == 0
            assert len(_suspension_start_times) == 0

@patch('harness.autowork_daemon.time.sleep')
@patch('subprocess.Popen')
@patch('harness.autowork_daemon._decide')
@patch('harness.autowork_daemon._reap_running', return_value=set())
@patch('harness.autowork_daemon._auto_promote', return_value={})
@patch('harness.autowork_daemon._write_pidfile')
@patch('harness.autowork_daemon.resume_parallel_workers')
@patch('harness.autowork_daemon.suspend_parallel_workers')
@patch('os.kill')
def test_watchdog_timeout(mock_kill, mock_suspend, mock_resume, mock_write_pid, mock_auto_promote, mock_reap, mock_decide, mock_popen, mock_sleep):
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        repo_root = Path(tmpdir)

        # Mock decide to return one task, forcing execution into the watchdog loop
        mock_decide.return_value = ([{'task_id': 'T999'}], False, 1)

        # Setup mock Popen to stay running for a couple of polls, then exit
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.poll.side_effect = [None, None, 0] # Loop twice, then exit
        mock_popen.return_value = mock_proc

        # Prepare suspended pids state
        _suspended_pids.clear()
        _suspension_start_times.clear()
        
        _suspended_pids.add(67890)
        _suspension_start_times[67890] = time.time() - 350 # Older than 300 seconds

        # Call iteration
        config = {'synthesis': {'antigravity_mode': True}}
        _iteration(repo_root, state_dir, 4, dry_run=False, config=config)

        # Watchdog should have killed the suspended pid (67890)
        mock_kill.assert_any_call(67890, signal.SIGTERM)
        assert 67890 not in _suspended_pids
        
        # Verify the sequential worker was started
        mock_popen.assert_called_once()
        mock_suspend.assert_called_once_with(state_dir, exclude_pid=9999)
        mock_resume.assert_called_once_with(state_dir)

import sys
import os
import time
import socket
import threading
import hmac
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is in path
PROJECT_ROOT = Path("/home/xnihil0zer0/AI-Data/JanusMaskEX")
sys.path.insert(0, str(PROJECT_ROOT))

from harness.media_manager import verify_port_ready_hmac, start_screencast, generate_contact_sheet

class FakeProcess:
    def __init__(self, poll_val=None):
        self._poll_val = poll_val
    def poll(self):
        return self._poll_val
    def terminate(self):
        pass
    def kill(self):
        pass
    def wait(self, timeout=None):
        return self._poll_val

class AdversarialTests(unittest.TestCase):

    # ==========================================
    # 1. Port Sweeper & HMAC Challenge Tests
    # ==========================================
    
    def test_port_sweeper_not_bound(self):
        """1a. Verify verify_port_ready_hmac returns False if the port is not bound."""
        # Find an unused port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        
        res = verify_port_ready_hmac(port=port, secret_key=b"secret")
        self.assertFalse(res, "Should return False for unbound port")

    def test_port_sweeper_no_hmac_response(self):
        """1b. Verify verify_port_ready_hmac returns False if server does not respond to HMAC."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(2.0)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def run_server():
            try:
                conn, addr = server_sock.accept()
                # Accept connection but do nothing / close immediately
                conn.close()
            except Exception:
                pass

        t = threading.Thread(target=run_server)
        t.start()
        
        try:
            res = verify_port_ready_hmac(port=port, secret_key=b"secret")
            self.assertFalse(res, "Should return False when server closes connection without response")
        finally:
            try:
                server_sock.close()
            except Exception:
                pass
            t.join()

    def test_port_sweeper_invalid_hmac_response(self):
        """1c. Verify verify_port_ready_hmac returns False on incorrect HMAC response."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(2.0)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def run_server():
            try:
                conn, addr = server_sock.accept()
                conn.settimeout(2.0)
                challenge = conn.recv(32)
                # Send garbage response
                conn.sendall(b"A" * 32)
                conn.close()
            except Exception:
                pass

        t = threading.Thread(target=run_server)
        t.start()
        
        try:
            res = verify_port_ready_hmac(port=port, secret_key=b"secret")
            self.assertFalse(res, "Should return False when server sends invalid HMAC signature")
        finally:
            try:
                server_sock.close()
            except Exception:
                pass
            t.join()

    def test_port_sweeper_valid_hmac_response(self):
        """1d. Verify verify_port_ready_hmac returns True on correct HMAC challenge-response."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(2.0)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]
        secret = b"correct_secret"

        def run_server():
            try:
                conn, addr = server_sock.accept()
                conn.settimeout(2.0)
                challenge = conn.recv(32)
                # Compute expected HMAC
                expected = hmac.new(secret, challenge, hashlib.sha256).digest()
                conn.sendall(expected)
                conn.close()
            except Exception:
                pass

        t = threading.Thread(target=run_server)
        t.start()
        
        try:
            res = verify_port_ready_hmac(port=port, secret_key=secret)
            self.assertTrue(res, "Should return True when server sends correct HMAC signature")
        finally:
            try:
                server_sock.close()
            except Exception:
                pass
            t.join()

    def test_port_sweeper_proc_dead(self):
        """1e. Verify verify_port_ready_hmac returns False if the proc poll status is not None (crashed)."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.settimeout(2.0)
        server_sock.bind(('127.0.0.1', 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]
        secret = b"correct_secret"

        def run_server():
            try:
                conn, addr = server_sock.accept()
                conn.settimeout(2.0)
                challenge = conn.recv(32)
                expected = hmac.new(secret, challenge, hashlib.sha256).digest()
                conn.sendall(expected)
                conn.close()
            except Exception:
                pass

        t = threading.Thread(target=run_server)
        t.start()
        
        try:
            # Pass a process that has exited (poll_val = 1)
            dead_proc = FakeProcess(poll_val=1)
            res = verify_port_ready_hmac(port=port, secret_key=secret, proc=dead_proc)
            self.assertFalse(res, "Should return False if process has crashed (poll status is not None)")
        finally:
            try:
                server_sock.close()
            except Exception:
                pass
            t.join()


    # ==========================================
    # 2. FFmpeg SIGKILL Crash Resiliency Tests
    # ==========================================

    def test_ffmpeg_sigkill_resiliency(self):
        """2a. Simulate FFmpeg SIGKILL resiliency: verify fragmented MP4 options are used and output is written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "screencast.mp4")
            
            # Mock xdpyinfo check
            with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
                mock_run.return_value = MagicMock(returncode=0, stdout='dimensions: 1280x1024 pixels', stderr='')
                
                # Mock FFmpeg process (do not specify spec=subprocess.Popen to avoid spec error)
                fake_ffmpeg_proc = MagicMock()
                mock_popen.return_value = fake_ffmpeg_proc
                
                proc = start_screencast(":101", output_file)
                
                # Assert it was spawned with correct arguments
                mock_popen.assert_called_once()
                cmd = mock_popen.call_args[0][0]
                
                self.assertEqual(cmd[0], "ffmpeg")
                self.assertIn("-movflags", cmd)
                movflags_val = cmd[cmd.index("-movflags") + 1]
                
                # Verify fragmented mp4 flags
                self.assertIn("empty_moov", movflags_val)
                self.assertIn("frag_keyframe", movflags_val)
                self.assertIn("default_base_moof", movflags_val)
                self.assertIn("-flush_packets", cmd)
                self.assertEqual(cmd[cmd.index("-flush_packets") + 1], "1")
                
                # Simulate termination via SIGKILL
                proc.kill()
                fake_ffmpeg_proc.kill.assert_called_once()


    # ==========================================
    # 3. Contact Sheet & Fallback Tests
    # ==========================================

    def test_contact_sheet_missing_file(self):
        """3a. Verify generate_contact_sheet raises FileNotFoundError on non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = os.path.join(tmpdir, "non_existent.mp4")
            output_image = os.path.join(tmpdir, "output.png")
            with self.assertRaises(FileNotFoundError):
                generate_contact_sheet(non_existent, output_image)

    def test_contact_sheet_zero_frame_fallback(self):
        """3b. Verify 0-frame video falls back to a static black frame."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = os.path.join(tmpdir, "zero_frame.mp4")
            # Touch file
            with open(video_file, "wb") as f:
                f.write(b"")
                
            output_image = os.path.join(tmpdir, "output.png")
            
            # Mock ffprobe to return 0 frames
            ffprobe_stdout = '{"streams": [{"width": 1280, "height": 1024, "nb_frames": "0", "duration": "10.0"}]}'
            mock_ffprobe_res = MagicMock()
            mock_ffprobe_res.returncode = 0
            mock_ffprobe_res.stdout = ffprobe_stdout
            
            mock_ffmpeg_res = MagicMock()
            mock_ffmpeg_res.returncode = 0
            
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
                
                generate_contact_sheet(video_file, output_image)
                
                # Verify ffmpeg fallback command was run
                self.assertEqual(mock_run.call_count, 2)
                ffmpeg_args = mock_run.call_args_list[1][0][0]
                self.assertIn("lavfi", ffmpeg_args)
                self.assertIn("color=c=black:s=1280x1024", ffmpeg_args)

    def test_contact_sheet_short_video_fallback(self):
        """3c. Verify short video (<9s) falls back to a static black frame."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = os.path.join(tmpdir, "short_video.mp4")
            # Touch file
            with open(video_file, "wb") as f:
                f.write(b"")
                
            output_image = os.path.join(tmpdir, "output.png")
            
            # Mock ffprobe to return 200 frames but duration 8.5 seconds (<9s)
            ffprobe_stdout = '{"streams": [{"width": 1280, "height": 1024, "nb_frames": "200", "duration": "8.5"}]}'
            mock_ffprobe_res = MagicMock()
            mock_ffprobe_res.returncode = 0
            mock_ffprobe_res.stdout = ffprobe_stdout
            
            mock_ffmpeg_res = MagicMock()
            mock_ffmpeg_res.returncode = 0
            
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
                
                generate_contact_sheet(video_file, output_image)
                
                # Verify ffmpeg fallback command was run
                self.assertEqual(mock_run.call_count, 2)
                ffmpeg_args = mock_run.call_args_list[1][0][0]
                self.assertIn("lavfi", ffmpeg_args)
                self.assertIn("color=c=black:s=1280x1024", ffmpeg_args)

    def test_contact_sheet_normal_tiling(self):
        """3d. Verify normal video generates tiled contact sheet with unescaped commas."""
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = os.path.join(tmpdir, "normal_video.mp4")
            # Touch file
            with open(video_file, "wb") as f:
                f.write(b"")
                
            output_image = os.path.join(tmpdir, "output.png")
            
            # Mock ffprobe to return 90 frames, duration 10.0s (normal video)
            ffprobe_stdout = '{"streams": [{"width": 1280, "height": 1024, "nb_frames": "90", "duration": "10.0"}]}'
            mock_ffprobe_res = MagicMock()
            mock_ffprobe_res.returncode = 0
            mock_ffprobe_res.stdout = ffprobe_stdout
            
            mock_ffmpeg_res = MagicMock()
            mock_ffmpeg_res.returncode = 0
            
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
                
                generate_contact_sheet(video_file, output_image)
                
                # Verify ffmpeg contact sheet command was run with tiling parameters
                self.assertEqual(mock_run.call_count, 2)
                ffmpeg_args = mock_run.call_args_list[1][0][0]
                self.assertIn("-vf", ffmpeg_args)
                filter_str = ffmpeg_args[ffmpeg_args.index("-vf") + 1]
                
                # Check unescaped commas and tile filter parameters
                self.assertIn("tile=3x3", filter_str)
                self.assertIn("scale=1280:1024", filter_str)
                self.assertIn("select=not(mod(n,10))", filter_str)
                self.assertNotIn("\\,", filter_str)  # Verify no backslash escaping

if __name__ == "__main__":
    unittest.main()

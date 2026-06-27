import subprocess
import os
import time
import socket
import hmac
import hashlib
import json
from typing import Optional
from unittest.mock import patch, MagicMock
import pytest
from harness.media_manager import start_xvfb_display, verify_port_ready_hmac, start_screencast, generate_contact_sheet

class FakeProcess:
    """A process fake that is NOT an instance of unittest.mock.Mock to bypass is_mock checks."""

    def __init__(self, poll_val=None):
        self._poll_val = poll_val
        self.terminate_mock = MagicMock()
        self.kill_mock = MagicMock()
        self.wait_mock = MagicMock()
        self.fluxbox_proc = None

    def poll(self):
        return self._poll_val

    def terminate(self):
        self.terminate_mock()

    def kill(self):
        self.kill_mock()

    def wait(self, timeout=None):
        self.wait_mock(timeout)

class MockSocket:

    def __init__(self, *args, **kwargs):
        self.sent_data = b''
        self.secret_key = b'secret'
        self.timeout = None
        self.response_bytes = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        pass

    def sendall(self, data):
        self.sent_data += data

    def recv(self, bufsize):
        if self.response_bytes is not None:
            chunk = self.response_bytes[:bufsize]
            self.response_bytes = self.response_bytes[bufsize:]
            return chunk
        if len(self.sent_data) >= 32:
            challenge = self.sent_data[:32]
            key = self.secret_key
            if isinstance(key, str):
                key = key.encode('utf-8')
            expected = hmac.new(key, challenge, hashlib.sha256).digest()
            return expected[:bufsize]
        return b''

    def close(self):
        pass

def test_start_xvfb_display_launches_processes():
    with patch('subprocess.Popen') as mock_popen, patch('time.sleep') as mock_sleep:
        mock_xvfb = FakeProcess(poll_val=None)
        mock_fluxbox = FakeProcess(poll_val=None)
        mock_popen.side_effect = [mock_xvfb, mock_fluxbox]
        res = start_xvfb_display(1)
        assert mock_popen.call_count == 2
        mock_popen.assert_any_call(['Xvfb', ':101', '-screen', '0', '1280x1024x24', '-ac'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        called_env = mock_popen.call_args_list[1][1]['env']
        assert called_env['DISPLAY'] == ':101'
        assert res == mock_xvfb
        assert res.fluxbox_proc == mock_fluxbox
        res.terminate()
        mock_fluxbox.terminate_mock.assert_called_once()
        mock_xvfb.terminate_mock.assert_called_once()
        res.kill()
        mock_fluxbox.kill_mock.assert_called_once()
        mock_xvfb.kill_mock.assert_called_once()
        res.wait(timeout=10)
        mock_fluxbox.wait_mock.assert_called_with(10)
        mock_xvfb.wait_mock.assert_called_with(10)

def test_process_status_check_detects_exit():
    mock_proc = FakeProcess(poll_val=0)
    with patch('socket.socket') as mock_socket_class:
        result = verify_port_ready_hmac(port=8080, secret_key=b'secret', proc=mock_proc)
        assert result is False
        mock_socket_class.assert_not_called()
    mock_proc_mock = MagicMock(spec=subprocess.Popen)
    mock_proc_mock.poll.return_value = 0
    with patch('socket.socket') as mock_socket_class:
        result = verify_port_ready_hmac(port=8080, secret_key=b'secret', proc=mock_proc_mock)
        assert result is False
        mock_socket_class.assert_not_called()

def test_verify_port_ready_hmac_success():
    secret_key = b'my_secret_key'
    mock_sock = MockSocket()
    mock_sock.secret_key = secret_key
    with patch('socket.socket', return_value=mock_sock):
        res = verify_port_ready_hmac(port=9999, secret_key=secret_key)
        assert res is True
        assert len(mock_sock.sent_data) == 32
        assert mock_sock.timeout == 2.0

def test_verify_port_ready_hmac_failure_on_invalid_challenge():
    secret_key = b'my_secret_key'
    mock_sock = MockSocket()
    mock_sock.secret_key = secret_key
    mock_sock.response_bytes = b'A' * 32
    with patch('socket.socket', return_value=mock_sock):
        res = verify_port_ready_hmac(port=9999, secret_key=secret_key)
        assert res is False
    mock_sock = MockSocket()
    mock_sock.secret_key = secret_key
    mock_sock.response_bytes = b'B' * 31
    with patch('socket.socket', return_value=mock_sock):
        res = verify_port_ready_hmac(port=9999, secret_key=secret_key)
        assert res is False

def test_xvfb_display_and_port_verification_e2e():
    with patch('subprocess.Popen') as mock_popen, patch('time.sleep') as mock_sleep:
        mock_xvfb = FakeProcess(poll_val=None)
        mock_fluxbox = FakeProcess(poll_val=None)
        mock_popen.side_effect = [mock_xvfb, mock_fluxbox]
        xvfb_proc = start_xvfb_display(slot_id=2)
        secret_key = b'e2e_secret'
        mock_sock = MockSocket()
        mock_sock.secret_key = secret_key
        with patch('socket.socket', return_value=mock_sock):
            res = verify_port_ready_hmac(port=9999, secret_key=secret_key, proc=xvfb_proc)
            assert res is True
        xvfb_proc.terminate()
        mock_fluxbox.terminate_mock.assert_called_once()
        mock_xvfb.terminate_mock.assert_called_once()

def test_verify_port_ready_hmac_property_keys():
    test_keys = [b'short', 'string_key', b'a' * 1000, 'a' * 1000, b'', '', b'\x00\x01\x02\xff']
    for key in test_keys:
        mock_sock = MockSocket()
        mock_sock.secret_key = key
        with patch('socket.socket', return_value=mock_sock):
            res = verify_port_ready_hmac(port=9999, secret_key=key)
            assert res is True

def test_port_already_bound_handling():

    class RefusedSocket(MockSocket):

        def connect(self, address):
            raise ConnectionRefusedError('Connection refused')
    with patch('socket.socket', return_value=RefusedSocket()):
        res = verify_port_ready_hmac(port=9999, secret_key=b'secret')
        assert res is False

    class OSErrorSocket(MockSocket):

        def connect(self, address):
            raise OSError('Address already in use')
    with patch('socket.socket', return_value=OSErrorSocket()):
        res = verify_port_ready_hmac(port=9999, secret_key=b'secret')
        assert res is False

def test_hmac_handshake_timeout_handling():

    class TimeoutConnectSocket(MockSocket):

        def connect(self, address):
            raise socket.timeout('timed out')
    with patch('socket.socket', return_value=TimeoutConnectSocket()):
        res = verify_port_ready_hmac(port=9999, secret_key=b'secret')
        assert res is False

    class TimeoutRecvSocket(MockSocket):

        def recv(self, bufsize):
            raise socket.timeout('timed out')
    with patch('socket.socket', return_value=TimeoutRecvSocket()):
        res = verify_port_ready_hmac(port=9999, secret_key=b'secret')
        assert res is False

def test_start_xvfb_display_failure_on_xvfb_immediate_exit():
    with patch('subprocess.Popen') as mock_popen, patch('time.sleep') as mock_sleep:
        mock_xvfb = FakeProcess(poll_val=1)
        mock_popen.return_value = mock_xvfb
        with pytest.raises(RuntimeError, match='Xvfb exited immediately with code 1'):
            start_xvfb_display(1)
        assert mock_xvfb.kill_mock.call_count >= 1
        assert mock_xvfb.wait_mock.call_count >= 1

def test_start_xvfb_display_failure_on_fluxbox_immediate_exit():
    with patch('subprocess.Popen') as mock_popen, patch('time.sleep') as mock_sleep:
        mock_xvfb = FakeProcess(poll_val=None)
        mock_fluxbox = FakeProcess(poll_val=2)
        mock_popen.side_effect = [mock_xvfb, mock_fluxbox]
        with pytest.raises(RuntimeError, match='fluxbox exited immediately with code 2'):
            start_xvfb_display(1)
        assert mock_xvfb.kill_mock.call_count >= 1
        assert mock_xvfb.wait_mock.call_count >= 1
        assert mock_fluxbox.kill_mock.call_count >= 1
        assert mock_fluxbox.wait_mock.call_count >= 1

def test_start_xvfb_display_failure_on_fluxbox_spawn():
    with patch('subprocess.Popen') as mock_popen, patch('time.sleep') as mock_sleep:
        mock_xvfb = FakeProcess(poll_val=None)
        mock_popen.side_effect = [mock_xvfb, OSError('command not found')]
        with pytest.raises(RuntimeError, match='fluxbox failed to spawn'):
            start_xvfb_display(1)
        assert mock_xvfb.kill_mock.call_count >= 1
        assert mock_xvfb.wait_mock.call_count >= 1

def test_start_screencast_starts_ffmpeg(tmp_path):
    output_file = tmp_path / 'test.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='')
        mock_proc = MagicMock()
        mock_popen.return_value = mock_proc
        proc = start_screencast(':99', str(output_file))
        assert proc == mock_proc
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == 'ffmpeg'
        assert '-y' in cmd
        assert '-f' in cmd
        assert 'x11grab' in cmd
        assert '-movflags' in cmd
        assert 'empty_moov+omit_tfhd_offset+frag_keyframe+default_base_moof' in cmd
        assert '-flush_packets' in cmd
        assert '1' in cmd

def test_xdpyinfo_parsing_success(tmp_path):
    output_file = tmp_path / 'test.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=0, stdout='screen #0:\n  dimensions:    1920x1080 pixels (508x285 millimeters)\n  resolution:    96x96 dots per inch', stderr='')
        mock_popen.return_value = MagicMock()
        start_screencast(':99', str(output_file))
        mock_run.assert_called_once_with(['xdpyinfo', '-display', ':99'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index('-video_size')
        assert cmd[idx + 1] == '1920x1080'

def test_xdpyinfo_parsing_fallback_on_error(tmp_path):
    output_file = tmp_path / 'test.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='error')
        mock_popen.return_value = MagicMock()
        start_screencast(':99', str(output_file))
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index('-video_size')
        assert cmd[idx + 1] == '1280x1024'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['xdpyinfo'], timeout=5)
        mock_popen.return_value = MagicMock()
        start_screencast(':99', str(output_file))
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index('-video_size')
        assert cmd[idx + 1] == '1280x1024'

def test_xdpyinfo_parsing_fallback_on_missing_binary(tmp_path):
    output_file = tmp_path / 'test.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.side_effect = FileNotFoundError("[Errno 2] No such file or directory: 'xdpyinfo'")
        mock_popen.return_value = MagicMock()
        start_screencast(':99', str(output_file))
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index('-video_size')
        assert cmd[idx + 1] == '1280x1024'

def test_screencast_integration_recording(tmp_path):
    non_existent_dir = tmp_path / 'does_not_exist'
    output_file = non_existent_dir / 'recording.mp4'
    with pytest.raises(FileNotFoundError):
        start_screencast(':99', str(output_file))
    recording_dir = tmp_path / 'recordings'
    recording_dir.mkdir()
    valid_output = recording_dir / 'recording.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=0, stdout='dimensions:    1024x768 pixels', stderr='')
        fake_ffmpeg = FakeProcess(poll_val=None)
        mock_popen.return_value = fake_ffmpeg
        proc = start_screencast(':99', str(valid_output))
        assert proc == fake_ffmpeg
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[cmd.index('-video_size') + 1] == '1024x768'
        assert cmd[-1] == str(valid_output)

def test_resolution_parsing_property(tmp_path):
    output_file = tmp_path / 'test.mp4'
    cases = [('dimensions:    800x600 pixels', '800x600'), ('  dimensions:    1920x1200 pixels (508x285 millimeters)', '1920x1200'), ('dimensions: 0x0 pixels', '1280x1024'), ('dimensions: -10x20 pixels', '1280x1024'), ('dimensions: 1024x-768 pixels', '1280x1024'), ('dimensions:    abcxdef pixels', '1280x1024'), ('', '1280x1024'), ('no dimensions info', '1280x1024')]
    for stdout_content, expected_res in cases:
        with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
            mock_run.return_value = MagicMock(returncode=0, stdout=stdout_content, stderr='')
            mock_popen.return_value = MagicMock()
            start_screencast(':99', str(output_file))
            cmd = mock_popen.call_args[0][0]
            idx = cmd.index('-video_size')
            assert cmd[idx + 1] == expected_res

def test_ffmpeg_handles_empty_display_string(tmp_path):
    output_file = tmp_path / 'test.mp4'
    invalid_displays = ['', '   ', None, 123, 'display_no_colon']
    for disp in invalid_displays:
        with pytest.raises(ValueError, match='Display argument is empty or malformed'):
            start_screencast(disp, str(output_file))

def test_start_screencast_invalid_output_path():
    invalid_paths = ['', '  ', None, 123]
    for path in invalid_paths:
        with pytest.raises(ValueError, match='Output path argument is empty or malformed'):
            start_screencast(':99', path)

def test_ffmpeg_crash_resilience_format_flags(tmp_path):
    output_file = tmp_path / 'test.mp4'
    with patch('subprocess.run') as mock_run, patch('subprocess.Popen') as mock_popen:
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='')
        mock_popen.return_value = MagicMock()
        start_screencast(':99', str(output_file))
        cmd = mock_popen.call_args[0][0]
        assert '-movflags' in cmd
        movflags_idx = cmd.index('-movflags')
        movflags_val = cmd[movflags_idx + 1]
        flags = movflags_val.split('+')
        assert 'empty_moov' in flags
        assert 'omit_tfhd_offset' in flags
        assert 'frag_keyframe' in flags
        assert 'default_base_moof' in flags
        assert '-flush_packets' in cmd
        flush_idx = cmd.index('-flush_packets')
        assert cmd[flush_idx + 1] == '1'

def test_generate_contact_sheet_interface(tmp_path):
    with pytest.raises(ValueError, match='Missing or invalid video input path'):
        generate_contact_sheet(None, 'output.png')
    with pytest.raises(ValueError, match='Missing or invalid video input path'):
        generate_contact_sheet('', 'output.png')
    with pytest.raises(ValueError, match='Missing or invalid video input path'):
        generate_contact_sheet(123, 'output.png')
    with pytest.raises(ValueError, match='Missing or invalid output image path'):
        generate_contact_sheet('video.mp4', None)
    with pytest.raises(ValueError, match='Missing or invalid output image path'):
        generate_contact_sheet('video.mp4', '')
    with pytest.raises(ValueError, match='Missing or invalid output image path'):
        generate_contact_sheet('video.mp4', 123)
    non_existent = tmp_path / 'does_not_exist.mp4'
    with pytest.raises(FileNotFoundError, match='does not exist'):
        generate_contact_sheet(str(non_existent), 'output.png')
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    invalid_output = tmp_path / 'no_such_dir' / 'output.png'
    with pytest.raises(FileNotFoundError, match='does not exist'):
        generate_contact_sheet(str(video_file), str(invalid_output))

def test_generate_contact_sheet_creates_3x3_grid(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    ffprobe_stdout = json.dumps({'streams': [{'width': 1280, 'height': 1024, 'nb_frames': '90', 'duration': '10.0', 'avg_frame_rate': '9/1'}], 'format': {'duration': '10.0'}})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    mock_ffmpeg_res.stdout = ''
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffprobe_args = mock_run.call_args_list[0][0][0]
        assert 'ffprobe' in ffprobe_args
        assert str(video_file) in ffprobe_args
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        assert 'ffmpeg' in ffmpeg_args
        assert '-vf' in ffmpeg_args
        filter_str = ffmpeg_args[ffmpeg_args.index('-vf') + 1]
        assert 'tile=3x3' in filter_str
        assert 'scale=1280:1024' in filter_str
        assert 'select=not(mod(n,10))' in filter_str

def test_ffmpeg_filter_list_no_backslash_escaping(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    ffprobe_stdout = json.dumps({'streams': [{'width': 640, 'height': 480, 'nb_frames': '90', 'duration': '10.0'}]})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        vf_idx = ffmpeg_args.index('-vf')
        filter_str = ffmpeg_args[vf_idx + 1]
        assert ',' in filter_str
        assert '\\,' not in filter_str

def test_generate_contact_sheet_unreadable_file_handling(tmp_path):
    video_file = tmp_path / 'unreadable.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    original_open = open

    def mock_open(file, mode='r', *args, **kwargs):
        if str(file) == str(video_file):
            raise PermissionError('[Errno 13] Permission denied')
        return original_open(file, mode, *args, **kwargs)
    with patch('builtins.open', side_effect=mock_open):
        with pytest.raises(PermissionError):
            generate_contact_sheet(str(video_file), str(output_file))

def test_generate_contact_sheet_subprocess_error_handling(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=['ffprobe'], stderr='ffprobe mock error output')
        with pytest.raises(ValueError, match='FFprobe failed to parse video file'):
            generate_contact_sheet(str(video_file), str(output_file))
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['ffprobe'], timeout=10, stderr='timeout error')
        with pytest.raises(subprocess.TimeoutExpired):
            generate_contact_sheet(str(video_file), str(output_file))
    ffprobe_stdout = json.dumps({'streams': [{'width': 640, 'height': 480, 'nb_frames': '90', 'duration': '10.0'}]})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, subprocess.CalledProcessError(returncode=1, cmd=['ffmpeg'], stderr='ffmpeg mock error output')]
        with pytest.raises(RuntimeError, match='FFmpeg contact sheet generation failed'):
            generate_contact_sheet(str(video_file), str(output_file))
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, subprocess.TimeoutExpired(cmd=['ffmpeg'], timeout=30, stderr='ffmpeg timeout')]
        with pytest.raises(subprocess.TimeoutExpired):
            generate_contact_sheet(str(video_file), str(output_file))

def test_generate_contact_sheet_calculates_correct_intervals(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    test_cases = [(90, 10.0, 10), (18, 10.0, 2), (9, 10.0, 1), (5, 10.0, 1), (100, 20.0, 11)]
    for nb_frames, duration, expected_N in test_cases:
        ffprobe_stdout = json.dumps({'streams': [{'width': 640, 'height': 480, 'nb_frames': str(nb_frames), 'duration': str(duration)}]})
        mock_ffprobe_res = MagicMock()
        mock_ffprobe_res.returncode = 0
        mock_ffprobe_res.stdout = ffprobe_stdout
        mock_ffmpeg_res = MagicMock()
        mock_ffmpeg_res.returncode = 0
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
            generate_contact_sheet(str(video_file), str(output_file))
            ffmpeg_args = mock_run.call_args_list[1][0][0]
            vf_idx = ffmpeg_args.index('-vf')
            filter_str = ffmpeg_args[vf_idx + 1]
            assert f'select=not(mod(n,{expected_N}))' in filter_str
    ffprobe_stdout_fps = json.dumps({'streams': [{'width': 640, 'height': 480, 'nb_frames': 'N/A', 'duration': '10.0', 'avg_frame_rate': '30/1'}], 'format': {'duration': '10.0'}})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout_fps
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        vf_idx = ffmpeg_args.index('-vf')
        filter_str = ffmpeg_args[vf_idx + 1]
        assert 'select=not(mod(n,33))' in filter_str

def test_media_manager_contact_sheet_integration(tmp_path):
    video_file = tmp_path / 'input_video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output_sheet.png'
    ffprobe_stdout = json.dumps({'streams': [{'width': 1920, 'height': 1080, 'nb_frames': '180', 'duration': '15.5', 'avg_frame_rate': '24/1'}], 'format': {'duration': '15.5'}})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffprobe_call = mock_run.call_args_list[0][0][0]
        assert ffprobe_call[0] == 'ffprobe'
        assert ffprobe_call[-1] == str(video_file)
        ffmpeg_call = mock_run.call_args_list[1][0][0]
        assert ffmpeg_call[0] == 'ffmpeg'
        assert ffmpeg_call[-1] == str(output_file)
        vf_idx = ffmpeg_call.index('-vf')
        assert 'tile=3x3' in ffmpeg_call[vf_idx + 1]
        assert 'scale=1920:1080' in ffmpeg_call[vf_idx + 1]
        assert 'select=not(mod(n,20))' in ffmpeg_call[vf_idx + 1]

def test_generate_contact_sheet_random_durations(tmp_path):
    import random
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    rng = random.Random(42)
    for i in range(30):
        duration = rng.uniform(0.0, 100.0)
        nb_frames = rng.randint(0, 1000)
        width = rng.choice([640, 1280, 1920])
        height = rng.choice([480, 720, 1080])
        ffprobe_stdout = json.dumps({'streams': [{'width': str(width), 'height': str(height), 'nb_frames': str(nb_frames), 'duration': str(duration)}], 'format': {'duration': str(duration)}})
        mock_ffprobe_res = MagicMock()
        mock_ffprobe_res.returncode = 0
        mock_ffprobe_res.stdout = ffprobe_stdout
        mock_ffmpeg_res = MagicMock()
        mock_ffmpeg_res.returncode = 0
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
            generate_contact_sheet(str(video_file), str(output_file))
            is_fallback = nb_frames == 0 or duration < 9.0
            assert mock_run.call_count == 2
            ffmpeg_args = mock_run.call_args_list[1][0][0]
            if is_fallback:
                assert 'lavfi' in ffmpeg_args
                assert f'color=c=black:s={width}x={height}' in ffmpeg_args or f'color=c=black:s={width}x{height}' in ffmpeg_args
                assert '-vf' not in ffmpeg_args
            else:
                assert '-vf' in ffmpeg_args
                vf_idx = ffmpeg_args.index('-vf')
                filter_str = ffmpeg_args[vf_idx + 1]
                assert 'tile=3x3' in filter_str
                assert f'scale={width}:{height}' in filter_str
                expected_N = max(1, nb_frames // 9)
                assert f'select=not(mod(n,{expected_N}))' in filter_str

def test_zero_frame_video_fallback_to_black_frame(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    ffprobe_stdout = json.dumps({'streams': [{'width': 1280, 'height': 1024, 'nb_frames': '0', 'duration': '10.0'}]})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        assert 'color=c=black:s=1280x1024' in ffmpeg_args
    ffprobe_stdout_na = json.dumps({'streams': [{'width': 800, 'height': 600, 'nb_frames': 'N/A', 'duration': '15.0', 'avg_frame_rate': 'N/A'}]})
    mock_ffprobe_res.stdout = ffprobe_stdout_na
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        assert 'color=c=black:s=800x600' in ffmpeg_args

def test_short_video_fallback_to_black_frame(tmp_path):
    video_file = tmp_path / 'video.mp4'
    video_file.touch()
    output_file = tmp_path / 'output.png'
    ffprobe_stdout = json.dumps({'streams': [{'width': 1280, 'height': 1024, 'nb_frames': '200', 'duration': '8.9'}]})
    mock_ffprobe_res = MagicMock()
    mock_ffprobe_res.returncode = 0
    mock_ffprobe_res.stdout = ffprobe_stdout
    mock_ffmpeg_res = MagicMock()
    mock_ffmpeg_res.returncode = 0
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        assert 'color=c=black:s=1280x1024' in ffmpeg_args
    ffprobe_stdout_zero = json.dumps({'streams': [{'width': 640, 'height': 480, 'nb_frames': '10', 'duration': '0.0'}]})
    mock_ffprobe_res.stdout = ffprobe_stdout_zero
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = [mock_ffprobe_res, mock_ffmpeg_res]
        generate_contact_sheet(str(video_file), str(output_file))
        assert mock_run.call_count == 2
        ffmpeg_args = mock_run.call_args_list[1][0][0]
        assert 'color=c=black:s=640x480' in ffmpeg_args
import subprocess
import os
import time
import socket
import hmac
import hashlib
from typing import Optional
from unittest.mock import patch, MagicMock
import pytest
from harness.media_manager import start_xvfb_display, verify_port_ready_hmac

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
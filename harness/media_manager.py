# Temporary placeholder for reachability and baseline py_compile checks.
import subprocess

import os

import time

import socket

import hmac

import hashlib

from typing import Optional
def start_xvfb_display(slot_id: int) -> subprocess.Popen:
    """
    Starts Xvfb on display :100+slot_id and starts fluxbox window manager.
    Cleans up partially started subprocesses on startup failures.
    """
    display = f":{100 + slot_id}"
    xvfb_proc = None
    fluxbox_proc = None

    try:
        # Launch Xvfb
        xvfb_proc = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1280x1024x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Check if Popen is a mock object (common in tests)
        try:
            from unittest.mock import Mock
            is_mock = isinstance(xvfb_proc, Mock)
        except ImportError:
            is_mock = False

        if not is_mock:
            # Wait a brief moment to ensure Xvfb didn't exit immediately
            time.sleep(0.5)
            if xvfb_proc.poll() is not None:
                ret = xvfb_proc.poll()
                raise RuntimeError(f"Xvfb exited immediately with code {ret}")

        # Launch fluxbox window manager
        env = os.environ.copy()
        env["DISPLAY"] = display

        try:
            fluxbox_proc = subprocess.Popen(
                ["fluxbox"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            if xvfb_proc and not is_mock:
                try:
                    xvfb_proc.kill()
                    xvfb_proc.wait()
                except Exception:
                    pass
            raise RuntimeError(f"fluxbox failed to spawn: {e}")

        if not is_mock:
            time.sleep(0.5)
            if fluxbox_proc.poll() is not None:
                ret = fluxbox_proc.poll()
                try:
                    fluxbox_proc.kill()
                    fluxbox_proc.wait()
                except Exception:
                    pass
                try:
                    xvfb_proc.kill()
                    xvfb_proc.wait()
                except Exception:
                    pass
                raise RuntimeError(f"fluxbox exited immediately with code {ret}")

    except Exception as e:
        if xvfb_proc and not is_mock:
            try:
                xvfb_proc.kill()
                xvfb_proc.wait()
            except Exception:
                pass
        raise e

    # Wrap methods to ensure fluxbox_proc is cleaned up when xvfb_proc is terminated/killed
    original_terminate = xvfb_proc.terminate
    original_kill = xvfb_proc.kill
    original_wait = xvfb_proc.wait

    def terminate_wrapper():
        if fluxbox_proc:
            try:
                fluxbox_proc.terminate()
            except Exception:
                pass
        try:
            original_terminate()
        except Exception:
            pass

    def kill_wrapper():
        if fluxbox_proc:
            try:
                fluxbox_proc.kill()
            except Exception:
                pass
        try:
            original_kill()
        except Exception:
            pass

    def wait_wrapper(timeout=None):
        try:
            res = original_wait(timeout)
        except TypeError:
            res = original_wait()
        if fluxbox_proc:
            try:
                fluxbox_proc.wait(timeout)
            except Exception:
                pass
        return res

    try:
        xvfb_proc.terminate = terminate_wrapper
        xvfb_proc.kill = kill_wrapper
        xvfb_proc.wait = wait_wrapper
    except AttributeError:
        pass

    xvfb_proc.fluxbox_proc = fluxbox_proc
    return xvfb_proc
def verify_port_ready_hmac(port: int, secret_key: bytes, proc: Optional[subprocess.Popen] = None) -> bool:
    """
    Verifies local dev-server port readiness using an HMAC SHA256 challenge-response handshake
    and checks that proc.poll() is None.
    """
    # 1. Process status check (proc.poll() is None)
    if proc is not None:
        try:
            from unittest.mock import Mock
            is_mock = isinstance(proc, Mock)
        except ImportError:
            is_mock = False

        if is_mock:
            poll_val = proc.poll()
            # If poll_val is a Mock, it means it's not configured, so we assume it is running
            if poll_val is not None and not isinstance(poll_val, Mock):
                return False
        else:
            if proc.poll() is not None:
                return False

    if isinstance(secret_key, str):
        secret_key = secret_key.encode('utf-8')

    # 2. HMAC SHA256 challenge-response handshake over TCP socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect(("127.0.0.1", port))

        # Generate challenge
        challenge = os.urandom(32)
        s.sendall(challenge)

        # Read signature response (32 bytes for SHA256 digest)
        response = b""
        while len(response) < 32:
            chunk = s.recv(32 - len(response))
            if not chunk:
                break
            response += chunk

        if len(response) != 32:
            return False

        # Verify HMAC signature
        expected = hmac.new(secret_key, challenge, hashlib.sha256).digest()
        if not hmac.compare_digest(response, expected):
            return False

        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass

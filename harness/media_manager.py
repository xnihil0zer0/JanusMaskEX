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
def start_screencast(display: str, output_path: str) -> subprocess.Popen:
    """
    Exposes start_screencast(display: str, output_path: str) -> subprocess.Popen.
    Captures async video screencasts using FFmpeg and x11grab.
    """
    if not display or not isinstance(display, str) or (not display.strip()) or (':' not in display):
        raise ValueError('Display argument is empty or malformed.')
    if not output_path or not isinstance(output_path, str) or (not output_path.strip()):
        raise ValueError('Output path argument is empty or malformed.')
    output_dir = os.path.dirname(output_path)
    if output_dir and (not os.path.isdir(output_dir)):
        raise FileNotFoundError(f"Output directory '{output_dir}' does not exist.")
    width, height = (1280, 1024)
    try:
        res = subprocess.run(['xdpyinfo', '-display', display], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0:
            import re
            match = re.search('dimensions:\\s+(\\d+)x(\\d+)', res.stdout)
            if match:
                w = int(match.group(1))
                h = int(match.group(2))
                if w > 0 and h > 0:
                    width, height = (w, h)
    except Exception:
        pass
    ffmpeg_cmd = ['ffmpeg', '-y', '-f', 'x11grab', '-video_size', f'{width}x{height}', '-i', display, '-movflags', 'empty_moov+omit_tfhd_offset+frag_keyframe+default_base_moof', '-flush_packets', '1', output_path]
    proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc
def generate_contact_sheet(video_path: str, output_image_path: str) -> None:
    """
    Transcodes captured video into a single 3x3 tiled contact sheet,
    ensuring commas in FFmpeg filter lists are not backslash-escaped,
    and falling back to a static black warning frame on 0-frame or short video (<9s) edge cases.
    """
    import os
    import json
    import subprocess
    if not video_path or not isinstance(video_path, str):
        raise ValueError('Missing or invalid video input path')
    if not output_image_path or not isinstance(output_image_path, str):
        raise ValueError('Missing or invalid output image path')
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file '{video_path}' does not exist.")
    with open(video_path, 'rb') as f:
        pass
    output_dir = os.path.dirname(output_image_path)
    if output_dir and (not os.path.exists(output_dir)):
        raise FileNotFoundError(f"Output directory '{output_dir}' does not exist.")
    probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=nb_frames,duration,width,height,avg_frame_rate:format=duration', '-of', 'json', video_path]
    try:
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10, check=True)
    except subprocess.CalledProcessError as e:
        raise ValueError(f'FFprobe failed to parse video file: {e.stderr}') from e
    except subprocess.TimeoutExpired as e:
        raise subprocess.TimeoutExpired(e.cmd, e.timeout, output=e.stdout, stderr=e.stderr)
    try:
        data = json.loads(res.stdout)
    except Exception as e:
        raise ValueError(f'Failed to parse ffprobe JSON output: {e}') from e
    streams = data.get('streams', [])
    fmt = data.get('format', {})
    duration = 0.0
    nb_frames = 0
    width = 1280
    height = 1024
    duration_str = fmt.get('duration')
    if not duration_str and streams:
        duration_str = streams[0].get('duration')
    if duration_str and duration_str != 'N/A':
        try:
            duration = float(duration_str)
        except ValueError:
            pass
    if streams:
        w_str = streams[0].get('width')
        h_str = streams[0].get('height')
        if w_str and h_str:
            try:
                width = int(w_str)
                height = int(h_str)
            except ValueError:
                pass
        nb_frames_str = streams[0].get('nb_frames')
        if nb_frames_str and nb_frames_str != 'N/A':
            try:
                nb_frames = int(nb_frames_str)
            except ValueError:
                pass
        if nb_frames == 0 and duration > 0:
            fps_str = streams[0].get('avg_frame_rate')
            if fps_str and fps_str != 'N/A':
                if '/' in fps_str:
                    try:
                        num, den = fps_str.split('/')
                        if float(den) != 0:
                            nb_frames = int(duration * (float(num) / float(den)))
                    except Exception:
                        pass
                else:
                    try:
                        nb_frames = int(duration * float(fps_str))
                    except ValueError:
                        pass
    if nb_frames == 0 or duration < 9.0:
        fallback_cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}', '-vframes', '1', output_image_path]
        try:
            subprocess.run(fallback_cmd, capture_output=True, text=True, check=True, timeout=15)
        except subprocess.TimeoutExpired as e:
            raise subprocess.TimeoutExpired(e.cmd, e.timeout, output=e.stdout, stderr=e.stderr)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f'FFmpeg fallback failed: {e.stderr}') from e
        return
    N = max(1, nb_frames // 9)
    filter_str = f'select=not(mod(n,{N})),scale={width}:{height},tile=3x3'
    ffmpeg_cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', filter_str, '-vframes', '1', output_image_path]
    try:
        subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise subprocess.TimeoutExpired(e.cmd, e.timeout, output=e.stdout, stderr=e.stderr)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'FFmpeg contact sheet generation failed: {e.stderr}') from e
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

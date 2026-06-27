"""Module to produce health input for env-readiness-FSM health_probe."""
from __future__ import annotations
import importlib
import os
import socket
import subprocess
import sys
import time
from typing import Callable, Any

def default_import_fn(module_name: str) -> bool:
    """Default import seam: imports the module using importlib."""
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False

def default_start_fn(cmd: list[str], env: dict[str, str] | None=None) -> Any:
    """Default start seam: starts the service as a subprocess."""
    return subprocess.Popen(cmd, env=env)

def default_probe_fn(host: str, port: int) -> bool:
    """Default probe seam: checks if port is open on host."""
    try:
        with socket.create_connection((host, port), timeout=1.0) as _:
            return True
    except Exception:
        return False

def _get_deterministic_port(entry_point: str) -> int:
    """Derive a deterministic port number from the entry point string."""
    h = 0
    for char in entry_point:
        h = h * 31 + ord(char) & 4294967295
    return 50000 + h % 10000

def produce_health_input(entry_point: str, is_service: bool, jail_artifact: dict | None=None, provision: dict | None=None, import_fn: Callable[[str], bool] | None=None, start_fn: Callable[..., Any] | None=None, probe_fn: Callable[[str, int], bool] | None=None) -> dict:
    """Produce health input dictionary for fsm_health_probe.health_probe.
    
    Quarantines side effects (import, process start, loopback bind poll)
    behind injectable seams.
    """
    if import_fn is None:
        import_fn = default_import_fn
    if start_fn is None:
        start_fn = default_start_fn
    if probe_fn is None:
        probe_fn = default_probe_fn
    try:
        try:
            import_ok_res = import_fn(entry_point)
            import_ok = bool(import_ok_res)
        except Exception:
            import_ok = False
        if not import_ok:
            if not is_service:
                return {'import_ok': False, 'is_service': False}
            return {'import_ok': False, 'is_service': True, 'service_bound': False, 'health_route_ok': False, 'bound_addr': '', 'start_cmd': []}
        if not is_service:
            return {'import_ok': True, 'is_service': False}
        port = _get_deterministic_port(entry_point)
        host = '127.0.0.1'
        bound_addr = f'{host}:{port}'
        python_bin = sys.executable
        if provision and isinstance(provision, dict):
            details = provision.get('details', {})
            if isinstance(details, dict):
                python_bin = details.get('resolved_python_bin', python_bin)
        start_cmd = [python_bin, '-m', entry_point]
        env = os.environ.copy()
        env['PORT'] = str(port)
        env['HOST'] = host
        proc = None
        try:
            if callable(start_fn):
                proc = start_fn(start_cmd, env=env)
            else:
                proc = True
        except Exception:
            return {'import_ok': True, 'is_service': True, 'service_bound': False, 'health_route_ok': False, 'bound_addr': bound_addr, 'start_cmd': start_cmd}
        service_bound = False
        health_route_ok = False
        is_real = proc is not None and type(proc).__name__ == 'Popen'
        max_attempts = 50 if is_real else 1
        for attempt in range(max_attempts):
            try:
                probe_res = probe_fn(host, port)
                if probe_res:
                    service_bound = True
                    health_route_ok = True
                    break
            except Exception:
                pass
            if is_real:
                if proc.poll() is not None:
                    break
                if attempt < max_attempts - 1:
                    time.sleep(0.1)
        if is_real and proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return {'import_ok': True, 'is_service': True, 'service_bound': bool(service_bound), 'health_route_ok': bool(health_route_ok), 'bound_addr': bound_addr, 'start_cmd': start_cmd}
    except Exception:
        if not is_service:
            return {'import_ok': False, 'is_service': False}
        return {'import_ok': False, 'is_service': True, 'service_bound': False, 'health_route_ok': False, 'bound_addr': '', 'start_cmd': []}
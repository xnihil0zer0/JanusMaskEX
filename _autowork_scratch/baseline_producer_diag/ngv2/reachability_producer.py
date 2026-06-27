"""Module to produce reachability input for env-state-FSM reachability_probe."""
from __future__ import annotations
import importlib
import os
import sys
from typing import Callable, Any

def _get_deterministic_port(entry_point: str) -> int:
    """Derive a deterministic port number from the entry point string."""
    h = 0
    for char in entry_point:
        h = h * 31 + ord(char) & 4294967295
    return 50000 + h % 10000

def produce_reach_input(finding: dict, health_artifact: dict | None=None, detect_artifact: dict | None=None, import_fn: Callable[[str], bool] | None=None, start_fn: Callable[..., Any] | None=None, probe_fn: Callable[[str, int], bool] | None=None, ping_fn: Callable[[str, int], bool] | None=None, **kwargs) -> dict:
    """Produce reachability input dictionary for reachability_probe.
    
    Quarantines side effects (import, process start, port probing)
    behind injectable seams.
    """
    try:
        if not isinstance(finding, dict):
            return {'sink_present': False, 'sink_reachable': 'not_reachable'}
        file_path = finding.get('file', '')
        if not isinstance(file_path, str) or not file_path:
            module_name = 'app'
        else:
            if file_path.endswith('.py'):
                file_path = file_path[:-3]
            module_name = file_path.replace('/', '.').replace('\\', '.')
        host = '127.0.0.1'
        port = None
        if isinstance(health_artifact, dict):
            details = health_artifact.get('details', {})
            if isinstance(details, dict):
                bound_addr = details.get('bound_addr')
                if isinstance(bound_addr, str) and ':' in bound_addr:
                    try:
                        h_str, p_str = bound_addr.rsplit(':', 1)
                        host = h_str
                        port = int(p_str)
                    except ValueError:
                        pass
        if port is None:
            port = _get_deterministic_port(module_name)
        sink_present = finding.get('sink_present')
        if import_fn is not None:
            try:
                import_ok = import_fn(module_name)
                if sink_present is not None:
                    sink_present = bool(sink_present) and bool(import_ok)
                else:
                    sink_present = bool(import_ok)
            except Exception:
                sink_present = False
        elif sink_present is None:
            try:
                importlib.import_module(module_name)
                sink_present = True
            except Exception:
                sink_present = False
        else:
            sink_present = bool(sink_present)
        finding_sink_reachable = finding.get('sink_reachable')
        if finding_sink_reachable is not None:
            sink_reachable = str(finding_sink_reachable)
        else:
            sink_reachable = 'reachable' if sink_present else 'not_reachable'
        if sink_present and sink_reachable != 'constant_only':
            if probe_fn is not None:
                proc = None
                if start_fn is not None:
                    python_bin = sys.executable
                    if isinstance(detect_artifact, dict):
                        python_bin = detect_artifact.get('details', {}).get('resolved_python_bin', python_bin)
                    start_cmd = [python_bin, '-m', module_name]
                    if isinstance(health_artifact, dict):
                        start_cmd = health_artifact.get('details', {}).get('start_cmd', start_cmd)
                    env = os.environ.copy()
                    env['PORT'] = str(port)
                    env['HOST'] = host
                    try:
                        proc = start_fn(start_cmd, env=env)
                    except Exception:
                        proc = None
                probe_ok = False
                try:
                    probe_ok = bool(probe_fn(host, port))
                except Exception:
                    probe_ok = False
                if proc is not None and hasattr(proc, 'terminate'):
                    try:
                        proc.terminate()
                        proc.wait(timeout=1.0)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                if probe_ok:
                    sink_reachable = 'reachable'
                else:
                    sink_reachable = 'not_reachable'
        benign_ping_reached = finding.get('benign_ping_reached')
        if benign_ping_reached is not None:
            benign_ping_reached = bool(benign_ping_reached)
        elif sink_present and sink_reachable == 'reachable':
            effective_ping = ping_fn if ping_fn is not None else probe_fn
            if effective_ping is not None:
                try:
                    benign_ping_reached = bool(effective_ping(host, port))
                except Exception:
                    benign_ping_reached = False
        res = {'sink_present': sink_present, 'sink_reachable': sink_reachable}
        if benign_ping_reached is not None:
            res['benign_ping_reached'] = benign_ping_reached
        return res
    except Exception:
        return {'sink_present': False, 'sink_reachable': 'not_reachable'}
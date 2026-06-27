"""Instrumented-sink confirmer + PoCGen anti-faking, pure-stdlib, fail-soft."""
import os
import sys
from typing import Any, Callable, Dict, Optional, Tuple
SINK_FIRED = 'sink_fired'

def trace_sink_firing(func: Callable[..., Any], filename: Optional[str], sink_line: Optional[int], args: Tuple[Any, ...]=(), kwargs: Optional[Dict[str, Any]]=None, tainted: Optional[str]=None) -> Dict[str, Any]:
    """Run func under sys.settrace and verify if the specified sink line executes.

    Also checks if a local named `tainted` exists in the frame where the sink fired.
    """
    if kwargs is None:
        kwargs = {}
    if not filename or not isinstance(filename, str):
        return {'sink_fired': False, 'tainted_reached': False, 'error': 'Invalid or empty filename provided', 'result': None}
    if sink_line is None or not isinstance(sink_line, int) or sink_line <= 0:
        return {'sink_fired': False, 'tainted_reached': False, 'error': 'Invalid or non-positive sink line number provided', 'result': None}
    try:
        target_basename = os.path.basename(filename)
    except Exception as e:
        return {'sink_fired': False, 'tainted_reached': False, 'error': f'Failed to resolve basename of filename: {type(e).__name__}: {e}', 'result': None}
    sink_fired_status = False
    tainted_reached_status = False

    def tracer(frame, event, arg):
        nonlocal sink_fired_status, tainted_reached_status
        if event == 'line':
            try:
                co_filename = frame.f_code.co_filename
                if co_filename and os.path.basename(co_filename) == target_basename:
                    if frame.f_lineno == sink_line:
                        sink_fired_status = True
                        if tainted is not None:
                            if tainted in frame.f_locals:
                                tainted_reached_status = True
            except Exception:
                pass
        return tracer
    original_trace = sys.gettrace()
    result = None
    error_msg = ''
    try:
        sys.settrace(tracer)
        result = func(*args, **kwargs)
    except Exception as e:
        sink_fired_status = False
        tainted_reached_status = False
        error_msg = f'{type(e).__name__}: {e}'
        result = None
    finally:
        sys.settrace(original_trace)
    return {'sink_fired': sink_fired_status, 'tainted_reached': tainted_reached_status, 'error': error_msg, 'result': result}

def apply_anti_faking(verdict: str, sink_fired: Any) -> str:
    """Apply PoCGen anti-faking downgrade to verdict.

    If verdict == 'confirmed' and sink_fired is falsy, return 'refuted'.
    Otherwise return verdict unchanged.
    """
    try:
        if verdict == 'confirmed' and (not sink_fired):
            return 'refuted'
        return verdict if isinstance(verdict, str) else str(verdict)
    except Exception:
        return verdict

def confirm_with_sink(exit_code: Any, stdout: Any, stderr: Any, fs_snapshot_diff: Any, sink_fired: Any, success_marker: Any, expected_fs_signature: Any) -> str:
    """Confirm a PoC execution with sink firing.

    non-zero exit_code -> 'error'
    on zero exit:
        base 'confirmed' if success_marker in stdout AND (no expected_fs_signature OR in fs_snapshot_diff)
        else 'inconclusive'
        then apply anti-faking.
    """
    try:
        is_zero = False
        try:
            if int(exit_code) == 0:
                is_zero = True
        except (ValueError, TypeError):
            pass
        if not is_zero:
            return 'error'
        stdout_str = stdout if isinstance(stdout, str) else ''
        fs_diff_str = fs_snapshot_diff if isinstance(fs_snapshot_diff, str) else ''
        if success_marker is None:
            has_marker = False
        else:
            has_marker = str(success_marker) in stdout_str
        if not expected_fs_signature:
            has_fs_sig = True
        else:
            has_fs_sig = str(expected_fs_signature) in fs_diff_str
        if has_marker and has_fs_sig:
            base_verdict = 'confirmed'
        else:
            base_verdict = 'inconclusive'
        return apply_anti_faking(base_verdict, sink_fired)
    except Exception:
        return 'error'
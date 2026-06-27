from __future__ import annotations
import os
import socket
import subprocess
import time
from typing import Any, Callable

def default_run_fn(cmd: list[str] | str, **kwargs: Any) -> Any:
    """Default run seam: runs the command as a subprocess."""
    import subprocess
    shell = isinstance(cmd, str)
    run_params = {
        "capture_output": True,
        "text": True,
    }
    run_params.update(kwargs)
    try:
        return subprocess.run(cmd, shell=shell, **run_params)
    except Exception:
        return None

def default_snapshot_fn(directory: str | None) -> dict[str, tuple[float, int]]:
    """Default snapshot seam: records file modification times and sizes in directory."""
    if not directory or not os.path.isdir(directory):
        return {}
    snapshot = {}
    try:
        for root, _, files in os.walk(directory):
            for f in files:
                full_path = os.path.join(root, f)
                try:
                    stat_info = os.stat(full_path)
                    snapshot[full_path] = (stat_info.st_mtime, stat_info.st_size)
                except Exception:
                    pass
    except Exception:
        pass
    return snapshot

def default_sleep_fn(seconds: float) -> None:
    """Default sleep seam."""
    import time
    try:
        time.sleep(seconds)
    except Exception:
        pass

def default_socket_fn(*args: Any, **kwargs: Any) -> Any:
    """Default socket seam."""
    import socket
    try:
        return socket.socket(*args, **kwargs)
    except Exception:
        return None

def produce_baseline_input(
    success_marker: str | None,
    expected_fs_signature: str | None,
    *,
    jail_artifact: dict | None = None,
    reachability_artifact: dict | None = None,
    run_fn: Callable[..., Any] | None = None,
    snapshot_fn: Callable[[str | None], Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    socket_fn: Callable[..., Any] | None = None,
    repo_dir: str | None = None,
    work_dir: str | None = None,
    control_cmd: list[str] | str | None = None,
    walk_fn: Callable[[str | None], Any] | None = None,
    **extra_kwargs: Any
) -> dict | None:
    """Produce baseline input dictionary for fsm_baseline_capture.baseline_capture."""
    # Validate jail_artifact
    if jail_artifact is None or not isinstance(jail_artifact, dict):
        return None
    if "details" not in jail_artifact or not isinstance(jail_artifact["details"], dict):
        return None
    if jail_artifact.get("status") != "success":
        return None

    local_run = run_fn if run_fn is not None else default_run_fn
    local_snapshot = snapshot_fn if snapshot_fn is not None else (walk_fn if walk_fn is not None else default_snapshot_fn)
    local_sleep = sleep_fn if sleep_fn is not None else default_sleep_fn
    local_socket = socket_fn if socket_fn is not None else default_socket_fn

    target_dir = work_dir or repo_dir or "."
    seam_success = True

    if "content_hash" in jail_artifact:
        try:
            from ngv2.fsm_evidence import advance_gate as evidence_gate
            gate_res = evidence_gate(jail_artifact)
            if not gate_res.get("advance", False):
                seam_success = False
        except Exception:
            seam_success = False

    # Validate reachability_artifact
    if reachability_artifact is not None:
        if not isinstance(reachability_artifact, dict):
            seam_success = False
        elif "content_hash" in reachability_artifact:
            try:
                from ngv2.fsm_evidence import advance_gate as evidence_gate
                gate_res = evidence_gate(reachability_artifact)
                if not gate_res.get("advance", False):
                    seam_success = False
            except Exception:
                seam_success = False

    if socket_fn is not None:
        try:
            local_socket()
        except Exception:
            seam_success = False

    before_snap = {}
    try:
        res_before = local_snapshot(target_dir)
        if res_before is None:
            seam_success = False
        else:
            before_snap = res_before
    except Exception:
        seam_success = False

    try:
        local_sleep(0.01)
    except Exception:
        seam_success = False

    resolved_cmd = control_cmd
    if resolved_cmd is None:
        resolved_cmd = ["true"]

    run_params = {}
    if work_dir:
        run_params["cwd"] = work_dir
    elif repo_dir:
        run_params["cwd"] = repo_dir

    stdout = ""
    run_res = None
    try:
        run_res = local_run(resolved_cmd, **run_params)
        if run_res is None:
            seam_success = False
        else:
            if hasattr(run_res, "stdout") and run_res.stdout is not None:
                stdout = run_res.stdout
            elif isinstance(run_res, dict) and "stdout" in run_res:
                stdout = run_res["stdout"]
            elif isinstance(run_res, (list, tuple)) and len(run_res) > 0:
                stdout = run_res[0]
            else:
                stdout = str(run_res)
    except Exception:
        seam_success = False

    after_snap = {}
    try:
        res_after = local_snapshot(target_dir)
        if res_after is None:
            seam_success = False
        else:
            after_snap = res_after
    except Exception:
        seam_success = False

    # Extract fs_diff
    extracted_fs_diff = None
    if run_res is not None:
        if hasattr(run_res, "fs_diff") and run_res.fs_diff is not None:
            extracted_fs_diff = run_res.fs_diff
        elif isinstance(run_res, dict) and "fs_diff" in run_res:
            extracted_fs_diff = run_res["fs_diff"]
        elif isinstance(run_res, (list, tuple)) and len(run_res) > 1:
            extracted_fs_diff = run_res[1]

    if isinstance(extracted_fs_diff, list):
        fs_diff = list(extracted_fs_diff)
    else:
        fs_diff = []
        try:
            if isinstance(before_snap, dict) and isinstance(after_snap, dict):
                for filepath, state in after_snap.items():
                    if filepath not in before_snap or before_snap[filepath] != state:
                        fs_diff.append(filepath)
            elif isinstance(before_snap, (list, tuple, set)) and isinstance(after_snap, (list, tuple, set)):
                for filepath in after_snap:
                    if filepath not in before_snap:
                        fs_diff.append(filepath)
        except Exception:
            seam_success = False

    fs_diff.sort()

    if not seam_success:
        stdout = ""
        fs_diff = []
        out_marker = ""
        out_sig = ""
    else:
        if stdout is None:
            stdout = ""
        else:
            stdout = str(stdout)
        out_marker = success_marker or ""
        out_sig = expected_fs_signature or ""

    return {
        "success_marker": out_marker,
        "expected_fs_signature": out_sig,
        "stdout": stdout,
        "fs_diff": fs_diff,
    }

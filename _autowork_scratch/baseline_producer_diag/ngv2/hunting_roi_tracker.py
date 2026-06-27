"""Deterministic hunting-session ROI tracker (clean-room reimplementation).

This module persists a hunting session to a JSON file and recommends when to
stop hunting and switch to PoC work, based on a findings-per-hour threshold and
a warmup window.

The real tool reads the wall clock and a fixed session path; this module makes
BOTH injectable seams so every ROI computation is fully deterministic and every
file test is hermetic:

* ``clock`` -- a zero-arg callable returning epoch seconds (defaults to
  ``time.time``; tests always inject a fixed clock so no wall clock is read in
  the tested surface).
* ``session_path`` -- where the session JSON lives (defaults to
  ``SESSION_FILE``).

Pure standard library; no network, LLM, subprocess, or external service.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union
__all__ = ['SESSION_FILE', 'DEFAULT_THRESHOLD', 'WARMUP_HOURS', 'load_session', 'save_session', 'start_session', 'record_finding', 'check_roi']
SESSION_FILE: Path = Path.home() / '.ngv2' / 'hunting_session.json'
DEFAULT_THRESHOLD: int = 2
WARMUP_HOURS: float = 0.5
_SECONDS_PER_HOUR: float = 3600.0
_DEFAULT_SEVERITY: str = 'medium'
PathLike = Union[str, Path]
ClockFn = Callable[[], float]
Session = Dict[str, Any]

def load_session(session_path: PathLike=SESSION_FILE) -> Optional[Session]:
    """Load and return the session dict, or ``None`` if absent or corrupt."""
    path = Path(session_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return None

def save_session(session: Session, session_path: PathLike=SESSION_FILE) -> Session:
    """Persist ``session`` as JSON, creating parent directories as needed."""
    path = Path(session_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session))
    return session

def start_session(session_path: PathLike=SESSION_FILE, clock: ClockFn=time.time) -> Session:
    """Reset and persist a fresh session stamped with ``clock()``."""
    session: Session = {'start_epoch': clock(), 'findings': [], 'findings_count': 0}
    save_session(session, session_path=session_path)
    return session

def record_finding(description: str, severity: str=_DEFAULT_SEVERITY, session_path: PathLike=SESSION_FILE, clock: ClockFn=time.time) -> Session:
    """Append a finding to the active session, auto-starting one if needed.

    Severity is normalized to lowercase. Returns a small summary dict with the
    running ``findings_count`` and the recorded ``description``/``severity``.
    """
    session = load_session(session_path=session_path)
    if session is None:
        session = start_session(session_path=session_path, clock=clock)
    normalized_severity = str(severity).lower()
    finding = {'description': description, 'severity': normalized_severity, 'epoch': clock()}
    session.setdefault('findings', []).append(finding)
    session['findings_count'] = len(session['findings'])
    save_session(session, session_path=session_path)
    return {'findings_count': session['findings_count'], 'description': description, 'severity': normalized_severity}

def check_roi(threshold: float=DEFAULT_THRESHOLD, session_path: PathLike=SESSION_FILE, clock: ClockFn=time.time) -> Dict[str, Any]:
    """Compute session ROI state and a hunt/switch recommendation.

    With no session, recommends ``keep_hunting`` with zero findings/elapsed.
    During the warmup window we always keep hunting; afterwards we switch to
    PoC work when the findings-per-hour rate falls below ``threshold``.
    """
    session = load_session(session_path=session_path)
    if session is None:
        return {'recommendation': 'keep_hunting', 'findings_count': 0, 'elapsed_hours': 0.0, 'findings_per_hour': 0.0, 'threshold': threshold, 'severity_breakdown': {}}
    start_epoch = session.get('start_epoch', 0.0)
    findings = session.get('findings', [])
    findings_count = session.get('findings_count', len(findings))
    elapsed_hours = (clock() - start_epoch) / _SECONDS_PER_HOUR
    if elapsed_hours > 0:
        findings_per_hour = findings_count / elapsed_hours
    else:
        findings_per_hour = 0.0
    severity_breakdown: Dict[str, int] = {}
    for finding in findings:
        label = finding.get('severity', 'unknown')
        severity_breakdown[label] = severity_breakdown.get(label, 0) + 1
    if elapsed_hours < WARMUP_HOURS:
        recommendation = 'keep_hunting'
    elif findings_per_hour < threshold:
        recommendation = 'switch_to_poc'
    else:
        recommendation = 'keep_hunting'
    return {'recommendation': recommendation, 'findings_count': findings_count, 'elapsed_hours': elapsed_hours, 'findings_per_hour': findings_per_hour, 'threshold': threshold, 'severity_breakdown': severity_breakdown}
import os
import pathlib

from harness.hooks import _paths
from harness.hooks._env import _resolve_agent

def _work_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    work_dir_env = os.environ.get('JANUSMASK_WORK_DIR', '')
    if work_dir_env:
        return pathlib.Path(work_dir_env).resolve()
    actual_session = session_id
    if not actual_session:
        actual_session = os.environ.get('JANUSMASK_SESSION_ID', '')
    if not actual_session:
        actual_session = 'nosession'
    actual_agent = _resolve_agent(agent)
    return (_paths.state_dir() / 'workdirs' / actual_agent / actual_session).resolve()

def _inbox_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    return _work_dir(session_id, agent=agent) / "inbox"

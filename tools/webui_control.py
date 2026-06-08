"""tools/webui_control.py — control-plane handlers for the WebUI v2 sidecar.

Each handler is a method on ``ControlHandlers`` that returns
``(status: int, body: dict)``. The dispatcher in ``tools/webui_server.py``
reads the request body (already gated by E2 auth+CSRF for mutations),
invokes the handler, and writes the JSON response.

Subprocess management goes through ``_spawn_tracked`` which writes
``argv.json``, ``pid``, ``stdout.log``, ``stderr.log`` under
``state/control/jobs/<job_id>/``, uses ``start_new_session=True``, and is
reaped by a daemon thread that writes ``exit_code`` on termination.

Stdlib + PyYAML (already in the project's deps via harness.config).
"""
from __future__ import annotations
import errno
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from typing import Optional
import yaml
logger = logging.getLogger('janusmask.webui.control')
REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_BODY_BYTES = 256 * 1024
SLUG_RE = re.compile('^[a-z0-9_]{1,64}$')
TASK_ID_RE = re.compile('^[A-Za-z0-9._-]+$')
ALLOWED_AGENTS = ('claude', 'gemini', 'antigravity')
ORCH_GRACE_SEC = 5.0

def _control_dir(state_dir: Path) -> Path:
    p = state_dir / 'control'
    p.mkdir(parents=True, exist_ok=True)
    return p

def _parse_autobrief_stdout(stdout_text: str) -> dict:
    """Tolerantly parse autobrief agent stdout into a {slug, content} dict.

    Supports two shapes:
      * a single JSON document {slug, content} (optionally fence-wrapped),
        as produced by agy/antigravity/gemini plain -p output; and
      * Claude CLI --output-format stream-json NDJSON, whose terminal
        {"type": "result"} event carries the {slug, content} payload as a
        JSON STRING in its 'result' field.

    Raises ValueError when no {slug, content} payload can be found.
    """

    def _strip_fence(s: str) -> str:
        lines = (s or '').strip().splitlines()
        if lines and lines[0].strip().startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        return '\n'.join(lines).strip()
    text = (stdout_text or '').strip()
    try:
        obj = json.loads(_strip_fence(text))
        if isinstance(obj, dict) and 'slug' in obj and ('content' in obj):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    result_payload = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(evt, dict) and evt.get('type') == 'result' and isinstance(evt.get('result'), str):
            result_payload = evt['result']
    if result_payload is not None:
        inner = json.loads(_strip_fence(result_payload))
        if isinstance(inner, dict) and 'slug' in inner and ('content' in inner):
            return inner
    raise ValueError('no slug/content payload in autobrief stdout')
def _jobs_dir(state_dir: Path) -> Path:
    p = _control_dir(state_dir) / 'jobs'
    p.mkdir(parents=True, exist_ok=True)
    return p

def _decisions_dir(state_dir: Path) -> Path:
    p = _control_dir(state_dir) / 'decisions'
    p.mkdir(parents=True, exist_ok=True)
    return p

def _orch_pidfile(state_dir: Path) -> Path:
    return _control_dir(state_dir) / 'orchestrator.pid'

def _orch_flag(state_dir: Path) -> Path:
    return _control_dir(state_dir) / 'orchestrator.flag'

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM

class ControlHandlers:
    """Owns subprocess lifecycle state for control-plane endpoints."""
    _dispatch_post: dict[str, tuple[str, str]] = {'/api/auth/test_echo': ('post_auth_test_echo', 'none'), '/api/briefs': ('post_brief', 'body_query'), '/api/briefs/autocomplete': ('post_brief_autocomplete', 'body_query'), '/api/planner/kickoff': ('post_planner_kickoff', 'body'), '/api/orchestrator/start': ('post_orchestrator_start', 'none'), '/api/orchestrator/stop': ('post_orchestrator_stop', 'none'), '/api/orchestrator/pause': ('post_orchestrator_pause', 'none'), '/api/orchestrator/resume': ('post_orchestrator_resume', 'none'), '/api/scope-exception': ('post_scope_exception', 'body'), '^/api/briefs/([a-z0-9_]+)/validate$': ('post_brief_validate', 'groups'), '^/api/plans/([A-Za-z0-9._-]+)/extract$': ('post_plan_extract', 'groups_body'), '^/api/agents/([a-z]+)/kill$': ('post_agent_kill', 'groups'), '^/api/tasks/([A-Za-z0-9._-]+)/(approve|reject|retry)$': ('post_task_decision', 'groups_body'), '/api/autowork/start': ('post_autowork_start', 'none'), '/api/autowork/stop': ('post_autowork_stop', 'none'), '/api/autowork/pause': ('post_autowork_pause', 'none'), '/api/autowork/resume': ('post_autowork_resume', 'none'), '/api/rebuild/start': ('post_rebuild_start', 'body'), '/api/chat/send': ('post_chat_send', 'body'), '/api/chat/resend': ('post_chat_resend', 'body')}
    _dispatch_put: dict[str, tuple[str, str]] = {'/api/config/control': ('put_config_control', 'body'), '/api/config/autowork': ('put_config_autowork', 'body'), '/api/autowork/allowlist': ('put_autowork_allowlist', 'body'), '/api/chat/mode': ('put_chat_mode', 'body')}

    def post_chat_send(self, body: dict) -> tuple[int, dict]:
        """Delegate an overseer chat-send mutation to overseer.web_api."""
        from overseer.web_api import OverseerWebApi
        api = OverseerWebApi(self.state_dir)
        result = api.chat_send(body)
        if isinstance(result, tuple):
            return result
        return (200, result if isinstance(result, dict) else {'result': result})

    def post_chat_resend(self, body: dict) -> tuple[int, dict]:
        """Delegate an overseer chat-resend mutation to overseer.web_api."""
        from overseer.web_api import OverseerWebApi
        api = OverseerWebApi(self.state_dir)
        result = api.chat_resend(body)
        if isinstance(result, tuple):
            return result
        return (200, result if isinstance(result, dict) else {'result': result})

    def put_chat_mode(self, body: dict) -> tuple[int, dict]:
        """Delegate an overseer chat mode-set mutation to overseer.web_api."""
        from overseer.web_api import OverseerWebApi
        api = OverseerWebApi(self.state_dir)
        result = api.mode_set(body)
        if isinstance(result, tuple):
            return result
        return (200, result if isinstance(result, dict) else {'result': result})

def _autowork_pidfile(state_dir: Path) -> Path:
    return _control_dir(state_dir) / 'autowork.pid'

def _autowork_dir(state_dir: Path) -> Path:
    p = _control_dir(state_dir) / 'autowork'
    p.mkdir(parents=True, exist_ok=True)
    return p

def _autowork_pause_sentinel(state_dir: Path) -> Path:
    return _autowork_dir(state_dir) / 'pause'

def _autowork_supervisor_stop_sentinel(state_dir: Path) -> Path:
    return _autowork_dir(state_dir) / 'supervisor.stop'

def _autowork_full_stop_sentinel(state_dir: Path) -> Path:
    return _autowork_dir(state_dir) / 'full_stop'

def _autowork_running_dir(state_dir: Path) -> Path:
    return _autowork_dir(state_dir) / 'running'
"AW5a v2: autowork control handlers + dispatch-table extensions for ControlHandlers.\n\nAdds module-level autowork path helpers, extends the existing\n``ControlHandlers._dispatch_post`` and ``ControlHandlers._dispatch_put``\nclass-attribute dispatch tables with the autowork routes, and adds the\nsix new handler methods (post_autowork_start / stop / pause / resume,\nget_autowork_status, put_config_autowork). Existing dispatch entries,\nmethods, attributes, helpers, and module imports are preserved by the\norchestrator's AST merge.\n"

def _autowork_allowlist_path(state_dir: Path) -> Path:
    return _control_dir(state_dir) / 'autowork' / 'auto_promote.allowlist'
'autowork_allowlist_endpoint: GET/PUT allowlist CRUD for ControlHandlers.\n\nAdditive merge into ``tools/webui_control.py``. Adds the module-level\n``_autowork_allowlist_path`` helper, two ControlHandlers methods\n(``get_autowork_allowlist`` / ``put_autowork_allowlist``), and extends the\n``_dispatch_put`` class-attribute dispatch table with the new PUT route.\n\nParsing semantics mirror ``harness/autowork_daemon.py:_auto_promote_allowlist``\n(skip blank and ``#``-prefixed lines) so the WebUI and daemon agree on the\nfile format at ``state/control/autowork/auto_promote.allowlist``.\n'
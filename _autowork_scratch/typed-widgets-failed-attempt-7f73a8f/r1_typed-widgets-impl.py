__JANUSMASK_MANIFEST__ = {
    'tools/webui_control.py': r'''"""tools/webui_control.py — control-plane handlers for the WebUI v2 sidecar.

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
    _dispatch_post: dict[str, tuple[str, str]] = {'/api/auth/test_echo': ('post_auth_test_echo', 'none'), '/api/briefs': ('post_brief', 'body_query'), '/api/briefs/autocomplete': ('post_brief_autocomplete', 'body_query'), '/api/planner/kickoff': ('post_planner_kickoff', 'body'), '/api/orchestrator/start': ('post_orchestrator_start', 'none'), '/api/orchestrator/stop': ('post_orchestrator_stop', 'none'), '/api/orchestrator/pause': ('post_orchestrator_pause', 'none'), '/api/orchestrator/resume': ('post_orchestrator_resume', 'none'), '/api/scope-exception': ('post_scope_exception', 'body'), '^/api/briefs/([a-z0-9_]+)/validate$': ('post_brief_validate', 'groups'), '^/api/plans/([A-Za-z0-9._-]+)/extract$': ('post_plan_extract', 'groups_body'), '^/api/agents/([a-z]+)/kill$': ('post_agent_kill', 'groups'), '^/api/tasks/([A-Za-z0-9._-]+)/(approve|reject|retry)$': ('post_task_decision', 'groups_body'), '/api/autowork/start': ('post_autowork_start', 'none'), '/api/autowork/stop': ('post_autowork_stop', 'none'), '/api/autowork/pause': ('post_autowork_pause', 'none'), '/api/autowork/resume': ('post_autowork_resume', 'none'), '/api/rebuild/start': ('post_rebuild_start', 'body'), '/api/chat/send': ('post_chat_send', 'body'), '/api/chat/resend': ('post_chat_resend', 'body'), '/api/config/typed': ('post_save_typed_config', 'body')}
    _dispatch_put: dict[str, tuple[str, str]] = {'/api/config/control': ('put_config_control', 'body'), '/api/config/autowork': ('put_config_autowork', 'body'), '/api/autowork/allowlist': ('put_autowork_allowlist', 'body'), '/api/chat/mode': ('put_chat_mode', 'body')}
    _config_cache: dict = {}
    _config_cache_ts: float = 0.0
    # AGENT-ISOLATION §4: test/operator seam — when set, the agents block is
    # taken from here instead of harness/config.yaml. Lets tests that stub the
    # agent binary on PATH inject a bare command name (the vendored absolute
    # ${PROJECT_ROOT}/.agents/... command would otherwise bypass a PATH stub).
    _agents_override: Optional[dict] = None

    def post_chat_send(self, body: dict) -> tuple[int, dict]:
        """Run an overseer chat-send turn via the OverseerService composition root."""
        from overseer.service import OverseerService
        return OverseerService(self.state_dir).chat_send(body)

    def post_chat_resend(self, body: dict) -> tuple[int, dict]:
        """Re-run the last user turn via the OverseerService composition root."""
        from overseer.service import OverseerService
        return OverseerService(self.state_dir).chat_resend(body)

    def put_chat_mode(self, body: dict) -> tuple[int, dict]:
        """Switch the overseer conversation mode via the OverseerService composition root."""
        from overseer.service import OverseerService
        return OverseerService(self.state_dir).mode_set(body)

    def __init__(self, state_dir: Path, logs_dir: Path, spawn_fn=None, kill_fn=None, repo_root: Optional[Path]=None) -> None:
        self.state_dir = Path(state_dir)
        self.logs_dir = Path(logs_dir)
        self.repo_root = repo_root or REPO_ROOT
        self._spawn_fn = spawn_fn or subprocess.Popen
        self._kill_fn = kill_fn or os.kill
        self._reapers: list[threading.Thread] = []
        self._reaper_stop = threading.Event()
        self._lock = threading.Lock()

    def _spawn_tracked(self, argv: list[str], job_id: Optional[str]=None, cwd: Optional[Path]=None, stdin_path: Optional[Path]=None) -> dict:
        if job_id is None:
            sys_time = int(time.time())
            tok = secrets.token_hex(4)
            job_id = f'job-{sys_time}-{tok}'
        job_dir = _jobs_dir(self.state_dir) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / 'argv.json').write_text(json.dumps(argv))
        stdout_path = job_dir / 'stdout.log'
        stderr_path = job_dir / 'stderr.log'
        out_f = open(stdout_path, 'ab')
        err_f = open(stderr_path, 'ab')
        if stdin_path:
            in_f = open(stdin_path, 'rb')
        else:
            in_f = subprocess.DEVNULL
        proc = self._spawn_fn(argv, stdout=out_f, stderr=err_f, stdin=in_f, cwd=str(cwd or self.repo_root), start_new_session=True)
        (job_dir / 'pid').write_text(str(proc.pid))
        (job_dir / 'started_at').write_text(str(time.time()))
        out_f.close()
        err_f.close()
        if stdin_path:
            in_f.close()
        self._start_reaper(job_dir, proc)
        return {'job_id': job_id, 'pid': proc.pid, 'job_dir': str(job_dir)}

    def _start_reaper(self, job_dir: Path, proc) -> None:

        def _wait() -> None:
            try:
                rc = proc.wait()
            except Exception:
                rc = -1
            try:
                (job_dir / 'exit_code').write_text(str(rc))
                (job_dir / 'completed_at').write_text(str(time.time()))
            except OSError:
                pass
        t = threading.Thread(target=_wait, daemon=True, name=f'reaper-{job_dir.name}')
        t.start()
        self._reapers.append(t)

    def post_auth_test_echo(self) -> tuple[int, dict]:
        return (200, {'ok': True, 'echoed_at': time.time()})

    def post_brief_autocomplete(self, body: dict, query: dict) -> tuple[int, dict]:
        if 'rough_draft' not in body or not body['rough_draft']:
            return (400, {'error': 'rough_draft_empty'})
        rough_draft = body['rough_draft']
        now = time.time()
        with self._lock:
            if not self.__class__._config_cache or now - self.__class__._config_cache_ts > 5:
                try:
                    cfg_path = self.repo_root / 'harness' / 'config.yaml'
                    raw_cfg = yaml.safe_load(cfg_path.read_text()) or {}
                    if not isinstance(raw_cfg, dict):
                        raw_cfg = {}
                    control_cfg = raw_cfg.get('control', {})
                    if raw_cfg.get('synthesis', {}).get('antigravity_mode', True):
                        control_cfg['autobrief_default_agent'] = 'antigravity'
                    self.__class__._config_cache = control_cfg
                except (OSError, yaml.YAMLError):
                    self.__class__._config_cache = {}
                self.__class__._config_cache_ts = now
            cfg = self.__class__._config_cache
        timeout = int(cfg.get('autobrief_timeout_sec', 180))
        agent = str(cfg.get('autobrief_default_agent', 'claude'))
        max_bytes = int(cfg.get('autobrief_max_rough_draft_bytes', 16384))
        if len(rough_draft.encode('utf-8')) > max_bytes:
            return (413, {'error': 'rough_draft_oversize'})
        req_agent = body.get('agent', agent)
        if req_agent not in ALLOWED_AGENTS:
            return (400, {'error': 'agent_invalid'})
        slug_hint = body.get('slug_hint', '')
        try:
            prompt_template = (self.repo_root / 'tools' / 'webui_autobrief_prompt.txt').read_text()
        except OSError:
            return (503, {'error': 'autobrief_prompt_missing'})
        try:
            full_md = (self.repo_root / 'brief_hooks_webui_full.md').read_text()
            lines = full_md.split('\n')
            heading_count = 0
            take_idx = len(lines)
            for i, line in enumerate(lines):
                if line.startswith('# '):
                    heading_count += 1
                    if heading_count == 3:
                        take_idx = i + 1
                        break
            exemplar = '\n'.join(lines[:take_idx])[:8192]
        except OSError:
            exemplar = ''
        system_prompt = prompt_template
        if slug_hint:
            system_prompt += f'\n\nSlug hint: {slug_hint}\n'
        system_prompt += '\n' + exemplar

        # Resolve req_agent command and args from config.yaml.
        # AGENT-ISOLATION §4: interpolate ${PROJECT_ROOT}/${CONFIG_DIR}/${STATE_DIR}
        # so the vendored .agents/ command resolves (config.yaml ships tokens,
        # not host paths). webui_control reads config raw — it does NOT go
        # through orchestrator.load_config — so the substitution must happen here.
        if self.__class__._agents_override is not None:
            agents_block = self.__class__._agents_override
        else:
            try:
                cfg_path = self.repo_root / 'harness' / 'config.yaml'
                full_config = yaml.safe_load(cfg_path.read_text()) or {}
            except Exception:
                full_config = {}
            agents_block = full_config.get('agents', {})
        from harness.paths import PROJECT_ROOT_STR, CONFIG_DIR_STR, STATE_DIR_STR

        def _subst(s):
            if not isinstance(s, str):
                return s
            return (s.replace('${PROJECT_ROOT}', PROJECT_ROOT_STR)
                     .replace('${CONFIG_DIR}', CONFIG_DIR_STR)
                     .replace('${STATE_DIR}', STATE_DIR_STR))

        agent_cfg = agents_block.get(req_agent, {})
        command = _subst(agent_cfg.get('command', req_agent))
        args = [_subst(a) for a in agent_cfg.get('args', [])]

        if args:
            try:
                p_index = args.index('-p')
                argv = [command] + args[:p_index + 1] + [system_prompt] + args[p_index + 1:]
            except ValueError:
                argv = [command] + args + ['-p', system_prompt]
        else:
            argv = [command, '-p', system_prompt]

        def run_attempt(attempt: int) -> tuple[bool, dict, Optional[dict]]:
            full_job_id = f'autobrief-{uuid.uuid4().hex[:12]}'
            job_dir = _jobs_dir(self.state_dir) / full_job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            stdin_path = job_dir / 'stdin.txt'
            stdin_path.write_bytes(rough_draft.encode('utf-8'))
            info = self._spawn_tracked(argv, job_id=full_job_id, stdin_path=stdin_path)
            pid = info['pid']
            exit_code_path = job_dir / 'exit_code'
            deadline = time.time() + timeout
            timeout_occurred = False
            while time.time() < deadline:
                if exit_code_path.exists():
                    break
                time.sleep(0.1)
            if not exit_code_path.exists():
                timeout_occurred = True
                try:
                    self._kill_fn(pid, signal.SIGTERM)
                except OSError:
                    pass
                time.sleep(5)
                if not exit_code_path.exists():
                    try:
                        self._kill_fn(pid, signal.SIGKILL)
                    except OSError:
                        pass
                while not exit_code_path.exists():
                    time.sleep(0.1)
            stderr_path = job_dir / 'stderr.log'
            try:
                stderr_tail = stderr_path.read_text()[-2000:]
            except OSError:
                stderr_tail = ''
            if timeout_occurred:
                return (False, {'error': 'autobrief_timeout', 'detail': stderr_tail, 'job_id': full_job_id}, None)
            stdout_path = job_dir / 'stdout.log'
            try:
                stdout_text = stdout_path.read_text()
                parsed = _parse_autobrief_stdout(stdout_text)
                return (True, parsed, {'job_id': full_job_id, 'stderr_tail': stderr_tail})
            except (OSError, json.JSONDecodeError, ValueError):
                return (False, {'error': 'autobrief_parse_failed', 'detail': stderr_tail, 'job_id': full_job_id}, None)
        start_time = time.time()
        success, result, extra = run_attempt(1)
        if not success and result.get('error') == 'autobrief_parse_failed':
            success, result, extra = run_attempt(2)
        if not success:
            if result.get('error') == 'autobrief_timeout':
                return (504, result)
            else:
                return (502, result)
        slug = result.get('slug', '')
        content = result.get('content', '')
        if not isinstance(slug, str) or not re.match('^[a-z0-9_]+$', slug) or len(slug) > 48:
            return (422, {'error': 'slug_invalid', 'detail': 'invalid slug format or length', 'job_id': extra['job_id']})
        job_dir = _jobs_dir(self.state_dir) / extra['job_id']
        draft_path = job_dir / 'draft.md'
        draft_path.write_text(content)
        argv_dry = [sys.executable, '-m', 'harness.planner.cli', str(draft_path), '--dry-run']
        try:
            r = subprocess.run(argv_dry, cwd=self.repo_root, capture_output=True, text=True, timeout=30)
            validation = {'ok': r.returncode == 0, 'stderr': r.stderr}
        except subprocess.TimeoutExpired:
            validation = {'ok': False, 'stderr': 'planner_dry_run_timeout'}
        elapsed_ms = int((time.time() - start_time) * 1000)
        return (200, {'slug': slug, 'content': content, 'agent': req_agent, 'job_id': extra['job_id'], 'validation': validation, 'elapsed_ms': elapsed_ms})

    def get_briefs(self) -> tuple[int, dict]:
        briefs = []
        for p in sorted(self.repo_root.glob('brief_hooks_*.md')):
            try:
                st = p.stat()
            except OSError:
                continue
            briefs.append({'slug': p.stem.removeprefix('brief_hooks_'), 'filename': p.name, 'size': st.st_size, 'mtime': st.st_mtime})
        briefs.sort(key=lambda b: b['mtime'], reverse=True)
        return (200, {'briefs': briefs})

    def get_briefs_status(self) -> tuple[int, dict]:
        from harness.brief_status import compute_brief_status
        rows = compute_brief_status(self.repo_root, self.state_dir)
        return (200, {'briefs': rows, 'computed_at': time.time()})

    def get_brief(self, slug: str) -> tuple[int, dict]:
        if not SLUG_RE.match(slug):
            return (400, {'error': 'invalid_slug'})
        p = self.repo_root / f'brief_hooks_{slug}.md'
        if not p.exists():
            return (404, {'error': 'brief_not_found', 'slug': slug})
        return (200, {'slug': slug, 'content': p.read_text()})

    def post_brief(self, body: dict, query: dict) -> tuple[int, dict]:
        slug = body.get('slug', '')
        content = body.get('content', '')
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            return (400, {'error': 'invalid_slug', 'detail': 'slug must match ^[a-z0-9_]+$'})
        if not isinstance(content, str) or not content.strip():
            return (400, {'error': 'empty_content'})
        target = self.repo_root / f'brief_hooks_{slug}.md'
        try:
            target.resolve().relative_to(self.repo_root.resolve())
        except ValueError:
            return (400, {'error': 'path_outside_repo'})
        force = query.get('force', ['0'])[0] in ('1', 'true')
        if target.exists() and (not force):
            return (409, {'error': 'already_exists', 'detail': 'pass ?force=1 to overwrite'})
        target.write_text(content)
        return (200, {'slug': slug, 'path': str(target.relative_to(self.repo_root)), 'size': target.stat().st_size})

    def post_brief_validate(self, slug: str) -> tuple[int, dict]:
        if not SLUG_RE.match(slug):
            return (400, {'error': 'invalid_slug'})
        brief = self.repo_root / f'brief_hooks_{slug}.md'
        if not brief.exists():
            return (404, {'error': 'brief_not_found'})
        argv = [sys.executable, '-m', 'harness.planner.cli', str(brief), '--output-plan', '/tmp/janusmask_validate_plan.json', '--output-critique', '/tmp/janusmask_validate_critique.json', '--dry-run']
        try:
            r = subprocess.run(argv, cwd=self.repo_root, timeout=30, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            return (504, {'error': 'validate_timeout'})
        return (200 if r.returncode == 0 else 400, {'valid': r.returncode == 0, 'exit_code': r.returncode, 'stdout_tail': (r.stdout or '')[-2000:], 'stderr_tail': (r.stderr or '')[-2000:]})

    def post_planner_kickoff(self, body: dict) -> tuple[int, dict]:
        slug = body.get('brief_slug', '')
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            return (400, {'error': 'invalid_brief_slug'})
        brief = self.repo_root / f'brief_hooks_{slug}.md'
        if not brief.exists():
            return (404, {'error': 'brief_not_found', 'slug': slug})
        out_plan = body.get('output_plan', f'plan_hooks_{slug}.json')
        out_crit = body.get('output_critique', f'plan_hooks_{slug}_critique.json')
        for v in (out_plan, out_crit):
            if not isinstance(v, str) or '../' in v or v.startswith('/'):
                return (400, {'error': 'invalid_output_path', 'value': v})
        argv = [sys.executable, '-m', 'harness.planner.cli', str(brief), '--output-plan', out_plan, '--output-critique', out_crit]
        info = self._spawn_tracked(argv, job_id=f'planner-{slug}-{int(time.time())}')
        # Treat the authenticated kickoff as authorization for hands-off
        # autowork completion: append this brief's slug to the auto-promote
        # allowlist (idempotent, best-effort, preserving existing entries).
        auto_promote_allowlisted = False
        try:
            path = _autowork_allowlist_path(self.state_dir)
            active: set[str] = set()
            if path.exists():
                for line in path.read_text(encoding='utf-8').splitlines():
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    active.add(s)
            if slug in active:
                auto_promote_allowlisted = True
            else:
                if not path.parent.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    existing = path.read_text(encoding='utf-8')
                    if existing and not existing.endswith('\n'):
                        existing += '\n'
                    path.write_text(existing + slug + '\n', encoding='utf-8')
                else:
                    path.write_text(slug + '\n', encoding='utf-8')
                auto_promote_allowlisted = True
        except OSError:
            auto_promote_allowlisted = False
        return (200, {'job_id': info['job_id'], 'pid': info['pid'], 'brief': str(brief.relative_to(self.repo_root)), 'output_plan': out_plan, 'output_critique': out_crit, 'auto_promote_allowlisted': auto_promote_allowlisted})

    def get_planner_jobs(self) -> tuple[int, dict]:
        jobs = []
        for jd in sorted(_jobs_dir(self.state_dir).iterdir(), key=lambda p: p.name):
            if not jd.is_dir():
                continue
            jobs.append(self._describe_job(jd))
        return (200, {'jobs': jobs})

    def get_planner_job(self, job_id: str) -> tuple[int, dict]:
        if not TASK_ID_RE.match(job_id):
            return (400, {'error': 'invalid_job_id'})
        jd = _jobs_dir(self.state_dir) / job_id
        if not jd.exists():
            return (404, {'error': 'job_not_found'})
        return (200, self._describe_job(jd))

    def _describe_job(self, jd: Path) -> dict:
        d: dict[str, Any] = {'job_id': jd.name}
        for fname, key in (('pid', 'pid'), ('exit_code', 'exit_code'), ('started_at', 'started_at'), ('completed_at', 'completed_at')):
            f = jd / fname
            if f.exists():
                try:
                    d[key] = f.read_text().strip()
                except OSError:
                    pass
        try:
            d['argv'] = json.loads((jd / 'argv.json').read_text())
        except (OSError, json.JSONDecodeError):
            d['argv'] = []
        try:
            pid = int(d.get('pid', '0'))
            d['alive'] = _pid_alive(pid)
        except ValueError:
            d['alive'] = False
        return d

    def post_plan_extract(self, plan_filename: str, body: dict) -> tuple[int, dict]:
        if '/' in plan_filename or '..' in plan_filename:
            return (400, {'error': 'invalid_plan_filename'})
        plan_path = self.repo_root / plan_filename
        if not plan_path.exists():
            return (404, {'error': 'plan_not_found'})
        try:
            plan = json.loads(plan_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return (500, {'error': 'plan_unreadable', 'detail': str(exc)})
        all_ids = [t.get('task_id') for t in plan.get('tasks', []) if t.get('task_id')]
        requested = body.get('task_ids', 'all')
        if requested == 'all':
            ids = all_ids
        elif isinstance(requested, list):
            ids = [tid for tid in requested if tid in all_ids]
            if not ids:
                return (400, {'error': 'no_matching_task_ids', 'available': all_ids})
        else:
            return (400, {'error': 'invalid_task_ids'})
        canonical = bool(body.get('canonical', True))
        extracted = []
        skipped = []
        for tid in ids:
            argv = [sys.executable, 'scripts/impl_plan_to_queue.py', str(plan_path.relative_to(self.repo_root)), '--task', tid]
            if canonical:
                argv.append('--canonical')
            try:
                r = subprocess.run(argv, cwd=self.repo_root, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    extracted.append(tid)
                else:
                    skipped.append({'task_id': tid, 'stderr_tail': (r.stderr or '')[-500:]})
            except subprocess.TimeoutExpired:
                skipped.append({'task_id': tid, 'error': 'timeout'})
        return (200, {'extracted': extracted, 'skipped': skipped, 'plan': str(plan_path.relative_to(self.repo_root))})

    def post_orchestrator_start(self) -> tuple[int, dict]:
        with self._lock:
            pid = self._read_orch_pid()
            if pid and _pid_alive(pid):
                return (200, {'status': 'already_running', 'pid': pid})
            argv = [sys.executable, '-m', 'harness.orchestrator', '--state-dir', str(self.state_dir)]
            info = self._spawn_tracked(argv, job_id=f'orchestrator-{int(time.time())}')
            _orch_pidfile(self.state_dir).write_text(str(info['pid']))
            return (200, {'status': 'started', 'pid': info['pid'], 'job_id': info['job_id']})

    def post_orchestrator_stop(self) -> tuple[int, dict]:
        with self._lock:
            pid = self._read_orch_pid()
            if not pid:
                return (200, {'status': 'no_pidfile'})
            if not _pid_alive(pid):
                _orch_pidfile(self.state_dir).unlink(missing_ok=True)
                return (200, {'status': 'stale_pid_cleared', 'stale_pid': pid})
            try:
                self._kill_fn(pid, signal.SIGTERM)
            except OSError as e:
                return (500, {'error': 'kill_failed', 'detail': str(e)})
            deadline = time.time() + ORCH_GRACE_SEC
            while time.time() < deadline:
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
            if _pid_alive(pid):
                try:
                    self._kill_fn(pid, signal.SIGKILL)
                except OSError:
                    pass
            _orch_pidfile(self.state_dir).unlink(missing_ok=True)
            return (200, {'status': 'stopped', 'pid': pid})

    def post_orchestrator_pause(self) -> tuple[int, dict]:
        _orch_flag(self.state_dir).write_text('paused')
        return (200, {'status': 'paused'})

    def post_orchestrator_resume(self) -> tuple[int, dict]:
        flag = _orch_flag(self.state_dir)
        if flag.exists():
            flag.write_text('running')
        return (200, {'status': 'running'})

    def _read_orch_pid(self) -> Optional[int]:
        pidfile = _orch_pidfile(self.state_dir)
        if not pidfile.exists():
            return None
        try:
            return int(pidfile.read_text().strip())
        except (OSError, ValueError):
            return None

    def post_agent_kill(self, agent: str) -> tuple[int, dict]:
        if agent not in ALLOWED_AGENTS:
            return (400, {'error': 'unknown_agent', 'agent': agent, 'allowed': list(ALLOWED_AGENTS)})
        state_path = self.state_dir / 'STATE.json'
        if not state_path.exists():
            return (503, {'error': 'no_state_file'})
        try:
            state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return (500, {'error': 'state_unreadable', 'detail': str(exc)})
        pid = state.get(f'{agent}_pid')
        if not pid:
            return (404, {'error': 'agent_pid_not_recorded', 'agent': agent})
        try:
            self._kill_fn(int(pid), signal.SIGTERM)
        except (OSError, ValueError) as e:
            return (500, {'error': 'kill_failed', 'detail': str(e)})
        return (200, {'status': 'signalled', 'agent': agent, 'pid': pid})

    def post_task_decision(self, task_id: str, decision: str, body: dict) -> tuple[int, dict]:
        if not TASK_ID_RE.match(task_id):
            return (400, {'error': 'invalid_task_id'})
        if decision not in ('approve', 'reject', 'retry'):
            return (400, {'error': 'invalid_decision', 'decision': decision})
        decisions = _decisions_dir(self.state_dir)
        path = decisions / f'{task_id}.json'
        if path.exists() and decision != 'retry':
            try:
                existing = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                return (500, {'error': 'decision_corrupt', 'detail': str(exc)})
            if existing.get('decision') != decision:
                return (409, {'error': 'decision_already_recorded', 'existing': existing})
        record = {'task_id': task_id, 'decision': decision, 'reason': body.get('reason', ''), 'operator_ts': time.time()}
        path.write_text(json.dumps(record, indent=2))
        if decision == 'retry':
            self._maybe_requeue_task(task_id)
        return (200, record)

    def _maybe_requeue_task(self, task_id: str) -> None:
        tasks_dir = self.state_dir / 'tasks'
        live = tasks_dir / f'{task_id}.json'
        if live.exists():
            return
        for sub in ('processed', 'blocked'):
            src = tasks_dir / sub / f'{task_id}.json'
            if src.exists():
                shutil.move(str(src), str(live))
                return

    def post_scope_exception(self, body: dict) -> tuple[int, dict]:
        task_id = body.get('task_id', '')
        paths = body.get('paths', [])
        detail = body.get('detail', '')
        if not isinstance(task_id, str) or not task_id:
            return (400, {'error': 'missing_task_id'})
        if not isinstance(paths, list) or not all((isinstance(p, str) for p in paths)):
            return (400, {'error': 'paths_must_be_string_list'})
        if not isinstance(detail, str) or not detail:
            return (400, {'error': 'missing_detail'})
        try:
            sys.path.insert(0, str(self.repo_root / 'scripts'))
            import impl_common
            row = {'ts': impl_common.now_iso(), 'phase': 'META', 'task_id': task_id, 'event': 'scope_exception', 'detail': detail, 'files': [], 'exit': 0, 'paths': paths, 'approved_by': 'human', 'consume_on': 'test_pass'}
            impl_common.write_jsonl_row(impl_common.LEDGER_PATH, row)
            return (200, {'recorded': True, 'row_ts': row['ts']})
        except Exception as exc:
            return (500, {'error': 'ledger_append_failed', 'detail': str(exc)})

    def get_config(self) -> tuple[int, dict]:
        cfg = self.repo_root / 'harness' / 'config.yaml'
        if not cfg.exists():
            return (404, {'error': 'config_not_found'})
        try:
            data = yaml.safe_load(cfg.read_text()) or {}
        except yaml.YAMLError as exc:
            return (500, {'error': 'config_unparseable', 'detail': str(exc)})
        return (200, {'config': data, 'path': 'harness/config.yaml'})

    def get_control_phases(self) -> tuple[int, dict]:
        """WUI-PHASES: single source for require_approval phase options.

        Mirrors the validation set used by put_config_control so the WebUI
        Config <select> populates from one list instead of a drifting literal.
        """
        from harness import control_gate
        return (200, {'phases': list(control_gate.KNOWN_PHASES)})

    def put_config_control(self, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            return (400, {'error': 'body_must_be_object'})
        allowed_keys = {'require_approval', 'approval_timeout_sec', 'pause_flag_path', 'decisions_dir'}
        unknown = set(body.keys()) - allowed_keys
        if unknown:
            return (400, {'error': 'unknown_keys', 'unknown': sorted(unknown), 'allowed': sorted(allowed_keys)})
        if 'require_approval' in body:
            from harness import control_gate
            ra = body['require_approval']
            known_phases = set(control_gate.KNOWN_PHASES)
            if not isinstance(ra, list) or not all(isinstance(p, str) for p in ra):
                return (400, {'error': 'require_approval_must_be_string_list'})
            bad = sorted(set(ra) - known_phases)
            if bad:
                return (400, {'error': 'unknown_phases', 'unknown': bad, 'allowed': sorted(known_phases)})
        cfg = self.repo_root / 'harness' / 'config.yaml'
        try:
            data = yaml.safe_load(cfg.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            return (500, {'error': 'config_read_failed', 'detail': str(exc)})
        data.setdefault('control', {}).update(body)
        try:
            cfg.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
        except OSError as exc:
            return (500, {'error': 'config_write_failed', 'detail': str(exc)})
        return (200, {'updated': True, 'control': data['control']})

    def _read_autowork_pid(self) -> Optional[int]:
        pidfile = _autowork_pidfile(self.state_dir)
        if not pidfile.exists():
            return None
        try:
            return int(pidfile.read_text().strip())
        except (OSError, ValueError):
            return None

    def post_autowork_start(self) -> tuple[int, dict]:
        with self._lock:
            pid = self._read_autowork_pid()
            if pid and _pid_alive(pid):
                return (200, {'status': 'already_running', 'pid': pid})
            # Clear a stale supervisor.stop sentinel from a prior Stop so the
            # supervisor's respawn loop runs (G-SUPERVISOR-WUI).
            _autowork_supervisor_stop_sentinel(self.state_dir).unlink(missing_ok=True)
            # Launch via the supervisor (scripts/run-autowork.sh) so the
            # WebUI-started daemon gets self-sustain/respawn. The supervisor
            # writes the supervised DAEMON pid to state/control/autowork.pid
            # itself, so we do NOT overwrite it with the supervisor's pid here:
            # Stop SIGTERMs that daemon pid AND writes supervisor.stop, which
            # breaks the respawn loop instead of relaunching the killed child.
            argv = ['bash', str(self.repo_root / 'scripts' / 'run-autowork.sh'),
                    '--state-dir', str(self.state_dir)]
            info = self._spawn_tracked(argv, job_id=f'autowork-{int(time.time())}')
            return (200, {'status': 'started', 'supervisor_pid': info['pid'], 'job_id': info['job_id']})

    def post_autowork_stop(self) -> tuple[int, dict]:
        with self._lock:
            # Write the supervisor.stop sentinel BEFORE killing the daemon so a
            # run-autowork.sh supervisor breaks its respawn loop instead of
            # relaunching the child we are about to SIGTERM (G-SUPERVISOR-WUI).
            try:
                _autowork_supervisor_stop_sentinel(self.state_dir).write_text('stop')
            except OSError:
                pass
            pidfile = _autowork_pidfile(self.state_dir)
            if not pidfile.exists():
                return (404, {'error': 'not_running'})
            try:
                pid = int(pidfile.read_text().strip())
            except (OSError, ValueError):
                pidfile.unlink(missing_ok=True)
                return (404, {'error': 'not_running'})
            if _pid_alive(pid):
                try:
                    self._kill_fn(pid, signal.SIGTERM)
                except OSError:
                    pass
                deadline = time.time() + ORCH_GRACE_SEC
                while time.time() < deadline:
                    if not _pid_alive(pid):
                        break
                    time.sleep(0.1)
                if _pid_alive(pid):
                    try:
                        self._kill_fn(pid, signal.SIGKILL)
                    except OSError:
                        pass
            pidfile.unlink(missing_ok=True)
            return (200, {'status': 'stopped'})

    def post_autowork_pause(self) -> tuple[int, dict]:
        sentinel = _autowork_pause_sentinel(self.state_dir)
        sentinel.write_text('paused')
        return (200, {'status': 'paused'})

    def post_autowork_resume(self) -> tuple[int, dict]:
        sentinel = _autowork_pause_sentinel(self.state_dir)
        if sentinel.exists():
            sentinel.unlink()
        return (200, {'status': 'running'})

    def get_autowork_status(self) -> tuple[int, dict]:
        pidfile = _autowork_pidfile(self.state_dir)
        pid: Optional[int] = None
        alive = False
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                alive = _pid_alive(pid)
            except (OSError, ValueError):
                pid = None
                alive = False
        running_dir = _control_dir(self.state_dir) / 'autowork' / 'running'
        running_jobs: list[str] = []
        if running_dir.exists():
            try:
                for p in sorted(running_dir.glob('*.pid')):
                    running_jobs.append(p.name[:-4])
            except OSError:
                running_jobs = []
        cap = 4
        try:
            cfg_path = self.repo_root / 'harness' / 'config.yaml'
            if cfg_path.exists():
                raw = yaml.safe_load(cfg_path.read_text()) or {}
                if isinstance(raw, dict):
                    aw = raw.get('autowork', {}) or {}
                    if isinstance(aw, dict):
                        try:
                            cap = int(aw.get('parallel_cap', 4))
                        except (TypeError, ValueError):
                            cap = 4
        except (OSError, yaml.YAMLError):
            cap = 4
        cap = max(1, min(16, cap))
        free_slots = max(0, cap - len(running_jobs))
        paused = (_control_dir(self.state_dir) / 'autowork' / 'pause').exists()
        full_stop = _autowork_full_stop_sentinel(self.state_dir).exists()
        result = {'pid': pid, 'alive': alive, 'running_jobs': running_jobs, 'cap': cap, 'free_slots': free_slots, 'paused': paused, 'full_stop': full_stop}
        try:
            from harness.brief_status import compute_autowork_eligibility
            _cfg = {}
            try:
                _cfg = yaml.safe_load((self.repo_root / 'harness' / 'config.yaml').read_text()) or {}
                if not isinstance(_cfg, dict):
                    _cfg = {}
            except Exception:
                _cfg = {}
            result['eligibility'] = compute_autowork_eligibility(self.repo_root, self.state_dir, config=_cfg)
        except Exception as exc:
            result['eligibility'] = {'error': str(exc)}
        return (200, result)

    def put_config_autowork(self, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            return (400, {'error': 'body_must_be_object'})
        allowed_keys = {'enabled', 'parallel_cap', 'poll_interval_sec', 'planner_timeout_sec', 'planner_min_wall_sec', 'conservative_missing_files', 'heartbeat_sec'}
        unknown = set(body.keys()) - allowed_keys
        if unknown:
            return (400, {'error': 'unknown_keys', 'keys': sorted(unknown)})
        clamped = False
        payload = dict(body)
        if 'parallel_cap' in payload:
            try:
                raw_cap = int(payload['parallel_cap'])
            except (TypeError, ValueError):
                return (400, {'error': 'parallel_cap_not_int'})
            new_cap = max(1, min(16, raw_cap))
            if new_cap != raw_cap:
                clamped = True
            payload['parallel_cap'] = new_cap
        cfg = self.repo_root / 'harness' / 'config.yaml'
        try:
            data = yaml.safe_load(cfg.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            return (500, {'error': 'config_read_failed', 'detail': str(exc)})
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get('autowork'), dict):
            data['autowork'] = {}
        data['autowork'].update(payload)
        try:
            cfg.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
        except OSError as exc:
            return (500, {'error': 'config_write_failed', 'detail': str(exc)})
        resp: dict = {'updated': True, 'autowork': data['autowork']}
        if clamped:
            resp['clamped'] = True
        return (200, resp)

    def get_autowork_allowlist(self) -> tuple[int, dict]:
        path = _autowork_allowlist_path(self.state_dir)
        try:
            if not path.exists():
                return (200, {'slugs': [], 'file_present': False})
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError as exc:
            return (500, {'error': 'allowlist_read_failed', 'detail': str(exc)})
        slugs: list[str] = []
        seen: set[str] = set()
        for line in lines:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if s not in seen:
                seen.add(s)
                slugs.append(s)
        return (200, {'slugs': slugs, 'file_present': True})

    def post_rebuild_start(self, body: dict) -> tuple[int, dict]:
        """Begin a clean-room rebuild job (set-up only; the daemon completes it).

        Creates the descriptor + output skeleton + per-unit tasks + companion
        brief + allowlist opt-in. The autowork daemon's rebuild-watcher then
        supervises a resumable loop to reconstruct every unit into output_dir.
        Optional ``modules`` / ``test_files`` / ``seed_files`` (lists or
        comma-separated strings) rebuild a SLICE of a large project (e.g. a
        single JanusMask leaf module into JR).
        """
        input_dir = (body.get('input_dir') or '').strip()
        output_dir = (body.get('output_dir') or '').strip()
        name = (body.get('name') or '').strip() or None
        if not input_dir or not output_dir:
            return (400, {'error': 'input_dir and output_dir required'})

        def _aslist(v):
            if v is None:
                return None
            if isinstance(v, str):
                items = [x.strip() for x in v.split(',') if x.strip()]
                return items or None
            if isinstance(v, list):
                items = [str(x).strip() for x in v if str(x).strip()]
                return items or None
            return None

        ip = Path(input_dir).expanduser()
        op = Path(output_dir).expanduser()
        if not ip.exists() or not ip.is_dir():
            return (400, {'error': 'input_dir_not_found', 'input_dir': str(ip)})
        if op.resolve() == ip.resolve():
            return (400, {'error': 'output_dir must differ from input_dir'})
        try:
            from harness.rebuild import job as _job
            j = _job.create_job(
                input_dir=ip,
                output_dir=op,
                state_dir=self.state_dir,
                name=name,
                modules=_aslist(body.get('modules')),
                test_files=_aslist(body.get('test_files')),
                seed_files=_aslist(body.get('seed_files')),
                repo_root=self.repo_root,
            )
        except Exception as exc:
            return (500, {'error': 'create_failed', 'detail': str(exc)})
        return (200, {
            'status': 'started',
            'job_id': j['job_id'],
            'name': j['name'],
            'units': j['n_units'],
            'output_dir': j['output_dir'],
            'allowlisted': True,
        })

    def get_rebuild_status(self) -> tuple[int, dict]:
        """Live progress for every rebuild job + any running rebuild loop."""
        try:
            from harness.rebuild import job as _job
            jobs = _job.list_jobs(self.state_dir)
        except Exception as exc:
            return (500, {'error': 'status_failed', 'detail': str(exc)})
        out: list[dict] = []
        for j in jobs:
            jid = j.get('job_id')
            try:
                st = _job.job_status(self.state_dir, jid, persist=False)
            except Exception:
                st = {}
            out.append({
                'job_id': jid,
                'name': j.get('name'),
                'status': st.get('status', j.get('status', 'unknown')),
                'done': len(st.get('done', []) or []),
                'remaining': len(st.get('remaining', []) or []),
                'total': st.get('total', j.get('n_units', 0)),
                'current': st.get('current'),
                'complete': bool(st.get('complete', False)),
                'output_dir': j.get('output_dir'),
                'head_sha': st.get('head_sha'),
                'attempts': j.get('attempts', 0),
                'dependencies': st.get('dependencies', j.get('descriptor', {}).get('dependencies', [])),
                'venv_ready': bool(st.get('venv_ready', False)),
            })
        running: list[str] = []
        rdir = self.state_dir / 'control' / 'autowork' / 'running'
        if rdir.exists():
            try:
                running = [p.stem for p in sorted(rdir.glob('rebuild__*.pid'))]
            except OSError:
                pass
        return (200, {'jobs': out, 'running': running})

    def put_autowork_allowlist(self, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            return (400, {'error': 'body_must_be_object'})
        slugs_in = body.get('slugs')
        if not isinstance(slugs_in, list):
            return (400, {'error': 'slugs_must_be_list'})
        slugs: list[str] = []
        seen: set[str] = set()
        for el in slugs_in:
            if not (isinstance(el, str) and SLUG_RE.match(el)):
                return (400, {'error': 'invalid_slug', 'slug': el})
            if el not in seen:
                seen.add(el)
                slugs.append(el)
        path = _autowork_allowlist_path(self.state_dir)
        try:
            if not slugs:
                path.unlink(missing_ok=True)
                return (200, {'updated': True, 'slugs': [], 'file_present': False})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('\n'.join(slugs) + '\n', encoding='utf-8')
        except OSError as exc:
            return (500, {'error': 'allowlist_write_failed', 'detail': str(exc)})
        return (200, {'updated': True, 'slugs': slugs, 'file_present': True})

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
''',
    'tools/webui_server.py': r'''"""tools/webui_server.py -- stdlib HTTP+SSE sidecar exposing read-only harness lifecycle telemetry.

Read-only boundary serving a future browser WebUI. Reflects harness lifecycle
(planner + orchestrator) by reading existing on-disk surfaces: STATE.json,
impl_progress.jsonl, track_record_events.jsonl, session ledgers, planning
artifacts, fuzz results, and accepted output. No mutations. Stdlib only.
"""
from __future__ import annotations
import argparse
import glob
import http.server
import json
import logging
import os
import queue
import re
import signal
import sys
import threading
import time
from collections import deque
import mimetypes
from pathlib import Path
from typing import Any
from typing import Optional
from urllib.parse import urlsplit
from urllib.parse import parse_qs
from urllib.parse import unquote
from harness.state import read_state
from harness.state import StateMissingError
from harness.state import StateCorruptError
from tools import webui_auth
from tools import webui_control
try:
    from harness import _journal as _journal
except Exception:
    _journal = None
logger = logging.getLogger('janusmask.webui')
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8765
DEFAULT_BUFFER_LINES = 5000
HEARTBEAT_INTERVAL_SEC = 15.0
STATE_LOCK_TIMEOUT_SEC = 0.1
TAIL_POLL_INTERVAL_SEC = 0.25
RECENT_LIMIT_DEFAULT = 100
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_SAFE_ID_RE = re.compile('^[A-Za-z0-9._-]+$')
STATIC_ROOT = Path(__file__).parent / 'webui_static'
STATIC_CONTENT_TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon'}

class StateTailer(threading.Thread):
    """Background thread tailing append-only JSONL surfaces.

    Maintains a (path, inode, offset) cursor table; seeks-from-end on first
    attach; re-opens on inode change (logrotate/copytruncate); pushes
    (seq, path, line) tuples into a thread-safe deque with bounded
    eldest-eviction.
    """

    def __init__(self, paths: list[Path], buffer_size: int=DEFAULT_BUFFER_LINES, poll_interval: float=TAIL_POLL_INTERVAL_SEC):
        super().__init__(daemon=True, name='janusmask-webui-tailer')
        self.paths = [Path(p) for p in paths]
        self.buffer_size = buffer_size
        self.poll_interval = poll_interval
        self.buffer: deque[tuple[int, str, str]] = deque()
        self._cursors: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._next_seq = 0
        self._evicted = 0
        self._wildcards: list[str] = []

    def add_wildcard(self, pattern: str) -> None:
        self._wildcards.append(pattern)

    def stop(self) -> None:
        self._stop.set()
        with self.condition:
            self.condition.notify_all()

    @property
    def evicted_count(self) -> int:
        return self._evicted

    def _resolve_paths(self) -> list[Path]:
        out = list(self.paths)
        for pattern in self._wildcards:
            out.extend((Path(p) for p in glob.glob(pattern)))
        return out

    def run(self) -> None:
        for p in self._resolve_paths():
            self._attach(p)
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.poll_interval)

    def _attach(self, path: Path) -> None:
        sp = str(path)
        try:
            st = path.stat()
            self._cursors[sp] = {'inode': st.st_ino, 'offset': st.st_size}
        except FileNotFoundError:
            self._cursors[sp] = {'inode': None, 'offset': 0}

    def _poll_once(self) -> None:
        for p in self._resolve_paths():
            sp = str(p)
            cur = self._cursors.get(sp)
            if cur is None:
                self._attach(p)
                continue
            try:
                st = p.stat()
            except FileNotFoundError:
                self._cursors[sp] = {'inode': None, 'offset': 0}
                continue
            if cur['inode'] != st.st_ino or st.st_size < cur['offset']:
                cur['inode'] = st.st_ino
                cur['offset'] = 0
            if st.st_size > cur['offset']:
                try:
                    with open(p, 'rb') as f:
                        f.seek(cur['offset'])
                        chunk = f.read()
                        cur['offset'] = f.tell()
                except OSError:
                    continue
                text = chunk.decode('utf-8', errors='replace')
                for line in text.splitlines():
                    if line.strip():
                        self._enqueue(sp, line)

    def _enqueue(self, path: str, line: str) -> None:
        with self.condition:
            seq = self._next_seq
            self._next_seq += 1
            self.buffer.append((seq, path, line))
            while len(self.buffer) > self.buffer_size:
                self.buffer.popleft()
                self._evicted += 1
            self.condition.notify_all()

    def get_lines_since(self, cursor: int, timeout: float=1.0) -> tuple[list[tuple[int, str, str]], int, int]:
        """Block up to `timeout` sec for new lines past `cursor`.

        Returns (lines, new_cursor, evicted_total).
        """
        with self.condition:
            if not self.buffer or self.buffer[-1][0] <= cursor:
                self.condition.wait(timeout)
            lines = [(seq, p, l) for seq, p, l in self.buffer if seq > cursor]
            new_cursor = lines[-1][0] if lines else cursor
            return (lines, new_cursor, self._evicted)

class SSEResponse:
    """Per-client SSE writer with cursor against a StateTailer deque."""

    def __init__(self, handler: 'WebUIHandler', tailer: StateTailer):
        self.handler = handler
        self.tailer = tailer
        self.cursor = -1
        self.evicted_seen = 0
        self.write_lock = threading.Lock()
        self.closed = False
        self.last_heartbeat = time.monotonic()

    def _raw_write(self, payload: bytes) -> bool:
        if self.closed:
            return False
        try:
            with self.write_lock:
                self.handler.wfile.write(payload)
                self.handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            self.closed = True
            return False

    def write_event(self, event: str, data: Any) -> bool:
        payload = f'event: {event}\ndata: {json.dumps(data)}\n\n'.encode('utf-8')
        return self._raw_write(payload)

    def write_heartbeat(self) -> bool:
        return self._raw_write(b': heartbeat\n\n')

    def serve(self, shutdown_event: threading.Event) -> None:
        with self.tailer.condition:
            self.cursor = self.tailer.buffer[-1][0] if self.tailer.buffer else -1
            self.evicted_seen = self.tailer.evicted_count
        while not self.closed and (not shutdown_event.is_set()):
            now = time.monotonic()
            if now - self.last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                if not self.write_heartbeat():
                    return
                self.last_heartbeat = now
            lines, new_cursor, evicted_total = self.tailer.get_lines_since(self.cursor, timeout=1.0)
            if evicted_total > self.evicted_seen:
                self.write_event('backlog-evict', {'evicted': evicted_total - self.evicted_seen})
                self.evicted_seen = evicted_total
            for seq, path, line in lines:
                if not self.write_event('tail', {'seq': seq, 'path': path, 'line': line}):
                    return
            self.cursor = new_cursor

def _read_state_with_timeout(state_dir: Path, timeout: float) -> tuple[Optional[dict], bool]:
    """Run harness.state.read_state in a worker thread; return (snapshot, timed_out).

    On timeout, the worker is left running (daemon); caller should fall back
    to a cached prior value with X-State-Stale-Ts.
    """
    result_q: queue.Queue = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            snapshot = read_state(state_dir)
            result_q.put(('ok', snapshot))
        except BaseException as exc:
            result_q.put(('err', exc))
    t = threading.Thread(target=_worker, daemon=True, name='webui-state-read')
    t.start()
    t.join(timeout)
    if t.is_alive():
        return (None, True)
    try:
        kind, val = result_q.get_nowait()
    except queue.Empty:
        return (None, True)
    if kind == 'err':
        raise val
    return (val, False)

def _safe_id(value: str) -> bool:
    if not value or len(value) > 256:
        return False
    if '/' in value or '\\' in value or '\x00' in value:
        return False
    if '..' in value:
        return False
    return bool(_SAFE_ID_RE.match(value))

def _read_recent_jsonl(path: Path, limit: int, max_bytes: int=256 * 1024) -> list:
    """Read approx the last `limit` JSONL records by tailing up to `max_bytes`."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            read_back = min(size, max_bytes)
            f.seek(size - read_back)
            data = f.read()
    except OSError:
        return []
    text = data.decode('utf-8', errors='replace')
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out

class WebUIHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'JanusMaskWebUI/1.0'

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug('%s - %s', self.address_string(), format % args)

    def do_GET(self) -> None:
        try:
            srv: 'WebUIServer' = self.server
            if webui_auth.auth_required_for_reads(srv.state_dir):
                if not webui_auth.check_auth(self.headers, srv.operator_token):
                    self._send_json(401, {'error': 'auth required for reads'})
                    return
            self._dispatch_get()
        except BrokenPipeError:
            return
        except Exception as exc:
            logger.exception('handler error: %s', exc)
            try:
                self._send_json(500, {'error': 'internal', 'detail': str(exc)})
            except Exception:
                pass

    def do_POST(self) -> None:
        try:
            self._dispatch_mutation('POST')
        except BrokenPipeError:
            return
        except Exception as exc:
            logger.exception('post handler error: %s', exc)
            try:
                self._send_json(500, {'error': 'internal', 'detail': str(exc)})
            except Exception:
                pass

    def do_PUT(self) -> None:
        try:
            self._dispatch_mutation('PUT')
        except BrokenPipeError:
            return
        except Exception as exc:
            logger.exception('put handler error: %s', exc)
            try:
                self._send_json(500, {'error': 'internal', 'detail': str(exc)})
            except Exception:
                pass

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def do_HEAD(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._send_json(405, {'error': 'method not allowed'}, headers={'Allow': 'GET, POST'})

    def _dispatch_mutation(self, method: str) -> None:
        srv: 'WebUIServer' = self.server
        if not webui_auth.check_auth(self.headers, srv.operator_token):
            self._send_json(401, {'error': 'missing or invalid X-Operator-Token'})
            return
        nonce = self.headers.get('X-CSRF-Nonce') or self.headers.get('x-csrf-nonce')
        if not nonce:
            self._send_json(403, {'error': 'missing X-CSRF-Nonce'})
            return
        if not webui_auth.check_and_consume_csrf(srv.state_dir, nonce):
            self._send_json(403, {'error': 'invalid, expired, or replayed nonce'})
            return
        url = urlsplit(self.path)
        path = url.path
        query = parse_qs(url.query)
        body = self._read_json_body()
        if isinstance(body, tuple):
            return self._send_json(*body)
        ctl = srv.control
        if method == 'POST':
            table = ctl._dispatch_post
        elif method == 'PUT':
            table = ctl._dispatch_put
        else:
            return self._method_not_allowed()

        def _invoke(handler, arg_shape, groups):
            if arg_shape == 'none':
                return handler()
            if arg_shape == 'body':
                return handler(body)
            if arg_shape == 'body_query':
                return handler(body, query)
            if arg_shape == 'groups':
                return handler(*groups)
            if arg_shape == 'groups_body':
                return handler(*groups, body)
            raise ValueError(f'unknown arg_shape {arg_shape!r}')
        for key, (method_name, arg_shape) in table.items():
            if key.startswith('^'):
                continue
            if path == key:
                handler = getattr(ctl, method_name)
                return self._send_json(*_invoke(handler, arg_shape, ()))
        for key, (method_name, arg_shape) in table.items():
            if not key.startswith('^'):
                continue
            m = re.fullmatch(key[1:], path)
            if m is not None:
                handler = getattr(ctl, method_name)
                return self._send_json(*_invoke(handler, arg_shape, m.groups()))
        self._send_json(404, {'error': 'no mutation handler', 'path': path, 'method': method})

    def _read_json_body(self):
        """Returns parsed JSON dict on success, or (status, body) tuple on error."""
        cl = self.headers.get('Content-Length')
        if cl is None:
            return {}
        try:
            length = int(cl)
        except ValueError:
            return (400, {'error': 'invalid Content-Length'})
        if length == 0:
            return {}
        if length > webui_control.MAX_BODY_BYTES:
            return (400, {'error': 'body too large', 'limit': webui_control.MAX_BODY_BYTES})
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return (400, {'error': 'invalid_json', 'detail': str(exc)})

    def _send_json(self, status: int, body: Any, headers: Optional[dict[str, str]]=None) -> None:
        data = json.dumps(body, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)

    def _dispatch_get(self) -> None:
        path = urlsplit(self.path).path
        if path == '/':
            return self._handle_root()
        if path.startswith('/static/'):
            return self._handle_static(path)
        if path == '/api/health':
            return self._handle_health()
        if path == '/api/state':
            return self._handle_state()
        if path == '/api/track-record':
            return self._handle_track_record()
        if path == '/api/planner/current':
            return self._handle_planner_current()
        if path == '/events':
            return self._handle_events()
        if path == '/api/csrf':
            return self._handle_csrf_issue()
        if path == '/api/auth/whoami':
            return self._handle_whoami()
        if path == '/api/briefs':
            status, body = self.server.control.get_briefs()
            return self._send_json(status, body)
        if path == '/api/briefs/status':
            status, body = self.server.control.get_briefs_status()
            return self._send_json(status, body)
        if path == '/api/autowork/status':
            status, body = self.server.control.get_autowork_status()
            return self._send_json(status, body)
        if path == '/api/autowork/allowlist':
            status, body = self.server.control.get_autowork_allowlist()
            return self._send_json(status, body)
        if path == '/api/rebuild/status':
            status, body = self.server.control.get_rebuild_status()
            return self._send_json(status, body)
        m = re.match('^/api/briefs/([a-z0-9_]+)$', path)
        if m:
            status, body = self.server.control.get_brief(m.group(1))
            return self._send_json(status, body)
        if path == '/api/planner/jobs':
            status, body = self.server.control.get_planner_jobs()
            return self._send_json(status, body)
        m = re.match('^/api/planner/jobs/([A-Za-z0-9._-]+)$', path)
        if m:
            status, body = self.server.control.get_planner_job(m.group(1))
            return self._send_json(status, body)
        if path == '/api/config':
            status, body = self.server.control.get_config()
            return self._send_json(status, body)
        if path == '/api/config/schema':
            status, body = self.server.control.get_config_schema()
            return self._send_json(status, body)
        if path == '/api/control/phases':
            status, body = self.server.control.get_control_phases()
            return self._send_json(status, body)
        m = re.match('^/api/tasks/(queued|processing|processed|blocked)$', path)
        if m:
            return self._handle_tasks_partition(m.group(1))
        m = re.match('^/api/output/([^/]+)$', path)
        if m:
            return self._handle_output(m.group(1))
        m = re.match('^/api/fuzz/([^/]+)/([^/]+)$', path)
        if m:
            return self._handle_fuzz(m.group(1), m.group(2))
        self._send_json(404, {'error': 'not found', 'path': path})

    def _send_bytes(self, status: int, body: bytes, content_type: str, cache_control: str | None=None) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if cache_control is not None:
            self.send_header('Cache-Control', cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _handle_root(self) -> None:
        index = STATIC_ROOT / 'index.html'
        if not index.exists():
            self._send_json(404, {'error': 'index.html not found'})
            return
        self._send_bytes(200, index.read_bytes(), STATIC_CONTENT_TYPES['.html'], cache_control='no-cache')

    def _handle_static(self, path: str) -> None:
        rel = unquote(path[len('/static/'):])
        if not rel or rel.endswith('/'):
            self._send_json(404, {'error': 'no directory listing'})
            return
        ext = Path(rel).suffix.lower()
        if ext not in STATIC_CONTENT_TYPES:
            self._send_json(404, {'error': 'unsupported asset type', 'ext': ext})
            return
        target = STATIC_ROOT / rel
        real = self._resolve_inside(STATIC_ROOT, target)
        if real is None:
            self._send_json(400, {'error': 'path outside static root'})
            return
        if not real.exists() or not real.is_file():
            self._send_json(404, {'error': 'asset not found'})
            return
        self._send_bytes(200, real.read_bytes(), STATIC_CONTENT_TYPES[ext], cache_control='no-cache')

    def _handle_csrf_issue(self) -> None:
        srv: 'WebUIServer' = self.server
        nonce = webui_auth.mint_csrf_nonce(srv.state_dir)
        self._send_json(200, {'nonce': nonce, 'ttl_sec': webui_auth.NONCE_TTL_SEC})

    def _handle_whoami(self) -> None:
        srv: 'WebUIServer' = self.server
        present = webui_auth.check_auth(self.headers, srv.operator_token)
        self._send_json(200, {'token_present': bool(present)})

    def _handle_health(self) -> None:
        srv: 'WebUIServer' = self.server
        state_path = srv.state_dir / 'STATE.json'
        try:
            mtime: Optional[float] = state_path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        body = {'ok': True, 'state_mtime': mtime, 'state_dir': str(srv.state_dir), 'logs_dir': str(srv.logs_dir), 'uptime_sec': time.time() - srv.start_time, 'buffer_lines': len(srv.tailer.buffer), 'sse_clients': len(srv.sse_clients)}
        self._send_json(200, body)

    def _handle_state(self) -> None:
        srv: 'WebUIServer' = self.server
        state_path = srv.state_dir / 'STATE.json'
        if not state_path.exists():
            self._send_json(503, {'error': 'STATE.json not initialized'})
            return
        try:
            snapshot, timed_out = _read_state_with_timeout(srv.state_dir, STATE_LOCK_TIMEOUT_SEC)
        except StateMissingError:
            self._send_json(503, {'error': 'state file missing'})
            return
        except StateCorruptError as exc:
            self._send_json(500, {'error': 'state corrupt', 'detail': str(exc)})
            return
        if timed_out or snapshot is None:
            with srv.state_cache_lock:
                cached = srv.state_cache.get('snapshot')
                cached_mtime = srv.state_cache.get('mtime')
            if cached is None:
                self._send_json(503, {'error': 'state lock contended; no cache'})
                return
            self._send_json(200, cached, headers={'X-State-Stale-Ts': str(cached_mtime or '')})
            return
        try:
            mtime = state_path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        with srv.state_cache_lock:
            srv.state_cache['snapshot'] = snapshot
            srv.state_cache['mtime'] = mtime
        self._send_json(200, snapshot)

    def _handle_track_record(self) -> None:
        srv: 'WebUIServer' = self.server
        path = srv.state_dir / 'track_record_events.jsonl'
        if not path.exists():
            self._send_json(200, {'events': []})
            return
        params = self._query()
        try:
            limit = min(int(params.get('limit', ['100'])[0]), 1000)
        except ValueError:
            limit = 100
        events = _read_recent_jsonl(path, limit)
        self._send_json(200, {'events': events, 'limit': limit})

    def _handle_planner_current(self) -> None:
        srv: 'WebUIServer' = self.server
        candidates: list[tuple[float, Path]] = []
        for base in (Path.cwd(), srv.state_dir):
            try:
                for p in base.glob('plan_*.json'):
                    try:
                        candidates.append((p.stat().st_mtime, p))
                    except FileNotFoundError:
                        continue
            except OSError:
                continue
        if not candidates:
            self._send_json(404, {'error': 'no planner artifact found'})
            return
        candidates.sort(reverse=True)
        path_plan = candidates[0][1]
        try:
            with open(path_plan, 'r') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json(500, {'error': 'plan unreadable', 'detail': str(exc)})
            return
        self._send_json(200, {'plan_file': str(path_plan), 'plan': data})

    def _handle_tasks_partition(self, partition: str) -> None:
        srv: 'WebUIServer' = self.server
        tasks_dir = srv.state_dir / 'tasks'
        if not tasks_dir.exists():
            self._send_json(503, {'error': 'state/tasks does not exist'})
            return
        params = self._query()
        try:
            limit = min(int(params.get('limit', ['50'])[0]), 500)
            offset = max(int(params.get('offset', ['0'])[0]), 0)
        except ValueError:
            limit, offset = (50, 0)
        part_dir = tasks_dir / partition
        items: list[dict[str, Any]] = []
        total = 0
        if part_dir.exists() and part_dir.is_dir():
            entries: list[tuple[float, str]] = []
            try:
                with os.scandir(part_dir) as it:
                    for entry in it:
                        if not entry.is_file():
                            continue
                        if not entry.name.endswith('.json'):
                            continue
                        try:
                            mtime = entry.stat().st_mtime
                        except FileNotFoundError:
                            continue
                        entries.append((mtime, entry.name))
            except OSError:
                pass
            entries.sort(reverse=True)
            total = len(entries)
            for mtime, name in entries[offset:offset + limit]:
                items.append({'name': name, 'mtime': mtime})
        self._send_json(200, {'partition': partition, 'items': items, 'total': total, 'limit': limit, 'offset': offset})

    def _resolve_inside(self, base: Path, child: Path) -> Optional[Path]:
        try:
            base_real = base.resolve()
            real = child.resolve()
        except OSError:
            return None
        try:
            real.relative_to(base_real)
        except ValueError:
            return None
        return real

    def _handle_output(self, task_id: str) -> None:
        if not _safe_id(task_id):
            self._send_json(400, {'error': 'invalid task_id'})
            return
        srv: 'WebUIServer' = self.server
        base = srv.state_dir / 'output'
        target = base / task_id
        real = self._resolve_inside(base, target)
        if real is None:
            self._send_json(400, {'error': 'path outside state-dir'})
            return
        if not real.exists():
            self._send_json(404, {'error': 'no output for task_id'})
            return
        if real.is_dir():
            entries: list[dict[str, Any]] = []
            try:
                with os.scandir(real) as it:
                    for e in it:
                        try:
                            st = e.stat()
                        except FileNotFoundError:
                            continue
                        entries.append({'name': e.name, 'size': st.st_size, 'mtime': st.st_mtime})
            except OSError:
                pass
            self._send_json(200, {'task_id': task_id, 'entries': entries})
            return
        try:
            with open(real, 'r', errors='replace') as f:
                content = f.read(MAX_OUTPUT_BYTES)
        except OSError as exc:
            self._send_json(500, {'error': 'read failed', 'detail': str(exc)})
            return
        self._send_json(200, {'task_id': task_id, 'content': content})

    def _handle_fuzz(self, task_id: str, round_id: str) -> None:
        if not _safe_id(task_id) or not _safe_id(round_id):
            self._send_json(400, {'error': 'invalid task_id or round'})
            return
        srv: 'WebUIServer' = self.server
        base = srv.logs_dir / 'fuzz_results'
        target = base / f'{task_id}_{round_id}.json'
        real = self._resolve_inside(base, target)
        if real is None:
            self._send_json(400, {'error': 'path outside logs-dir'})
            return
        if not real.exists():
            self._send_json(404, {'error': 'no fuzz result'})
            return
        try:
            with open(real, 'r') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json(500, {'error': 'unreadable', 'detail': str(exc)})
            return
        self._send_json(200, data)

    def _handle_events(self) -> None:
        srv: 'WebUIServer' = self.server
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        sse = SSEResponse(self, srv.tailer)
        with srv.sse_clients_lock:
            srv.sse_clients.append(sse)
        try:
            sse.serve(srv.shutdown_event)
        finally:
            with srv.sse_clients_lock:
                if sse in srv.sse_clients:
                    srv.sse_clients.remove(sse)

class WebUIServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], RequestHandlerClass: type, *, state_dir: Path, logs_dir: Path, tailer: StateTailer):
        super().__init__(server_address, RequestHandlerClass)
        self.state_dir = state_dir
        self.logs_dir = logs_dir
        self.tailer = tailer
        self.sse_clients: list[SSEResponse] = []
        self.sse_clients_lock = threading.Lock()
        self.state_cache: dict[str, Any] = {'snapshot': None, 'mtime': None}
        self.state_cache_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self.start_time = time.time()
        self.operator_token = webui_auth.load_or_mint_token(state_dir)
        self.csrf_sweeper_stop = threading.Event()
        self.csrf_sweeper = webui_auth.start_csrf_sweeper(state_dir, self.csrf_sweeper_stop)
        self.control = webui_control.ControlHandlers(state_dir, logs_dir)

def _broadcast_shutdown(server: WebUIServer) -> None:
    with server.sse_clients_lock:
        clients = list(server.sse_clients)
    for client in clients:
        try:
            client.write_event('server-shutdown', {'reason': 'sigterm'})
        except Exception:
            pass

def _install_signal_handlers(server: WebUIServer, tailer: StateTailer) -> None:

    def _handler(signum, frame):
        logger.info('signal %s received; broadcasting server-shutdown', signum)
        server.shutdown_event.set()
        _broadcast_shutdown(server)
        tailer.stop()
        threading.Thread(target=server.shutdown, daemon=True, name='webui-shutdown').start()
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        pass

def build_tailer(state_dir: Path, logs_dir: Path, buffer_size: int) -> StateTailer:
    fixed_paths: list[Path] = [state_dir / 'impl_progress.jsonl', state_dir / 'track_record_events.jsonl', logs_dir / 'claude_stream.jsonl', logs_dir / 'gemini_stream.jsonl', logs_dir / 'antigravity_stream.jsonl', logs_dir / 'overseer_chat.jsonl']
    tailer = StateTailer(fixed_paths, buffer_size=buffer_size)
    tailer.add_wildcard(str(state_dir / 'sessions' / '*.ledger.jsonl'))
    return tailer

def parse_args(argv: Optional[list[str]]=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='tools.webui_server', description='Read-only HTTP+SSE sidecar for JanusMask harness telemetry.')
    parser.add_argument('--state-dir', default='state', help='path to state/ (default: state)')
    parser.add_argument('--logs-dir', default='logs', help='path to logs/ (default: logs)')
    parser.add_argument('--host', default=DEFAULT_HOST, help=f'bind host (default: {DEFAULT_HOST})')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'bind port (default: {DEFAULT_PORT})')
    parser.add_argument('--buffer-lines', type=int, default=DEFAULT_BUFFER_LINES, help=f'tailer ring buffer cap (default: {DEFAULT_BUFFER_LINES})')
    return parser.parse_args(argv)

_ACTIVE_SERVER: Optional[WebUIServer] = None

def release_for_handover() -> None:
    """Close active WebUI port socket to allow rebinding."""
    global _ACTIVE_SERVER
    if _ACTIVE_SERVER is not None:
        try:
            logger.info("Closing active WebUI socket for handover.")
            _ACTIVE_SERVER.server_close()
        except Exception as e:
            logger.warning(f"Failed to close WebUI socket: {e}")

def main(argv: Optional[list[str]]=None) -> int:
    global _ACTIVE_SERVER
    args = parse_args(argv)
    logging.basicConfig(level=os.environ.get('WEBUI_LOG_LEVEL', 'INFO'), stream=sys.stderr, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    state_dir = Path(args.state_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    tailer = build_tailer(state_dir, logs_dir, args.buffer_lines)
    tailer.start()
    server = WebUIServer((args.host, args.port), WebUIHandler, state_dir=state_dir, logs_dir=logs_dir, tailer=tailer)
    _ACTIVE_SERVER = server
    _install_signal_handlers(server, tailer)
    logger.info('WebUI sidecar listening on http://%s:%d', args.host, args.port)
    webui_auth.announce_token(state_dir, args.host, args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.server_close()
        except Exception:
            pass
        tailer.stop()
        logger.info('WebUI sidecar stopped')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())

def _invoke(handler: Callable[..., Any], arg_shape: str, groups: Tuple[str, ...], body: Any, query: Mapping[str, List[str]]) -> Any:
    """Invoke `handler` according to `arg_shape`.

    Discriminants and call signatures:
      'none'        -> handler()
      'body'        -> handler(body)
      'body_query'  -> handler(body, query)
      'groups'      -> handler(*groups)
      'groups_body' -> handler(*groups, body)

    Raises ValueError on any other arg_shape value (defensive guard against
    table corruption).
    """
    if arg_shape == 'none':
        return handler()
    if arg_shape == 'body':
        return handler(body)
    if arg_shape == 'body_query':
        return handler(body, query)
    if arg_shape == 'groups':
        return handler(*groups)
    if arg_shape == 'groups_body':
        return handler(*groups, body)
    raise ValueError(f'unknown arg_shape {arg_shape!r}')

def _resolve_route(table: DispatchTable, path: str) -> Optional[Tuple[Callable[..., Any], str, Tuple[str, ...]]]:
    """Resolve `path` against `table` using literal-first, regex-second order.

    Returns (handler, arg_shape, groups) on match, or None on no match.
    `groups` is the empty tuple for literal matches.
    """
    for key, (handler, arg_shape) in table.items():
        if key.startswith('^'):
            continue
        if path == key:
            return (handler, arg_shape, ())
    for key, (handler, arg_shape) in table.items():
        if not key.startswith('^'):
            continue
        m = re.fullmatch(key[1:], path)
        if m is not None:
            return (handler, arg_shape, m.groups())
    return None

def dispatch_mutation(self, method: str) -> None:
    """Table-driven replacement for the legacy `_dispatch_mutation` chain.

    Prologue (lines 329-345 of current file) is preserved byte-identically;
    only the post-prologue routing is refactored.
    """
    srv = self.server
    if not webui_auth.check_auth(self.headers, srv.operator_token):
        self._send_json(401, {'error': 'missing or invalid X-Operator-Token'})
        return
    nonce = self.headers.get('X-CSRF-Nonce') or self.headers.get('x-csrf-nonce')
    if not nonce:
        self._send_json(403, {'error': 'missing X-CSRF-Nonce'})
        return
    if not webui_auth.check_and_consume_csrf(srv.state_dir, nonce):
        self._send_json(403, {'error': 'invalid, expired, or replayed nonce'})
        return
    url = urlsplit(self.path)
    path = url.path
    query = parse_qs(url.query)
    body = self._read_json_body()
    if isinstance(body, tuple):
        return self._send_json(*body)
    ctl = srv.control
    if method == 'POST':
        table = ctl._dispatch_post
    elif method == 'PUT':
        table = ctl._dispatch_put
    else:
        return self._method_not_allowed()
    resolved = _resolve_route(table, path)
    if resolved is None:
        return self._send_json(404, {'error': 'no mutation handler', 'path': path, 'method': method})
    handler, arg_shape, groups = resolved
    return self._send_json(*_invoke(handler, arg_shape, groups, body, query))
''',
    'tools/webui_static/app.js': r'''// JanusMask WebUI v2 — single-page operator console.
// Vanilla ES2022. Hash-routed pages. SSE for live state.
"use strict";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
const TOKEN_KEY = "janusmask.operator_token";

function getToken() {
  // 1) ?token=… in URL takes precedence and persists
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("token");
  if (fromQuery) {
    localStorage.setItem(TOKEN_KEY, fromQuery);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url);
  }
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}

async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const token = getToken();
  if (token) headers.set("X-Operator-Token", token);
  if (["POST", "PUT", "DELETE"].includes(opts.method || "GET")) {
    const nonceRes = await fetch("/api/csrf", { headers });
    if (nonceRes.ok) {
      const { nonce } = await nonceRes.json();
      headers.set("X-CSRF-Nonce", nonce);
    }
    if (opts.body && typeof opts.body !== "string") {
      headers.set("Content-Type", "application/json");
      opts.body = JSON.stringify(opts.body);
    }
  }
  const res = await fetch(path, { ...opts, headers });
  let body = null;
  try { body = await res.json(); } catch {}
  if (!res.ok) {
    toast(`${opts.method || "GET"} ${path} → ${res.status} ${body?.error || ""}`, "err");
  }
  return { status: res.status, body };
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

// ---------------------------------------------------------------------------
// SSE store
// ---------------------------------------------------------------------------
const store = {
  state: null,
  recentEvents: [],
  streams: { claude: [], gemini: [] },
  parseFailures: 0,
  subscribers: new Set(),
};
function notify() { store.subscribers.forEach((fn) => fn()); }

// ---------------------------------------------------------------------------
// AW9d: transient per-slug badge overlays for the brief panel.
// Populated by the SSE tail handler when one of the three new ledger event
// types (plan_kickoff / extract / planner_hallucination_discarded) arrives;
// consulted in pages.briefs render to override the pill text/style for the
// matching row. Entries expire after 30s (plan_kickoff, extract) or 60s
// (planner_hallucination_discarded) and are removed lazily on read.
// ---------------------------------------------------------------------------
const transientBriefBadges = new Map();
const TRANSIENT_BADGE_EVENTS = new Set([
  "plan_kickoff",
  "extract",
  "planner_hallucination_discarded",
]);
const TRANSIENT_BADGE_TTL_MS = {
  plan_kickoff: 30000,
  extract: 30000,
  planner_hallucination_discarded: 60000,
};
const TRANSIENT_BADGE_COLOR = {
  plan_kickoff: "goldenrod",
  extract: "steelblue",
  planner_hallucination_discarded: "firebrick",
};

function _extractBriefSlug(raw) {
  if (raw == null) return "";
  let v = String(raw).trim();
  if (!v) return "";
  const slashIdx = v.lastIndexOf("/");
  if (slashIdx >= 0) v = v.slice(slashIdx + 1);
  if (v.startsWith("brief_hooks_")) v = v.slice("brief_hooks_".length);
  if (v.endsWith(".md")) v = v.slice(0, -3);
  return v.trim();
}

function _recordTransientBriefBadge(line) {
  if (!line || typeof line !== "object") return;
  const evt = line.event;
  if (typeof evt !== "string" || !TRANSIENT_BADGE_EVENTS.has(evt)) return;
  const slug = _extractBriefSlug(line.detail || line.task_id || line.slug || "");
  if (!slug) return;
  const ttl = TRANSIENT_BADGE_TTL_MS[evt] || 30000;
  transientBriefBadges.set(slug, { kind: evt, expiry: Date.now() + ttl });
}

function startSSE() {
  const es = new EventSource("/events");
  es.addEventListener("tail", (e) => {
    try {
      const data = JSON.parse(e.data);
      const path = data.path || "";
      let line = null;
      try { line = JSON.parse(data.line); } catch { line = { raw: data.line }; }
      if (path.includes("claude_stream.jsonl"))      store.streams.claude.push(line);
      else if (path.includes("gemini_stream.jsonl")) store.streams.gemini.push(line);
      else                                           store.recentEvents.push({ path, ...line });
      // AW9d: populate per-slug transient badge overlays from ledger events.
      _recordTransientBriefBadge(line);
      // bound buffers
      for (const k of ["claude", "gemini"]) {
        if (store.streams[k].length > 500) store.streams[k] = store.streams[k].slice(-500);
      }
      if (store.recentEvents.length > 200) store.recentEvents = store.recentEvents.slice(-200);
      notify();
    } catch (err) { /* swallow */ }
  });
  es.addEventListener("server-shutdown", () => toast("server shutting down", "warn"));
  es.onerror = () => { toast("SSE disconnected; retrying…", "warn"); };
}

async function refreshState() {
  const { status, body } = await api("/api/state");
  if (status === 200 && body) {
    store.state = body;
    store.parseFailures = 0;
    notify();
  } else if (status === 503) {
    store.parseFailures++;
    if (store.parseFailures > 3) toast("STATE.json unavailable", "warn");
  }
}

// ---------------------------------------------------------------------------
// Top-bar status + orchestrator buttons
// ---------------------------------------------------------------------------
function renderTopbar() {
  const s = store.state || {};
  const phase = s.phase || "idle";
  const taskId = s.task_id || "—";
  const orchPill = document.getElementById("orch-status");
  const phasePill = document.getElementById("phase-pill");
  const taskPill = document.getElementById("task-pill");
  phasePill.textContent = "phase: " + phase;
  taskPill.textContent = "task: " + taskId;
  if (phase === "idle") { orchPill.className = "pill status-unknown"; orchPill.textContent = "orchestrator: idle"; }
  else                  { orchPill.className = "pill status-running"; orchPill.textContent = "orchestrator: " + phase; }
}

function wireOrchestratorButtons() {
  const handlers = {
    "orch-start":  "/api/orchestrator/start",
    "orch-stop":   "/api/orchestrator/stop",
    "orch-pause":  "/api/orchestrator/pause",
    "orch-resume": "/api/orchestrator/resume",
  };
  for (const [id, path] of Object.entries(handlers)) {
    document.getElementById(id).addEventListener("click", async () => {
      const { status, body } = await api(path, { method: "POST", body: {} });
      if (status === 200) toast(`${id.replace("orch-", "")} → ${body?.status || "ok"}`, "ok");
      refreshState();
    });
  }
}

// ---------------------------------------------------------------------------
// Autowork topbar: pill + 3 buttons + 5s status poll.
// ---------------------------------------------------------------------------
let autoworkPollHandle = null;
let lastAutoworkStatus = null;

async function refreshAutoworkStatus() {
  const pill = document.getElementById("autowork-status");
  const pauseBtn = document.getElementById("autowork-pause");
  const { status, body } = await api("/api/autowork/status");
  if (status !== 200 || !body || typeof body !== "object") {
    lastAutoworkStatus = null;
    if (pill) { pill.className = "pill status-unknown"; pill.textContent = "autowork: ?"; }
    if (pauseBtn) pauseBtn.textContent = "⏸ pause";
    return;
  }
  lastAutoworkStatus = body;
  if (!pill) return;
  const alive = !!body.alive;
  const paused = !!body.paused;
  const cap = Number.isFinite(body.cap) ? body.cap : 0;
  const running = Array.isArray(body.running_jobs) ? body.running_jobs.length : 0;
  let cls;
  let text;
  if (!alive) {
    cls = "status-stopped";
    text = "autowork: stopped";
  } else if (paused) {
    cls = "status-paused";
    text = "autowork: paused";
  } else {
    cls = "status-running";
    text = `autowork: running ${running}/${cap}`;
  }
  pill.className = "pill " + cls;
  pill.textContent = text;
  if (pauseBtn) pauseBtn.textContent = paused ? "▶ resume" : "⏸ pause";
}

// newChatSession: start a brand-new chat session. Resets the in-memory state
// (null the conversation id so the next send boots a fresh conversation
// server-side, empty the replay buffer) and clears the self-managed
// #chat-transcript DOM, guarding the getElementById result before touching
// innerHTML (the container may not be mounted yet). Wired to the #chat-clear
// control in _wireChatPanel.
function newChatSession() {
  overseerChat.cid = null;
  overseerChat.buffer = [];
  const cont = document.getElementById("chat-transcript");
  if (cont) cont.innerHTML = "";
}

function wireAutoworkButtons() {
  document.getElementById("autowork-start")?.addEventListener("click", async () => {
    const { status, body } = await api("/api/autowork/start", { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
  document.getElementById("autowork-stop")?.addEventListener("click", async () => {
    const { status, body } = await api("/api/autowork/stop", { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
  document.getElementById("autowork-pause")?.addEventListener("click", async () => {
    const path = (lastAutoworkStatus && lastAutoworkStatus.paused)
      ? "/api/autowork/resume"
      : "/api/autowork/pause";
    const { status, body } = await api(path, { method: "POST", body: {} });
    if (status === 200) toast(`autowork: ${body?.status || "ok"}`, "ok");
    refreshAutoworkStatus();
  });
}

function startAutoworkPolling() {
  if (autoworkPollHandle !== null) return;
  refreshAutoworkStatus();
  autoworkPollHandle = setInterval(refreshAutoworkStatus, 5000);
}

function stopAutoworkPolling() {
  if (autoworkPollHandle !== null) {
    clearInterval(autoworkPollHandle);
    autoworkPollHandle = null;
  }
}

window.addEventListener("beforeunload", stopAutoworkPolling);
window.addEventListener("pagehide", stopAutoworkPolling);

// ---------------------------------------------------------------------------
// Autobrief helpers (F3): localStorage agent persistence + CSRF nonce fetch
// for the manual fetch path needed to attach an AbortSignal.
// ---------------------------------------------------------------------------
const AUTOBRIEF_AGENT_KEY = "autobrief_agent";

function readAutobriefAgent() {
  try {
    const v = localStorage.getItem(AUTOBRIEF_AGENT_KEY);
    if (v === "claude" || v === "gemini") return v;
  } catch (_) { /* localStorage missing or denied -> default */ }
  return "claude";
}

function writeAutobriefAgent(v) {
  if (v !== "claude" && v !== "gemini") return;
  try { localStorage.setItem(AUTOBRIEF_AGENT_KEY, v); } catch (_) { /* silent */ }
}

async function fetchCsrfNonce() {
  const headers = new Headers();
  const tk = getToken();
  if (tk) headers.set("X-Operator-Token", tk);
  try {
    const res = await fetch("/api/csrf", { headers });
    if (!res.ok) return "";
    const j = await res.json();
    return j.nonce || "";
  } catch (_) { return ""; }
}

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
const pages = {};

pages.dashboard = async () => {
  await refreshState();
  const s = store.state || {};
  return `
    <h2>Dashboard</h2>
    <div class="row">
      <div class="col card">
        <h3>Current state</h3>
        <table>
          <tr><th>phase</th><td>${s.phase || "—"}</td></tr>
          <tr><th>task_id</th><td>${s.task_id || "—"}</td></tr>
          <tr><th>round</th><td>${s.round ?? "—"}</td></tr>
          <tr><th>claude</th><td>${s.claude_status || "—"} ${s.claude_pid ? "(pid " + s.claude_pid + ")" : ""}</td></tr>
          <tr><th>gemini</th><td>${s.gemini_status || "—"} ${s.gemini_pid ? "(pid " + s.gemini_pid + ")" : ""}</td></tr>
          <tr><th>cross-exam</th><td>${s.cross_exam_round ?? 0}</td></tr>
        </table>
      </div>
      <div class="col card">
        <h3>Recent events</h3>
        <pre>${escape(store.recentEvents.slice(-12).reverse().map((r) =>
          `${r.ts || ""} ${r.event || r.kind || "?"} ${r.task_id || ""}`).join("\n"))}</pre>
      </div>
    </div>`;
};

pages.briefs = async () => {
  const { body } = await api("/api/briefs/status");
  // S1 (session #26): surface per-brief autowork eligibility from
  // /api/autowork/status.eligibility (eligible[] + blocked[{slug,reason}]).
  const { body: awBody } = await api("/api/autowork/status");
  const elig = (awBody && awBody.eligibility && typeof awBody.eligibility === "object" && !awBody.eligibility.error)
    ? awBody.eligibility
    : null;
  const eligibleSet = new Set(elig ? (elig.eligible || []) : []);
  const blockedMap = new Map();
  if (elig) for (const blk of (elig.blocked || [])) blockedMap.set(blk.slug, blk.reason);
  const parkedMap = (elig && elig.parked && typeof elig.parked === "object") ? elig.parked : {};
  const eligBadge = (slug) => {
    if (!elig) return `<span class="pill status-stopped" title="eligibility unavailable">—</span>`;
    if (eligibleSet.has(slug)) return `<span class="pill status-running" title="eligible for autowork">eligible</span>`;
    const reason = blockedMap.get(slug);
    if (reason === "stale") return `<span class="pill status-blocked" title="brief older than max_age_sec">blocked: stale</span>`;
    if (reason === "not_in_allowlist") return `<span class="pill status-stopped" title="slug not in auto_promote.allowlist">blocked: not allowlisted</span>`;
    return `<span class="pill status-stopped" title="${escape(String(reason || "blocked"))}">blocked${reason ? ": " + escape(String(reason)) : ""}</span>`;
  };
  const stateClass = {
    complete: "status-running",
    in_flight: "status-paused",
    queued: "status-queued",
    blocked: "status-blocked",
    planned: "status-stopped",
    unplanned: "status-stopped",
  };
  const now = Date.now();
  const items = (body?.briefs || []).map((b) => {
    const n_accepted = (b.accepted || []).length;
    const n_total = (b.task_ids || []).length;
    const n_remaining = (b.remaining || []).length;
    const n_in_flight = n_total - n_accepted - n_remaining;
    const state = b.state;
    const cls = stateClass[state] || "status-stopped";
    let pillText;
    if (state === "complete")       pillText = "complete";
    else if (state === "in_flight") pillText = `${n_accepted}/${n_total}, ${n_in_flight} in flight`;
    else if (state === "queued")    pillText = `${n_accepted}/${n_total}, ${n_remaining} pending`;
    else if (state === "blocked")   pillText = "blocked";
    else if (state === "planned")   pillText = "planned (0 tasks)";
    else if (state === "unplanned") pillText = "no plan";
    else                            pillText = String(state ?? "");
    // AW9d: consult the transient badge map and override the pill when a
    // plan_kickoff / extract / planner_hallucination_discarded ledger event
    // is still within its decay window for this slug.
    let pillStyle = "";
    const transient = transientBriefBadges.get(b.slug);
    if (transient) {
      if (transient.expiry > now) {
        pillText = transient.kind;
        const color = TRANSIENT_BADGE_COLOR[transient.kind] || "goldenrod";
        pillStyle = ` style="background:${color};color:#fff;border-color:${color};"`;
      } else {
        transientBriefBadges.delete(b.slug);
      }
    }
    return `<tr>
      <td><a href="#/briefs/${escape(b.slug)}">${escape(b.slug)}</a></td>
      <td><span class="pill ${cls}"${pillStyle}>${escape(pillText)}</span></td>
      <td>${eligBadge(b.slug)}${(parkedMap[b.slug] && parkedMap[b.slug].length)
        ? ` <span class="pill status-blocked" title="task(s) parked in processed/ unaccepted — zombie">zombie: ${parkedMap[b.slug].length} parked</span>`
        : ""}</td>
      <td>${n_accepted}/${n_total}</td>
      <td>${tsfmt(b.mtime)}</td>
    </tr>`;
  }).join("");
  return `
    <style>
      .status-queued  { background: rgba(88,166,255,0.15); color: var(--accent); border-color: var(--accent); }
      .status-blocked { background: rgba(248,81,73,0.15);  color: var(--err);    border-color: var(--err); }
    </style>
    <h2>Briefs</h2>
    <div class="card" id="autowork-eligibility-summary">
      <h3>Autowork eligibility</h3>
      ${elig
        ? `<p>
            <span class="pill status-running">${elig.eligible_count ?? eligibleSet.size} eligible</span>
            <span class="pill status-queued">${(elig.dispatchable || []).length} dispatchable</span>
            <span class="pill status-blocked">${elig.blocked_count ?? blockedMap.size} blocked</span>
            <span class="muted">allowlist ${elig.allowlist_present
              ? `present (${(elig.allowlist_slugs || []).length} slug(s))`
              : "absent — deny-all (nothing dispatches)"}; max_age ${Math.round((elig.max_age_sec || 0) / 86400)}d</span>
          </p>`
        : `<p class="muted">eligibility unavailable${awBody && awBody.eligibility && awBody.eligibility.error
            ? ": " + escape(String(awBody.eligibility.error))
            : ""}</p>`}
    </div>
    <div class="card">
      <button class="btn primary" id="brief-new">+ new brief</button>
    </div>
    <div class="card"><table>
      <thead><tr><th>slug</th><th>state</th><th>autowork</th><th>accepted/total</th><th>modified</th></tr></thead>
      <tbody>${items || `<tr><td colspan="5" class="muted">no briefs found</td></tr>`}</tbody>
    </table></div>`;
};

pages["briefs/edit"] = async (slug) => {
  let initial = "";
  if (slug && slug !== "_new") {
    const { body } = await api(`/api/briefs/${slug}`);
    initial = body?.content || "";
  }
  const savedAgent = readAutobriefAgent();

  setTimeout(() => {
    // ----- Agent toggle persistence ----------------------------------------
    const toggleRoot = document.getElementById("brief-agent-toggle");
    if (toggleRoot) {
      toggleRoot.querySelectorAll("input[name='brief-agent']").forEach((el) => {
        el.addEventListener("change", () => {
          if (el.checked) writeAutobriefAgent(el.value);
        });
      });
    }

    // ----- Existing action handlers ----------------------------------------
    document.getElementById("brief-validate")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      await api(`/api/briefs/${s}/validate`, { method: "POST", body: {} }).then(({ body }) => {
        if (body?.valid) toast("brief valid", "ok");
        else toast(`invalid: ${(body?.stderr_tail || "").slice(0, 200)}`, "err");
      });
    });
    document.getElementById("brief-save")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      const c = document.getElementById("brief-content").value;
      const { status } = await api(`/api/briefs?force=1`, { method: "POST", body: { slug: s, content: c } });
      if (status === 200) toast("saved", "ok");
    });
    document.getElementById("brief-kickoff")?.addEventListener("click", async () => {
      const s = document.getElementById("brief-slug").value;
      if (!confirm(`Kick off planner against brief_hooks_${s}.md? This spawns Claude+Gemini and consumes API quota.`)) return;
      const { status, body } = await api(`/api/planner/kickoff`, { method: "POST", body: { brief_slug: s } });
      if (status === 200) toast(`planner started: job ${body.job_id}`, "ok");
    });

    // ----- Autocomplete (F3) -----------------------------------------------
    const ACTION_IDS = ["brief-validate", "brief-save", "brief-kickoff", "brief-autocomplete"];

    const setActionsDisabled = (disabled) => {
      ACTION_IDS.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !!disabled;
      });
      document.querySelectorAll("#brief-agent-toggle input[name='brief-agent']").forEach((el) => {
        el.disabled = !!disabled;
      });
    };

    let abortCtrl = null;
    let tickHandle = null;
    let leaveListener = null;

    const cleanupRequestState = () => {
      if (tickHandle !== null) {
        clearInterval(tickHandle);
        tickHandle = null;
      }
      if (leaveListener) {
        window.removeEventListener("hashchange", leaveListener);
        leaveListener = null;
      }
    };

    document.getElementById("brief-autocomplete")?.addEventListener("click", async () => {
      const acBtn = document.getElementById("brief-autocomplete");
      const contentEl = document.getElementById("brief-content");
      const slugEl = document.getElementById("brief-slug");
      if (!acBtn || !contentEl || !slugEl) return;

      const roughDraft = contentEl.value || "";
      const slugHint = slugEl.value || "";
      const byteLen = new TextEncoder().encode(roughDraft).length;
      const needsConfirm = byteLen > 4096 || slugHint.trim() !== "";
      if (needsConfirm) {
        const msg = "Overwrite the current brief content and slug with an auto-completed draft?";
        if (!window.confirm(msg)) return;
      }

      const selected = document.querySelector("#brief-agent-toggle input[name='brief-agent']:checked");
      const agent = (selected && selected.value) || "claude";

      const originalLabel = acBtn.textContent;
      let elapsed = 0;
      acBtn.innerHTML = `<span class="autobrief-spinner" aria-hidden="true"></span><span class="autobrief-elapsed" id="brief-autocomplete-elapsed">0s</span>`;
      tickHandle = setInterval(() => {
        elapsed += 1;
        const ctr = document.getElementById("brief-autocomplete-elapsed");
        if (ctr) ctr.textContent = elapsed + "s";
      }, 1000);
      setActionsDisabled(true);

      abortCtrl = new AbortController();
      leaveListener = () => {
        try { abortCtrl && abortCtrl.abort(); } catch (_) { /* ignore */ }
        cleanupRequestState();
      };
      // {once: true} so it auto-removes if it fires; we also remove it manually on completion.
      window.addEventListener("hashchange", leaveListener, { once: true });

      const nonce = await fetchCsrfNonce();
      const headers = new Headers();
      const tk = getToken();
      if (tk) headers.set("X-Operator-Token", tk);
      if (nonce) headers.set("X-CSRF-Nonce", nonce);
      headers.set("Content-Type", "application/json");

      let res = null;
      let body = null;
      let aborted = false;
      try {
        res = await fetch("/api/briefs/autocomplete", {
          method: "POST",
          headers,
          body: JSON.stringify({ rough_draft: roughDraft, agent, slug_hint: slugHint }),
          signal: abortCtrl.signal,
        });
        try { body = await res.json(); } catch (_) { body = null; }
      } catch (err) {
        if (err && (err.name === "AbortError" || abortCtrl.signal.aborted)) {
          aborted = true;
        } else {
          cleanupRequestState();
          setActionsDisabled(false);
          acBtn.textContent = originalLabel;
          toast(`autocomplete failed: ${err && err.message ? err.message : err}`, "err");
          return;
        }
      }

      // Always tear down timers + leave-listener before we touch the DOM.
      cleanupRequestState();

      if (aborted) {
        // Page is being torn down; do not restore UI or surface a toast.
        return;
      }

      setActionsDisabled(false);
      acBtn.textContent = originalLabel;

      if (res && res.status === 200 && body) {
        if (typeof body.content === "string") contentEl.value = body.content;
        if (typeof body.slug === "string" && body.slug.length) slugEl.value = body.slug;
        const validation = body.validation || {};
        if (validation.ok) {
          toast("autocomplete: validation ok", "ok");
        } else {
          const stderr = String(validation.stderr || "");
          const card = document.createElement("div");
          card.className = "toast err";
          const head = document.createElement("div");
          head.textContent = "autocomplete: validation failed";
          card.appendChild(head);
          const det = document.createElement("details");
          det.className = "autobrief-validation-details";
          const sm = document.createElement("summary");
          sm.textContent = "stderr";
          det.appendChild(sm);
          const pre = document.createElement("pre");
          pre.textContent = stderr;
          det.appendChild(pre);
          card.appendChild(det);
          document.getElementById("toasts").appendChild(card);
          setTimeout(() => card.remove(), 12000);
        }
      } else {
        const errMsg = (body && body.error) ? body.error : `HTTP ${res ? res.status : "?"}`;
        const detail = (body && body.detail) ? ` — ${body.detail}` : "";
        toast(`autocomplete: ${errMsg}${detail}`, "err");
      }
    });
  }, 0);

  const claudeChecked = savedAgent === "claude" ? " checked" : "";
  const geminiChecked = savedAgent === "gemini" ? " checked" : "";
  return `
    <h2>Brief: ${escape(slug || "(new)")}</h2>
    <div class="card">
      <input type="text" id="brief-slug" value="${escape(slug === "_new" ? "" : slug)}" placeholder="slug (a-z0-9_)" />
    </div>
    <div class="card" id="brief-agent-toggle" role="radiogroup" aria-label="Autobrief agent">
      <label class="pill"><input type="radio" name="brief-agent" value="claude"${claudeChecked} /> Claude</label>
      <label class="pill"><input type="radio" name="brief-agent" value="gemini"${geminiChecked} /> Gemini</label>
    </div>
    <div class="card">
      <textarea id="brief-content">${escape(initial)}</textarea>
    </div>
    <div class="card row">
      <button class="btn" id="brief-autocomplete" title="Auto-complete this draft via the selected agent">✨ Auto-complete</button>
      <button class="btn" id="brief-validate">Validate</button>
      <button class="btn primary" id="brief-save">Save</button>
      <button class="btn" id="brief-kickoff">▶ Kick off planner</button>
    </div>`;
};

// ---------------------------------------------------------------------------
// Autowork allowlist editor + orphan-endpoint handlers (session #25).
// All call the api() wrapper so X-Operator-Token + X-CSRF-Nonce are honored.
// ---------------------------------------------------------------------------
async function loadAutoworkAllowlist() {
  const ta = document.getElementById("autowork-allowlist-text");
  const statusEl = document.getElementById("autowork-allowlist-status");
  const { status, body } = await api("/api/autowork/allowlist");
  if (status === 200 && body) {
    const slugs = body.slugs || [];
    if (ta) ta.value = slugs.join("\n");
    if (statusEl) {
      statusEl.textContent = body.file_present
        ? `restricted to ${slugs.length} slug(s)`
        : "no allowlist file — deny-all (nothing dispatches)";
      statusEl.className = "muted";
    }
  }
  return { status, body };
}

async function saveAutoworkAllowlist() {
  const ta = document.getElementById("autowork-allowlist-text");
  const slugs = (ta ? ta.value : "")
    .split("\n").map((s) => s.trim()).filter(Boolean);
  const { status, body } = await api("/api/autowork/allowlist", {
    method: "PUT", body: { slugs },
  });
  if (status === 200) {
    toast(slugs.length
      ? `allowlist saved (${slugs.length} slug(s))`
      : "allowlist cleared — deny-all (nothing dispatches)", "ok");
    loadAutoworkAllowlist();
  }
  return { status, body };
}

async function extractPlanToQueue(planFilename, taskIds = "all") {
  const { status, body } = await api(
    "/api/plans/" + encodeURIComponent(planFilename) + "/extract",
    { method: "POST", body: { task_ids: taskIds, canonical: true } });
  if (status === 200) {
    const n = Array.isArray(body?.extracted) ? body.extracted.length : "?";
    toast(`extracted ${n} task(s) from ${planFilename}`, "ok");
  }
  return { status, body };
}

async function decideTaskApproval(taskId, decision) {
  // POST /api/tasks/<id>/approve  (or /reject or /retry)
  if (!["approve", "reject", "retry"].includes(decision)) return { status: 0, body: null };
  const { status, body } = await api(
    "/api/tasks/" + encodeURIComponent(taskId) + "/" + decision,
    { method: "POST", body: { reason: "via UI" } });
  if (status === 200) toast(`${decision} ${taskId}`, "ok");
  return { status, body };
}

async function killAgent(agentName) {
  const { status, body } = await api(
    "/api/agents/" + encodeURIComponent(agentName) + "/kill",
    { method: "POST", body: {} });
  if (status === 200) toast(`killed ${agentName}${body?.pid ? " (pid " + body.pid + ")" : ""}`, "ok");
  return { status, body };
}

async function updateConfigControl(controlBody) {
  const { status, body } = await api("/api/config/control",
    { method: "PUT", body: controlBody });
  if (status === 200) toast("control config saved", "ok");
  return { status, body };
}

pages.plans = async () => {
  const { body } = await api("/api/planner/current");
  const data = body?.plan || {};
  const tasks = data.tasks || [];
  const items = tasks.map((t) =>
    `<tr><td><input type="checkbox" class="plan-row-cb" value="${escape(t.task_id)}" /></td>
         <td>${escape(t.task_id)}</td><td>${escape(t.meta_task_type || "")}</td>
         <td>${escape(t.priority || "")}</td>
         <td>${(t.dependencies || []).join(", ") || "—"}</td></tr>`).join("");
  const planFile = body?.plan_file || "";
  if (planFile) {
    setTimeout(() => {
      document.getElementById("plan-extract-btn")?.addEventListener("click",
        () => extractPlanToQueue(planFile, "all"));
      document.getElementById("plan-extract-sel-btn")?.addEventListener("click",
        async () => {
          const ids = Array.from(document.querySelectorAll(".plan-row-cb"))
            .filter((cb) => cb.checked).map((cb) => cb.value);
          if (!ids.length) { toast("no tasks selected", "warn"); return; }
          await extractPlanToQueue(planFile, ids);
        });
    }, 0);
  }
  const extractCard = planFile
    ? `<div class="card"><button id="plan-extract-btn" class="btn primary">Extract all to queue</button>
         <button id="plan-extract-sel-btn" class="btn">Extract selected</button>
         <span class="muted"> → ${escape(planFile)}</span></div>`
    : "";
  return `
    <h2>Plans</h2>
    <div class="card muted">${planFile ? "Showing: " + escape(planFile) : "no plan loaded"}</div>
    ${extractCard}
    <div class="card"><table>
      <thead><tr><th></th><th>task_id</th><th>type</th><th>priority</th><th>depends_on</th></tr></thead>
      <tbody>${items}</tbody>
    </table></div>
    <div class="card"><h3>Dependency graph</h3>${dagSvg(tasks)}</div>`;
};

pages.tasks = async () => {
  setTimeout(() => {
    document.querySelectorAll(".tab-row button").forEach((btn) => {
      btn.addEventListener("click", () => location.hash = `#/tasks/${btn.dataset.partition}`);
    });
  }, 0);
  return `
    <h2>Tasks</h2>
    <div class="tab-row">
      <button data-partition="queued">queued</button>
      <button data-partition="processing">processing</button>
      <button data-partition="processed">processed</button>
      <button data-partition="blocked">blocked</button>
    </div>
    <p class="muted">Pick a partition above.</p>`;
};

pages["tasks/list"] = async (partition) => {
  const { body } = await api(`/api/tasks/${partition}`);
  // WUI-3: a non-accepting task now parks in processed/ or blocked/. Offer a
  // per-row Re-queue (POST /api/tasks/<id>/retry -> _maybe_requeue_task) so the
  // operator can recover a parked task without touching the filesystem.
  const canRequeue = (partition === "processed" || partition === "blocked");
  const canDecide = (partition === "processing");
  const items = (body?.items || []).map((it) => {
    const tid = String(it.name).replace(/\.json$/, "");
    let action = "";
    if (canRequeue) {
      action = `<button class="btn" data-requeue="${escape(tid)}">Re-queue</button>`;
    } else if (canDecide) {
      action = `<button class="btn primary" data-decide="approve" data-tid="${escape(tid)}">Approve</button>
                <button class="btn danger" data-decide="reject" data-tid="${escape(tid)}">Reject</button>`;
    }
    return `<tr><td>${escape(it.name)}</td><td>${tsfmt(it.mtime)}</td><td>${action}</td></tr>`;
  }).join("");
  if (canRequeue) {
    setTimeout(() => {
      document.querySelectorAll("[data-requeue]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await decideTaskApproval(btn.dataset.requeue, "retry");
          renderRoute();
        });
      });
    }, 0);
  }
  if (canDecide) {
    setTimeout(() => {
      document.querySelectorAll("[data-decide]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await decideTaskApproval(btn.dataset.tid, btn.dataset.decide);
          renderRoute();
        });
      });
    }, 0);
  }
  return `
    <h2>Tasks → ${partition}</h2>
    <div class="card"><table>
      <thead><tr><th>filename</th><th>mtime</th><th>action</th></tr></thead>
      <tbody>${items || `<tr><td colspan="3" class="muted">empty</td></tr>`}</tbody>
    </table></div>`;
};

pages.streams = async () => {
  const renderAgent = (agent) => {
    const events = store.streams[agent].slice(-50);
    return events.map((e) => streamCard(e)).join("");
  };
  setTimeout(() => {
    document.querySelectorAll("[data-kill-agent]").forEach((btn) => {
      btn.addEventListener("click", () => killAgent(btn.dataset.killAgent));
    });
  }, 0);
  return `
    <h2>Live agent streams</h2>
    <div class="row">
      <div class="col"><h3>Claude <button class="btn danger" data-kill-agent="claude">Kill</button></h3>${renderAgent("claude") || `<div class="muted">no events yet</div>`}</div>
      <div class="col"><h3>Gemini <button class="btn danger" data-kill-agent="gemini">Kill</button></h3>${renderAgent("gemini") || `<div class="muted">no events yet</div>`}</div>
    </div>`;
};

pages.approvals = async () => {
  // WUI-1c: a pending row is resolved once a later terminal event arrives for
  // the same task_id (HITL reject/approve emits phase_transition accepted/
  // rejected; task_terminal also closes it). Keep only the latest unresolved
  // pending_approval per task_id, in arrival order.
  const resolved = new Set();
  for (const e of store.recentEvents) {
    if (e.event === "task_terminal" && e.task_id) resolved.add(e.task_id);
    if (e.event === "phase_transition" && e.task_id &&
        (e.phase === "accepted" || e.phase === "rejected")) resolved.add(e.task_id);
  }
  const seen = new Set();
  const pending = store.recentEvents
    .filter((e) => e.event === "pending_approval" && e.task_id && !resolved.has(e.task_id))
    .filter((e) => { if (seen.has(e.task_id)) return false; seen.add(e.task_id); return true; });
  if (!pending.length) return `<h2>Approvals</h2><div class="card muted">No pending approvals.</div>`;
  setTimeout(() => {
    document.querySelectorAll("[data-decide]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const { task, decide: decision } = btn.dataset;
        await api(`/api/tasks/${task}/${decision}`, { method: "POST", body: { reason: "via UI" } });
        toast(`${decision} ${task}`, "ok");
        renderRoute();
      });
    });
  }, 0);
  return `<h2>Approvals</h2>` + pending.map((p) => `
    <div class="card">
      <h3>${escape(p.task_id)}</h3>
      <p>phase: <strong>${escape(p.detail || p.phase || "?")}</strong></p>
      <button class="btn primary" data-decide="approve" data-task="${escape(p.task_id)}">Approve</button>
      <button class="btn danger"  data-decide="reject"  data-task="${escape(p.task_id)}">Reject</button>
      <button class="btn"         data-decide="retry"   data-task="${escape(p.task_id)}">Retry</button>
    </div>`).join("");
};

pages.config = async () => {
  const { body } = await api("/api/config");
  // WUI-PHASES: populate the require_approval <select> from the single-source
  // GET /api/control/phases (control_gate.KNOWN_PHASES); fall back to the
  // literal if the endpoint is unavailable (the fallback also includes
  // ast_validation so it stays in sync with the server).
  const phasesResp = await api("/api/control/phases");
  const knownPhases = Array.isArray(phasesResp.body?.phases) && phasesResp.body.phases.length
    ? phasesResp.body.phases
    : ["synthesis","fuzzing","cross_examination","ast_validation","accepted","rejected","decomposition"];
  const cfg = body?.config || {};
  const aw = (cfg.autowork && typeof cfg.autowork === "object") ? cfg.autowork : {};
  let cap = parseInt(aw.parallel_cap, 10);
  if (!Number.isFinite(cap)) cap = 4;
  
  // Fetch GET /api/config/schema
  const schemaResp = await api("/api/config/schema");
  const schema = schemaResp.body || {};

  const fieldsHtml = (schema.fields || []).map(f => {
    if (f.dtype === 'bool') {
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="font-weight: bold; display: flex; align-items: center; gap: 8px;">
            <input type="checkbox" id="field-${escape(f.name)}"${schema.values?.[f.name] ? ' checked' : ''} /> ${escape(f.name)}
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(f.name)}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    }
    if (f.dtype === 'int' || f.dtype === 'float') {
      const step = f.dtype === 'float' ? 'any' : '1';
      const minAttr = f.min !== null && f.min !== undefined ? ` min="${f.min}"` : '';
      const maxAttr = f.max !== null && f.max !== undefined ? ` max="${f.max}"` : '';
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(f.name)}:
            <input type="number" id="field-${escape(f.name)}" step="${step}"${minAttr}${maxAttr} value="${escape(String(schema.values?.[f.name] ?? f.default ?? ''))}" style="display: block; width: 100%; max-width: 300px;" />
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(f.name)}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    }
    if (f.dtype === 'enum') {
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(f.name)}:
            <select id="field-${escape(f.name)}" style="display: block; width: 100%; max-width: 300px;">
              ${(f.choices || []).map(choice => {
                const isSel = choice === (schema.values?.[f.name] ?? f.default) ? ' selected' : '';
                return `<option value="${escape(choice)}"${isSel}>${escape(choice)}</option>`;
              }).join('')}
            </select>
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(f.name)}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    }
    if (f.dtype === 'path-file' || f.dtype === 'path-dir') {
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(f.name)}:
            <div style="display: flex; gap: 8px; max-width: 400px;">
              <input type="text" id="field-${escape(f.name)}" value="${escape(String(schema.values?.[f.name] ?? f.default ?? ''))}" style="flex: 1;" />
              <button type="button" class="btn btn-browse" data-field="${escape(f.name)}">Browse</button>
            </div>
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(f.name).replace(/\./g, '_')}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    }
    return `
      <div class="form-group" style="margin-bottom: 12px;">
        <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(f.name)}:
          <input type="text" id="field-${escape(f.name)}" value="${escape(String(schema.values?.[f.name] ?? f.default ?? ''))}" style="display: block; width: 100%; max-width: 300px;" />
        </label>
        <span class="error-msg typed-config-error" id="error-${escape(f.name)}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
      </div>`;
  }).join('');

  function renderProviderOptions(providers, keysPresent, selectedValue) {
    if (!providers) return '';
    return Object.entries(providers).map(([pId, p]) => {
      const isDisabled = p.api_backed && (!keysPresent || !keysPresent.includes(p.api_key_env));
      const isSelected = pId === selectedValue ? " selected" : "";
      const disabledAttr = isDisabled ? " disabled" : "";
      const lockLabel = isDisabled ? " (Locked)" : "";
      return `<option value="${escape(pId)}"${isSelected}${disabledAttr}>${escape(p.label)}${lockLabel}</option>`;
    }).join("");
  }

  const rolesHtml = (schema.roles || []).map(r => {
    if (r.dual) {
      const active = schema.values?.[r.config_key] || [];
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(r.name)} agents:
            <div style="display: flex; gap: 8px; max-width: 300px;">
              <select id="role-${escape(r.config_key)}-0" style="flex: 1;">
                ${renderProviderOptions(schema.providers, schema.keys_present, active[0])}
              </select>
              <select id="role-${escape(r.config_key)}-1" style="flex: 1;">
                ${renderProviderOptions(schema.providers, schema.keys_present, active[1])}
              </select>
            </div>
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(r.config_key).replace(/\./g, '_')}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    } else {
      const val = schema.values?.[r.config_key];
      return `
        <div class="form-group" style="margin-bottom: 12px;">
          <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(r.name)} agent:
            <select id="role-${escape(r.config_key)}" style="display: block; width: 100%; max-width: 300px;">
              ${renderProviderOptions(schema.providers, schema.keys_present, val)}
            </select>
          </label>
          <span class="error-msg typed-config-error" id="error-${escape(r.config_key).replace(/\./g, '_')}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
        </div>`;
    }
  }).join('');

  const apiKeysHtml = Object.values(schema.providers || {}).filter(p => p.api_key_env).map(p => {
    const isSaved = schema.keys_present?.includes(p.api_key_env);
    return `
      <div class="form-group" style="margin-bottom: 12px;">
        <label style="display: block; font-weight: bold; margin-bottom: 4px;">${escape(p.label)} API Key (${escape(p.api_key_env)}):
          <input type="password" id="api-key-${escape(p.api_key_env)}" placeholder="${isSaved ? '•••••••• (Saved)' : 'Enter API Key'}" style="display: block; width: 100%; max-width: 300px;" />
        </label>
        <span class="error-msg typed-config-error" id="error-api_key_${escape(p.api_key_env)}" style="color: var(--err); font-size: 0.85em; display: block; margin-top: 4px;"></span>
      </div>`;
  }).join('');

  setTimeout(() => {
    const saveBtn = document.getElementById("autowork-cap-save");
    const inp = document.getElementById("autowork-cap-input");
    const msgEl = document.getElementById("autowork-cap-msg");
    if (!saveBtn || !inp) return;
    saveBtn.addEventListener("click", async () => {
      const raw = parseInt(inp.value, 10);
      if (msgEl) { msgEl.textContent = ""; msgEl.className = "muted"; }
      const { status, body: resp } = await api("/api/config/autowork", {
        method: "PUT",
        body: { parallel_cap: Number.isFinite(raw) ? raw : 4 },
      });
      if (status === 200 && resp) {
        const { body: refreshed } = await api("/api/config");
        const rcfg = refreshed?.config || {};
        const raw2 = rcfg.autowork && rcfg.autowork.parallel_cap;
        const parsed = parseInt(raw2, 10);
        if (Number.isFinite(parsed)) inp.value = String(parsed);
        if (resp.clamped && msgEl) {
          msgEl.textContent = `value clamped to ${Number.isFinite(parsed) ? parsed : "?"}`;
          msgEl.className = "warn";
        } else {
          toast("autowork: parallel_cap saved", "ok");
        }
      }
    });
    const hbBtn = document.getElementById("autowork-hb-save");
    const hbInp = document.getElementById("autowork-hb-input");
    if (hbBtn && hbInp) {
      hbBtn.addEventListener("click", async () => {
        const raw = parseInt(hbInp.value, 10);
        if (!Number.isFinite(raw) || raw < 1) { toast("heartbeat_sec must be a positive integer", "warn"); return; }
        const { status } = await api("/api/config/autowork", {
          method: "PUT", body: { heartbeat_sec: raw },
        });
        if (status === 200) toast("autowork: heartbeat_sec saved", "ok");
      });
    }
  }, 0);
  
  const ctrl = (cfg.control && typeof cfg.control === "object") ? cfg.control : {};
  
  setTimeout(() => {
    loadAutoworkAllowlist();
    document.getElementById("autowork-allowlist-save")?.addEventListener("click", saveAutoworkAllowlist);
    document.getElementById("autowork-allowlist-reload")?.addEventListener("click", loadAutoworkAllowlist);
    document.getElementById("ctrl-save")?.addEventListener("click", () => {
      const obj = {};
      const ra = document.getElementById("ctrl-require-approval");
      if (ra) obj.require_approval = Array.from(ra.selectedOptions).map((o) => o.value);
      const at = document.getElementById("ctrl-approval-timeout");
      if (at && at.value.trim() !== "") obj.approval_timeout_sec = parseInt(at.value, 10);
      const pf = document.getElementById("ctrl-pause-flag");
      if (pf && pf.value.trim() !== "") obj.pause_flag_path = pf.value.trim();
      const dd = document.getElementById("ctrl-decisions-dir");
      if (dd && dd.value.trim() !== "") obj.decisions_dir = dd.value.trim();
      updateConfigControl(obj);
    });
  }, 0);

  setTimeout(() => {
    // Wire Browse buttons
    document.querySelectorAll(".btn-browse").forEach(btn => {
      btn.addEventListener("click", () => {
        const fieldName = btn.dataset.field;
        toast(`Browse clicked for ${fieldName} (file system picker target)`, "ok");
      });
    });
    
    // Wire Save button
    const typedSaveBtn = document.getElementById("typed-config-save");
    if (typedSaveBtn) {
      typedSaveBtn.addEventListener("click", async () => {
        // Clear previous errors
        document.querySelectorAll(".typed-config-error").forEach(el => el.textContent = "");
        
        // Assemble payload
        const payload = {};
        
        // 1. Fields
        if (schema.fields) {
          schema.fields.forEach(f => {
            const el = document.getElementById("field-" + f.name);
            if (!el) return;
            if (f.dtype === 'bool') {
              payload[f.name] = el.checked;
            } else if (f.dtype === 'int') {
              payload[f.name] = el.value.trim() === "" ? "" : parseInt(el.value, 10);
            } else if (f.dtype === 'float') {
              payload[f.name] = el.value.trim() === "" ? "" : parseFloat(el.value);
            } else {
              payload[f.name] = el.value;
            }
          });
        }
        
        // 2. Roles
        if (schema.roles) {
          schema.roles.forEach(r => {
            if (r.dual) {
              const el0 = document.getElementById(`role-${r.config_key}-0`);
              const el1 = document.getElementById(`role-${r.config_key}-1`);
              if (el0 && el1) {
                payload[r.config_key] = [el0.value, el1.value];
              }
            } else {
              const el = document.getElementById(`role-${r.config_key}`);
              if (el) {
                payload[r.config_key] = el.value;
              }
            }
          });
        }
        
        // 3. API Keys
        if (schema.providers) {
          Object.values(schema.providers).forEach(p => {
            if (p.api_key_env) {
              const el = document.getElementById(`api-key-${p.api_key_env}`);
              if (el && el.value) {
                payload[`api_key__${p.api_key_env}`] = el.value;
              }
            }
          });
        }
        
        // POST to /api/config/typed
        const { status, body } = await api("/api/config/typed", {
          method: "POST",
          body: payload
        });
        
        if (status === 200) {
          toast("Typed config saved successfully", "ok");
          // Re-render route to refresh values and placeholders
          renderRoute();
        } else if (status === 400 && body && body.field_errors) {
          for (const [key, msg] of Object.entries(body.field_errors)) {
            // Replace dots with underscores to match error element IDs
            const errId = "error-" + key.replace(/\./g, "_");
            const errEl = document.getElementById(errId);
            if (errEl) {
              errEl.textContent = msg;
            } else {
              toast(`Error on ${key}: ${msg}`, "err");
            }
          }
        }
      });
    }
  }, 0);

  return `
    <h2>Config</h2>
    <div class="card">
      <h3>Autowork</h3>
      <label>Parallel cap:
        <input id="autowork-cap-input" type="number" min="1" max="16" step="1" value="${cap}" />
      </label>
      <button id="autowork-cap-save" class="btn primary">Save</button>
      <span id="autowork-cap-msg" class="muted"></span>
      <div style="margin-top:8px">
        <label>Heartbeat (sec):
          <input id="autowork-hb-input" type="number" min="1" step="1" value="${(aw.heartbeat_sec != null ? escape(String(aw.heartbeat_sec)) : "1800")}" />
        </label>
        <button id="autowork-hb-save" class="btn">Save</button>
        <span class="muted"> idle re-scan interval</span>
      </div>
    </div>
    
    <div class="card" id="typed-config-card">
      <h3>Typed Config System</h3>
      <div id="typed-config-container">
        <h4 style="margin-top: 16px; margin-bottom: 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px;">Fields</h4>
        ${fieldsHtml}
        
        <h4 style="margin-top: 24px; margin-bottom: 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px;">Roles</h4>
        ${rolesHtml}
        
        <h4 style="margin-top: 24px; margin-bottom: 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px;">API Keys</h4>
        ${apiKeysHtml}
        
        <div style="margin-top: 24px;">
          <button id="typed-config-save" class="btn primary">Save Typed Config</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Autowork allowlist</h3>
      <p class="muted">Empty = deny-all (nothing dispatches); listing slugs restricts the daemon to only those.</p>
      <textarea id="autowork-allowlist-text" rows="6" placeholder="one brief slug per line"></textarea>
      <div class="row">
        <button id="autowork-allowlist-save" class="btn primary">Save allowlist</button>
        <button id="autowork-allowlist-reload" class="btn">Reload</button>
        <span id="autowork-allowlist-status" class="muted"></span>
      </div>
    </div>
    <div class="card">
      <h3>Control (HITL)</h3>
      <label>require_approval (phases):
        <select id="ctrl-require-approval" multiple size="5">
          ${knownPhases.map((ph) =>
            `<option value="${ph}"${Array.isArray(ctrl.require_approval) && ctrl.require_approval.includes(ph) ? " selected" : ""}>${ph}</option>`).join("")}
        </select>
      </label>
      <label>approval_timeout_sec: <input type="number" id="ctrl-approval-timeout" value="${ctrl.approval_timeout_sec != null ? escape(String(ctrl.approval_timeout_sec)) : ""}" /></label>
      <label>pause_flag_path: <input type="text" id="ctrl-pause-flag" value="${ctrl.pause_flag_path != null ? escape(String(ctrl.pause_flag_path)) : ""}" /></label>
      <label>decisions_dir: <input type="text" id="ctrl-decisions-dir" value="${ctrl.decisions_dir != null ? escape(String(ctrl.decisions_dir)) : ""}" /></label>
      <button id="ctrl-save" class="btn primary">Save control</button>
    </div>
    <div class="card"><pre>${escape(JSON.stringify(cfg, null, 2))}</pre></div>
    <div class="card muted">PUT /api/config/control accepts: require_approval, approval_timeout_sec, pause_flag_path, decisions_dir.</div>`;
};
''',
}

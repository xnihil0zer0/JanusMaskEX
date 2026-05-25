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
    _dispatch_post: dict[str, tuple[str, str]] = {'/api/auth/test_echo': ('post_auth_test_echo', 'none'), '/api/briefs': ('post_brief', 'body_query'), '/api/briefs/autocomplete': ('post_brief_autocomplete', 'body_query'), '/api/planner/kickoff': ('post_planner_kickoff', 'body'), '/api/orchestrator/start': ('post_orchestrator_start', 'none'), '/api/orchestrator/stop': ('post_orchestrator_stop', 'none'), '/api/orchestrator/pause': ('post_orchestrator_pause', 'none'), '/api/orchestrator/resume': ('post_orchestrator_resume', 'none'), '/api/scope-exception': ('post_scope_exception', 'body'), '^/api/briefs/([a-z0-9_]+)/validate$': ('post_brief_validate', 'groups'), '^/api/plans/([A-Za-z0-9._-]+)/extract$': ('post_plan_extract', 'groups_body'), '^/api/agents/([a-z]+)/kill$': ('post_agent_kill', 'groups'), '^/api/tasks/([A-Za-z0-9._-]+)/(approve|reject|retry)$': ('post_task_decision', 'groups_body'), '/api/autowork/start': ('post_autowork_start', 'none'), '/api/autowork/stop': ('post_autowork_stop', 'none'), '/api/autowork/pause': ('post_autowork_pause', 'none'), '/api/autowork/resume': ('post_autowork_resume', 'none'), '/api/rebuild/start': ('post_rebuild_start', 'body')}
    _dispatch_put: dict[str, tuple[str, str]] = {'/api/config/control': ('put_config_control', 'body'), '/api/config/autowork': ('put_config_autowork', 'body'), '/api/autowork/allowlist': ('put_autowork_allowlist', 'body')}
    _config_cache: dict = {}
    _config_cache_ts: float = 0.0

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
            job_id = f'job-{int(time.time())}-{secrets.token_hex(4)}'
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
                    if raw_cfg.get('synthesis', {}).get('antigravity_mode', False):
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

        # Resolve req_agent command and args from config.yaml
        try:
            cfg_path = self.repo_root / 'harness' / 'config.yaml'
            full_config = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            full_config = {}
        
        agent_cfg = full_config.get('agents', {}).get(req_agent, {})
        command = agent_cfg.get('command', req_agent)
        args = list(agent_cfg.get('args', []))
        
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
                parsed = json.loads(stdout_text)
                if 'slug' not in parsed or 'content' not in parsed:
                    raise ValueError('missing slug or content')
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
        return (200, {'job_id': info['job_id'], 'pid': info['pid'], 'brief': str(brief.relative_to(self.repo_root)), 'output_plan': out_plan, 'output_critique': out_crit})

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
            result['eligibility'] = compute_autowork_eligibility(self.repo_root, self.state_dir)
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
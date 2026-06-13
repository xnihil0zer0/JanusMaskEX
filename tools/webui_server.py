"""tools/webui_server.py -- stdlib HTTP+SSE sidecar exposing read-only harness lifecycle telemetry.

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
        if path == '/api/fs/list':
            status, body = self.server.control.get_fs_list(self._query())
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
        plan_path = candidates[0][1]
        try:
            with open(plan_path, 'r') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json(500, {'error': 'plan unreadable', 'detail': str(exc)})
            return
        self._send_json(200, {'plan_file': str(plan_path), 'plan': data})

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
    args_parser = argparse.ArgumentParser(prog='tools.webui_server', description='Read-only HTTP+SSE sidecar for JanusMask harness telemetry.')
    args_parser.add_argument('--state-dir', default='state', help='path to state/ (default: state)')
    args_parser.add_argument('--logs-dir', default='logs', help='path to logs/ (default: logs)')
    args_parser.add_argument('--host', default=DEFAULT_HOST, help=f'bind host (default: {DEFAULT_HOST})')
    args_parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'bind port (default: {DEFAULT_PORT})')
    args_parser.add_argument('--buffer-lines', type=int, default=DEFAULT_BUFFER_LINES, help=f'tailer ring buffer cap (default: {DEFAULT_BUFFER_LINES})')
    return args_parser.parse_args(argv)
_ACTIVE_SERVER: Optional[WebUIServer] = None

def release_for_handover() -> None:
    """Close active WebUI port socket to allow rebinding."""
    global _ACTIVE_SERVER
    if _ACTIVE_SERVER is not None:
        try:
            logger.info('Closing active WebUI socket for handover.')
            _ACTIVE_SERVER.server_close()
        except Exception as e:
            logger.warning(f'Failed to close WebUI socket: {e}')

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
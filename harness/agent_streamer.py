"""Real-time agent output streamer for JanusMask.

Parses NDJSON streams from Claude Code (stream-json) and Gemini CLI
(stream-json) and renders them to the operator console with color-coded
formatting. Also logs raw events to the harness log.

Claude: --output-format stream-json --include-partial-messages
  Events: system(init), stream_event(content_block_start/delta/stop,
          message_start/delta/stop), assistant, user, result

Gemini: -o stream-json
  Events: init, message(user/assistant), tool_use, tool_result, result
"""
from __future__ import annotations
import json
import logging
import os
import sys
import threading
from io import TextIOWrapper
from pathlib import Path
from typing import IO, Any, TextIO
log = logging.getLogger('janusmask.streamer')

class _C:
    RESET = '\x1b[0m'
    BOLD = '\x1b[1m'
    DIM = '\x1b[2m'
    ITALIC = '\x1b[3m'
    CLAUDE = '\x1b[38;5;33m'
    GEMINI = '\x1b[38;5;208m'
    OK = '\x1b[38;5;82m'
    WARN = '\x1b[38;5;220m'
    ERR = '\x1b[38;5;196m'
    INFO = '\x1b[38;5;245m'
    CODE = '\x1b[38;5;183m'
    THINK = '\x1b[38;5;141m'
    TOOL = '\x1b[38;5;117m'
    RESULT = '\x1b[38;5;48m'
    MUTED = '\x1b[38;5;240m'
    TEXT = '\x1b[38;5;255m'
import datetime

def _out(msg: str) -> None:
    ts = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    sys.stderr.write(f'{ts} {msg}\n')
    sys.stderr.flush()

def _agent_tag(agent: str) -> str:
    color = _C.CLAUDE if agent == 'claude' else _C.GEMINI
    return f'{color}{_C.BOLD}{agent.upper()}{_C.RESET}'

def _truncate(s: str, max_len: int=200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + f'...({len(s)} total)'

class ClaudeStreamParser:
    """Parses Claude Code --output-format stream-json --include-partial-messages."""

    def __init__(self, agent: str='claude'):
        self.agent = agent
        self.tag = _agent_tag(agent)
        self._current_block_type: str | None = None
        self._thinking_buffer: str = ''
        self._text_buffer: str = ''
        self._tool_name: str = ''
        self._tool_input_buffer: str = ''

    def handle_event(self, event: dict) -> None:
        etype = event.get('type', '')
        if etype == 'system':
            self._on_system(event)
        elif etype == 'stream_event':
            self._on_stream_event(event)
        elif etype == 'assistant':
            self._on_assistant(event)
        elif etype == 'user':
            self._on_user(event)
        elif etype == 'result':
            self._on_result(event)
        elif etype == 'rate_limit_event':
            self._on_rate_limit(event)
        else:
            log.debug('[%s] unknown event type: %s', self.agent, etype)

    def _on_system(self, event: dict) -> None:
        subtype = event.get('subtype', '')
        if subtype == 'init':
            model = event.get('model', '?')
            tools = event.get('tools', [])
            tool_names = [t.get('name', '?') if isinstance(t, dict) else str(t) for t in tools] if isinstance(tools, list) else []
            _out(f'  {self.tag} {_C.OK}init{_C.RESET} model={_C.BOLD}{model}{_C.RESET} tools={_C.DIM}{tool_names}{_C.RESET}')

    def _on_stream_event(self, event: dict) -> None:
        """Handle partial-message streaming events."""
        se = event.get('event', {})
        se_type = se.get('type', '')
        if se_type == 'content_block_start':
            block = se.get('content_block', {})
            self._current_block_type = block.get('type', '')
            if self._current_block_type == 'thinking':
                _out(f'  {self.tag} {_C.THINK}thinking...{_C.RESET}')
                self._thinking_buffer = ''
            elif self._current_block_type == 'text':
                self._text_buffer = ''
            elif self._current_block_type == 'tool_use':
                self._tool_name = block.get('name', '?')
                self._tool_input_buffer = ''
                _out(f'  {self.tag} {_C.TOOL}tool_use:{_C.RESET} {_C.BOLD}{self._tool_name}{_C.RESET}')
        elif se_type == 'content_block_delta':
            delta = se.get('delta', {})
            delta_type = delta.get('type', '')
            if delta_type == 'thinking_delta':
                chunk = delta.get('thinking', '')
                self._thinking_buffer += chunk
                if chunk.strip():
                    for line in chunk.split('\n'):
                        if line.strip():
                            _out(f'  {self.tag}   {_C.THINK}{_C.DIM}{line}{_C.RESET}')
            elif delta_type == 'text_delta':
                chunk = delta.get('text', '')
                self._text_buffer += chunk
                if chunk.strip():
                    for line in chunk.split('\n'):
                        if line.strip():
                            _out(f'  {self.tag}   {_C.TEXT}{line}{_C.RESET}')
            elif delta_type == 'input_json_delta':
                chunk = delta.get('partial_json', '')
                self._tool_input_buffer += chunk
        elif se_type == 'content_block_stop':
            if self._current_block_type == 'thinking':
                lines = self._thinking_buffer.count('\n') + 1
                _out(f'  {self.tag} {_C.THINK}thinking complete{_C.RESET} {_C.DIM}({lines} lines, {len(self._thinking_buffer)} chars){_C.RESET}')
            elif self._current_block_type == 'tool_use':
                self._show_tool_input()
            self._current_block_type = None
        elif se_type == 'message_start':
            pass
        elif se_type == 'message_delta':
            stop_reason = se.get('delta', {}).get('stop_reason', '')
            if stop_reason:
                _out(f'  {self.tag} {_C.DIM}stop_reason={stop_reason}{_C.RESET}')
        elif se_type == 'message_stop':
            pass

    def _show_tool_input(self) -> None:
        """Display the accumulated tool input JSON."""
        try:
            parsed = json.loads(self._tool_input_buffer)
            if not isinstance(parsed, dict):
                return
            cmd = parsed.get('command', '')
            args_raw = parsed.get('args', '')
            if cmd:
                _out(f'  {self.tag}   {_C.TOOL}command:{_C.RESET} {cmd}')
            if args_raw:
                try:
                    inner = json.loads(args_raw)
                    for k, v in inner.items():
                        if k == 'code':
                            lines = v.count('\n') + 1
                            _out(f'  {self.tag}   {_C.TOOL}code:{_C.RESET} {_C.DIM}({lines} lines, {len(v)} chars){_C.RESET}')
                            for i, line in enumerate(v.split('\n')[:8], 1):
                                _out(f'  {self.tag}     {_C.CODE}{_C.DIM}{i:3d} {line}{_C.RESET}')
                            if lines > 8:
                                _out(f'  {self.tag}     {_C.DIM}... ({lines - 8} more){_C.RESET}')
                        else:
                            val_str = str(v)
                            _out(f'  {self.tag}   {_C.TOOL}{k}:{_C.RESET} {_truncate(val_str, 120)}')
                except (json.JSONDecodeError, AttributeError):
                    _out(f'  {self.tag}   {_C.TOOL}args:{_C.RESET} {_truncate(args_raw, 200)}')
        except json.JSONDecodeError:
            if self._tool_input_buffer.strip():
                _out(f'  {self.tag}   {_C.DIM}raw input: {_truncate(self._tool_input_buffer, 200)}{_C.RESET}')

    def _on_assistant(self, event: dict) -> None:
        """Complete assistant message (emitted even with --include-partial-messages)."""
        msg = event.get('message', {})
        content = msg.get('content', [])
        for block in content:
            btype = block.get('type', '')
            if btype == 'tool_use':
                name = block.get('name', '?')
                inp = block.get('input', {})
                cmd = inp.get('command', '?')
                _out(f'  {self.tag} {_C.TOOL}[complete] tool_use:{_C.RESET} {name} -> {cmd}')

    def _on_user(self, event: dict) -> None:
        """Tool result returned to the model."""
        msg = event.get('message', {})
        content = msg.get('content', [])
        for block in content:
            btype = block.get('type', '')
            if btype == 'tool_result':
                tool_use_id = block.get('tool_use_id', '?')[:12]
                is_error = block.get('is_error', False)
                inner_content = block.get('content', '')
                if isinstance(inner_content, list):
                    inner_text = inner_content[0].get('text', '') if inner_content else ''
                elif isinstance(inner_content, str):
                    inner_text = inner_content
                else:
                    inner_text = str(inner_content)
                color = _C.ERR if is_error else _C.RESULT
                status = 'ERROR' if is_error else 'OK'
                _out(f'  {self.tag} {color}tool_result [{status}]{_C.RESET} {_C.DIM}id={tool_use_id}{_C.RESET}')
                try:
                    result_data = json.loads(inner_text)
                    if isinstance(result_data, dict):
                        if 'status' in result_data:
                            _out(f'  {self.tag}   {color}status={result_data['status']}{_C.RESET}')
                        if 'task_id' in result_data:
                            _out(f'  {self.tag}   {color}task_id={result_data['task_id']}{_C.RESET}')
                        if 'error' in result_data:
                            _out(f'  {self.tag}   {_C.ERR}{_truncate(result_data['error'], 120)}{_C.RESET}')
                        if 'specification' in result_data:
                            _out(f'  {self.tag}   {_C.DIM}spec: {_truncate(result_data['specification'], 120)}{_C.RESET}')
                except (json.JSONDecodeError, TypeError):
                    _out(f'  {self.tag}   {_C.DIM}{_truncate(inner_text, 150)}{_C.RESET}')

    def _on_result(self, event: dict) -> None:
        subtype = event.get('subtype', '?')
        cost = event.get('total_cost_usd', 0)
        duration = event.get('duration_ms', 0)
        usage = event.get('usage', {})
        inp_tok = usage.get('input_tokens', 0)
        out_tok = usage.get('output_tokens', 0)
        cache_read = usage.get('cache_read_input_tokens', 0)
        cache_create = usage.get('cache_creation_input_tokens', 0)
        color = _C.OK if subtype == 'success' else _C.ERR
        _out(f'\n  {self.tag} {color}{_C.BOLD}RESULT: {subtype}{_C.RESET}')
        _out(f'  {self.tag}   {_C.DIM}cost=${cost:.4f}  duration={duration / 1000:.1f}s  in={inp_tok}  out={out_tok}  cache_read={cache_read}  cache_create={cache_create}{_C.RESET}')

    def _on_rate_limit(self, event: dict) -> None:
        pct = event.get('percentage_remaining')
        reset = event.get('seconds_until_reset')
        _out(f'  {self.tag} {_C.WARN}rate_limit{_C.RESET} remaining={pct}%  reset_in={reset}s')

class GeminiStreamParser:
    """Parses Gemini CLI -o stream-json output."""

    def __init__(self, agent: str='gemini'):
        self.agent = agent
        self.tag = _agent_tag(agent)

    def handle_event(self, event: dict) -> None:
        etype = event.get('type', '')
        if etype == 'init':
            self._on_init(event)
        elif etype == 'message':
            self._on_message(event)
        elif etype == 'tool_use':
            self._on_tool_use(event)
        elif etype == 'tool_result':
            self._on_tool_result(event)
        elif etype == 'result':
            self._on_result(event)
        elif etype == 'rate_limit_event':
            self._on_rate_limit(event)
        else:
            log.debug('[%s] unknown event type: %s', self.agent, etype)

    def _on_init(self, event: dict) -> None:
        session = event.get('session_id', '?')
        model = event.get('model', '?')
        _out(f'  {self.tag} {_C.OK}init{_C.RESET} model={_C.BOLD}{model}{_C.RESET} session={_C.DIM}{session[:12]}{_C.RESET}')

    def _on_message(self, event: dict) -> None:
        role = event.get('role', '?')
        content = event.get('content', '')
        is_delta = event.get('delta', False)
        if role == 'user':
            _out(f'  {self.tag} {_C.DIM}user prompt: {_truncate(content, 100)}{_C.RESET}')
        elif role == 'assistant':
            if is_delta and content.strip():
                for line in content.split('\n'):
                    if line.strip():
                        _out(f'  {self.tag}   {_C.TEXT}{line}{_C.RESET}')

    def _on_tool_use(self, event: dict) -> None:
        tool_name = event.get('tool_name', '?')
        tool_id = event.get('tool_id', '?')[:12]
        params = event.get('parameters', {})
        if not isinstance(params, dict):
            params = {}
        _out(f'  {self.tag} {_C.TOOL}tool_use:{_C.RESET} {_C.BOLD}{tool_name}{_C.RESET} {_C.DIM}id={tool_id}{_C.RESET}')
        cmd = params.get('command', '')
        if cmd:
            _out(f'  {self.tag}   {_C.TOOL}command:{_C.RESET} {cmd}')
        raw_args = params.get('args', '')
        if raw_args:
            try:
                inner = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if isinstance(inner, dict):
                    for k, v in inner.items():
                        if k == 'code':
                            lines = str(v).count('\n') + 1
                            _out(f'  {self.tag}   {_C.TOOL}code:{_C.RESET} {_C.DIM}({lines} lines, {len(str(v))} chars){_C.RESET}')
                            for i, line in enumerate(str(v).split('\n')[:8], 1):
                                _out(f'  {self.tag}     {_C.CODE}{_C.DIM}{i:3d} {line}{_C.RESET}')
                            if lines > 8:
                                _out(f'  {self.tag}     {_C.DIM}... ({lines - 8} more){_C.RESET}')
                        else:
                            _out(f'  {self.tag}   {_C.TOOL}{k}:{_C.RESET} {_truncate(str(v), 120)}')
                else:
                    _out(f'  {self.tag}   {_C.TOOL}args:{_C.RESET} {_truncate(str(raw_args), 200)}')
            except (json.JSONDecodeError, TypeError):
                _out(f'  {self.tag}   {_C.TOOL}args:{_C.RESET} {_truncate(str(raw_args), 200)}')

    def _on_tool_result(self, event: dict) -> None:
        tool_id = event.get('tool_id', '?')[:12]
        status = event.get('status', '?')
        output = event.get('output', '')
        color = _C.ERR if status == 'error' else _C.RESULT
        _out(f'  {self.tag} {color}tool_result [{status}]{_C.RESET} {_C.DIM}id={tool_id}{_C.RESET}')
        if output:
            try:
                result_data = json.loads(output) if isinstance(output, str) else output
                if isinstance(result_data, dict):
                    if 'status' in result_data:
                        _out(f'  {self.tag}   {color}status={result_data['status']}{_C.RESET}')
                    if 'task_id' in result_data:
                        _out(f'  {self.tag}   {color}task_id={result_data['task_id']}{_C.RESET}')
                    if 'error' in result_data:
                        _out(f'  {self.tag}   {_C.ERR}{_truncate(str(result_data['error']), 120)}{_C.RESET}')
                    if 'specification' in result_data:
                        _out(f'  {self.tag}   {_C.DIM}spec: {_truncate(str(result_data['specification']), 120)}{_C.RESET}')
                else:
                    _out(f'  {self.tag}   {_C.DIM}{_truncate(str(output), 150)}{_C.RESET}')
            except (json.JSONDecodeError, TypeError):
                _out(f'  {self.tag}   {_C.DIM}{_truncate(str(output), 150)}{_C.RESET}')

    def _on_result(self, event: dict) -> None:
        status = event.get('status', '?')
        stats = event.get('stats', {})
        color = _C.OK if status == 'success' else _C.ERR
        _out(f'\n  {self.tag} {color}{_C.BOLD}RESULT: {status}{_C.RESET}')
        if stats:
            total_in = stats.get('total_input_tokens', 0)
            total_out = stats.get('total_output_tokens', 0)
            latency = stats.get('total_latency_ms', 0)
            if total_in or total_out:
                _out(f'  {self.tag}   {_C.DIM}in={total_in}  out={total_out}  latency={latency / 1000:.1f}s{_C.RESET}')
            else:
                for model_name, model_stats in stats.items():
                    if isinstance(model_stats, dict):
                        inp = model_stats.get('input_tokens', 0)
                        outp = model_stats.get('output_tokens', 0)
                        lat = model_stats.get('latency_ms', 0)
                        _out(f'  {self.tag}   {_C.DIM}{model_name}: in={inp} out={outp} latency={lat / 1000:.1f}s{_C.RESET}')

    def _on_rate_limit(self, event: dict) -> None:
        pct = event.get('percentage_remaining')
        reset = event.get('seconds_until_reset')
        _out(f'  {self.tag} {_C.WARN}rate_limit{_C.RESET} remaining={pct}%  reset_in={reset}s')

def _get_parser(agent: str) -> ClaudeStreamParser | GeminiStreamParser:
    if agent == 'claude':
        return ClaudeStreamParser(agent)
    return GeminiStreamParser(agent)

def stream_agent_output(pipe: IO[str], agent: str, log_path: Path | None=None) -> None:
    """Read NDJSON from an agent's stdout pipe and display events.

    Designed to run in a background thread. Reads until EOF.
    """
    parser = _get_parser(agent)
    tag = _agent_tag(agent)
    log_file = None
    try:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, 'a', encoding='utf-8')
        for raw_line in pipe:
            raw_line = raw_line.rstrip('\n\r')
            if not raw_line:
                continue
            if log_file:
                log_file.write(raw_line + '\n')
                log_file.flush()
            json_start = raw_line.find('{')
            if json_start < 0:
                if raw_line.strip():
                    _out(f'  {tag} {_C.MUTED}[raw] {raw_line}{_C.RESET}')
                continue
            json_str = raw_line[json_start:]
            if json_start > 0:
                prefix = raw_line[:json_start].strip()
                if prefix:
                    _out(f'  {tag} {_C.WARN}[prefix] {prefix}{_C.RESET}')
            try:
                event = json.loads(json_str)
                parser.handle_event(event)
            except json.JSONDecodeError as exc:
                _out(f'  {tag} {_C.ERR}JSON parse error:{_C.RESET} {exc}')
                _out(f'  {tag} {_C.MUTED}[raw] {_truncate(raw_line, 200)}{_C.RESET}')
    except Exception as exc:
        _out(f'  {tag} {_C.ERR}stream reader error: {exc}{_C.RESET}')
        log.exception('Stream reader error for %s', agent)
    finally:
        if log_file:
            log_file.close()

def stream_stderr(pipe: IO[str], agent: str) -> None:
    """Read stderr from an agent and display any non-empty lines."""
    tag = _agent_tag(agent)
    try:
        for line in pipe:
            line = line.rstrip('\n\r')
            if line.strip():
                _out(f'  {tag} {_C.MUTED}[stderr] {line}{_C.RESET}')
    except Exception:
        pass

def start_stream_threads(proc, agent: str, log_dir: Path | None=None) -> tuple[threading.Thread, threading.Thread]:
    """Start daemon threads to stream stdout and stderr from an agent process.

    Returns (stdout_thread, stderr_thread).
    """
    log_path = None
    if log_dir:
        log_path = log_dir / f'{agent}_stream.jsonl'
    stdout_thread = threading.Thread(target=stream_agent_output, args=(proc.stdout, agent, log_path), name=f'{agent}-stdout-streamer', daemon=True)
    stderr_thread = threading.Thread(target=stream_stderr, args=(proc.stderr, agent), name=f'{agent}-stderr-streamer', daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    return (stdout_thread, stderr_thread)
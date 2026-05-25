"""ConsoleStreamer — rich, formatted agent-activity output to stderr.

Extracted from harness/mcp_server.py (HOOK-12). Shared by both the legacy
MCP path and the new Claude/Gemini hook paths so that console output stays
byte-for-byte identical across the migration.

Public surface (imported as `harness.hooks.console`):
    ANSI palette class  :  _C
    Low-level helpers   :  _agent_color, _agent_label, _divider,
                           _code_preview, _stream
    ConsoleStreamer     :  per-session formatter used by MCP + hooks

Every symbol is imported by harness/mcp_server.py; keep names and signatures
stable. Changes here must be mirrored in the MCP server's on_* call-sites.
"""
from __future__ import annotations
import json
import sys

class _C:
    RESET = '\x1b[0m'
    BOLD = '\x1b[1m'
    DIM = '\x1b[2m'
    CLAUDE = '\x1b[38;5;33m'
    GEMINI = '\x1b[38;5;208m'
    OK = '\x1b[38;5;82m'
    WARN = '\x1b[38;5;220m'
    ERR = '\x1b[38;5;196m'
    INFO = '\x1b[38;5;245m'
    CODE = '\x1b[38;5;183m'
    HEADER = '\x1b[38;5;117m'
    MUTED = '\x1b[38;5;240m'

def _agent_color(agent_id: str) -> str:
    return _C.CLAUDE if agent_id == 'claude' else _C.GEMINI

def _agent_label(agent_id: str) -> str:
    color = _agent_color(agent_id)
    return f'{color}{_C.BOLD}{agent_id.upper()}{_C.RESET}'

def _divider(agent_id: str, char: str='─', width: int=60) -> str:
    color = _agent_color(agent_id)
    return f'{color}{char * width}{_C.RESET}'

def _code_preview(code: str, max_lines: int=12) -> str:
    MUTED = '\x1b[38;5;240m'
    CODE = '\x1b[38;5;183m'
    RESET = '\x1b[0m'
    DIM = '\x1b[2m'
    lines = code.rstrip().split('\n')
    truncated = len(lines) > max_lines
    display = lines[:max_lines]
    parts = []
    for i, line in enumerate(display, 1):
        parts.append(f'  {MUTED}{i:3d}{RESET} {CODE}{line}{RESET}')
    if truncated:
        parts.append(f'  {DIM}... ({len(lines) - max_lines} more lines){RESET}')
    return '\n'.join(parts)

def _stream(msg: str) -> None:
    sys.stderr.write(msg + '\n')
    sys.stderr.flush()

class ConsoleStreamer:
    """Streams formatted agent activity to the operator console (stderr).

    Each agent type (claude/gemini) gets color-coded output showing
    task retrieval, code submissions, validation results, feedback,
    errors, and clarification requests in real time.
    """

    def __init__(self, agent_id: str, session_id: str):
        self.agent_id = agent_id
        self.session_id = session_id

    def on_connect(self) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(_divider(self.agent_id, '═'))
        _stream(f'  {label} agent connected')
        _stream(f'  {_C.DIM}session: {self.session_id}{_C.RESET}')
        _stream(_divider(self.agent_id, '═'))

    def on_task_read(self, task: dict) -> None:
        label = _agent_label(self.agent_id)
        task_id = task.get('task_id', 'unknown')
        spec = task.get('specification', '')
        sig = task.get('constraints', {}).get('function_signature', '')
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.HEADER}READ TASK{_C.RESET}')
        _stream(f'  {_C.DIM}task_id:{_C.RESET} {task_id}')
        if sig:
            _stream(f'  {_C.DIM}signature:{_C.RESET} {_C.CODE}{sig}{_C.RESET}')
        if spec:
            preview = spec[:200] + ('...' if len(spec) > 200 else '')
            _stream(f'  {_C.DIM}spec:{_C.RESET} {preview}')
        _stream(_divider(self.agent_id))

    def on_submit_accepted(self, code: str, submission_num: int, max_subs: int, round_number: int, warnings: list) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.OK}{_C.BOLD}SUBMITTED CODE{_C.RESET}  {_C.DIM}[{submission_num}/{max_subs}, round {round_number}]{_C.RESET}')
        _stream('')
        _stream(_code_preview(code))
        _stream('')
        if warnings:
            _stream(f'  {_C.WARN}Warnings:{_C.RESET}')
            for w in warnings[:5]:
                _stream(f'    {_C.WARN}L{w.get('line', '?')}: {w.get('rule', '?')} — {w.get('message', '')}{_C.RESET}')
        else:
            _stream(f'  {_C.OK}AST validation: passed (no warnings){_C.RESET}')
        _stream(_divider(self.agent_id))

    def on_submit_rejected(self, code: str, violations: list) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.ERR}{_C.BOLD}SUBMISSION REJECTED{_C.RESET}')
        _stream('')
        _stream(_code_preview(code, max_lines=8))
        _stream('')
        _stream(f'  {_C.ERR}AST violations ({len(violations)}):{_C.RESET}')
        for v in violations[:8]:
            _stream(f'    {_C.ERR}L{v.get('line', '?')}: [{v.get('rule', '?')}] {v.get('message', '')}{_C.RESET}')
        if len(violations) > 8:
            _stream(f'    {_C.DIM}... and {len(violations) - 8} more{_C.RESET}')
        _stream(_divider(self.agent_id))

    def on_submit_rate_limited(self, max_subs: int) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(f'  {label} {_C.ERR}RATE LIMITED{_C.RESET} — max {max_subs} submissions reached')

    def on_clarification(self, question: str, num: int, remaining: int) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.HEADER}CLARIFICATION REQUEST{_C.RESET}  {_C.DIM}[#{num}, {remaining} remaining]{_C.RESET}')
        _stream(f'  {_C.INFO}{question}{_C.RESET}')
        _stream(_divider(self.agent_id))

    def on_error_report(self, error_msg: str) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.ERR}{_C.BOLD}ERROR REPORT{_C.RESET}')
        _stream(f'  {_C.ERR}{error_msg[:500]}{_C.RESET}')
        _stream(_divider(self.agent_id))

    def on_feedback_retrieved(self, feedback: dict) -> None:
        label = _agent_label(self.agent_id)
        round_number = feedback.get('round', '?')
        _stream('')
        _stream(_divider(self.agent_id))
        _stream(f'  {label} {_C.HEADER}FEEDBACK RETRIEVED{_C.RESET}  {_C.DIM}[round {round_number}]{_C.RESET}')
        code_under_review = feedback.get('code_under_review', '')
        if code_under_review:
            _stream(f'  {_C.DIM}code under review:{_C.RESET}')
            _stream(_code_preview(code_under_review, max_lines=6))
        prompt = feedback.get('review_prompt', '')
        if prompt:
            preview = prompt[:300] + ('...' if len(prompt) > 300 else '')
            _stream(f'  {_C.DIM}review prompt:{_C.RESET} {preview}')
        failures = feedback.get('previous_fuzz_failures', [])
        if failures:
            _stream(f'  {_C.DIM}fuzz failures shown:{_C.RESET} {len(failures)}')
        _stream(_divider(self.agent_id))

    def on_feedback_unavailable(self, reason: str) -> None:
        label = _agent_label(self.agent_id)
        _stream(f'  {label} {_C.WARN}feedback unavailable: {reason}{_C.RESET}')

    def on_input(self, msg: dict) -> None:
        label = _agent_label(self.agent_id)
        method = msg.get('method', '?')
        msg_id = msg.get('id')
        params = msg.get('params', {})
        tag = f'{_C.BOLD}IN{_C.RESET}'
        id_str = f' {_C.MUTED}id={msg_id}{_C.RESET}' if msg_id is not None else ''
        detail = ''
        if method == 'tools/call':
            args = params.get('arguments', {})
            cmd = args.get('command', '?')
            detail = f' {_C.HEADER}{cmd}{_C.RESET}'
            raw = args.get('args')
            if raw:
                try:
                    parsed = json.loads(raw)
                    keys = list(parsed.keys())
                    if 'code' in parsed:
                        code_len = len(parsed['code'])
                        keys[keys.index('code')] = f'code({code_len}ch)'
                    detail += f' {_C.DIM}{{{', '.join(keys)}}}{_C.RESET}'
                except (json.JSONDecodeError, AttributeError):
                    if len(raw) > 60:
                        detail += f' {_C.DIM}{raw[:60]}...{_C.RESET}'
                    else:
                        detail += f' {_C.DIM}{raw}{_C.RESET}'
        _stream(f'  {label} {tag} {_C.INFO}{method}{_C.RESET}{detail}{id_str}')

    def on_output(self, msg: dict) -> None:
        label = _agent_label(self.agent_id)
        tag = f'{_C.BOLD}OUT{_C.RESET}'
        msg_id = msg.get('id')
        id_str = f' {_C.MUTED}id={msg_id}{_C.RESET}' if msg_id is not None else ''
        if 'error' in msg:
            err = msg['error']
            code = err.get('code', '?')
            emsg = err.get('message', '')[:80]
            _stream(f'  {label} {tag} {_C.ERR}error {code}: {emsg}{_C.RESET}{id_str}')
            return
        result = msg.get('result', {})
        content = result.get('content')
        if content and isinstance(content, list):
            is_error = result.get('isError', False)
            text = content[0].get('text', '') if content else ''
            try:
                inner = json.loads(text)
                if is_error:
                    err_msg = inner.get('error', '?')[:80]
                    err_code = inner.get('code', '?')
                    _stream(f'  {label} {tag} {_C.ERR}{err_code}: {err_msg}{_C.RESET}{id_str}')
                elif 'status' in inner:
                    status = inner['status']
                    color = _C.OK if status == 'accepted' else _C.WARN
                    extra = ''
                    if inner.get('ast_valid') is not None:
                        extra = f' ast={inner['ast_valid']}'
                    if inner.get('violations'):
                        extra += f' violations={len(inner['violations'])}'
                    if inner.get('warnings'):
                        extra += f' warnings={len(inner['warnings'])}'
                    _stream(f'  {label} {tag} {color}{status}{extra}{_C.RESET}{id_str}')
                elif 'task_id' in inner:
                    _stream(f'  {label} {tag} {_C.OK}task={inner['task_id']}{_C.RESET}{id_str}')
                elif 'round' in inner:
                    _stream(f'  {label} {tag} {_C.OK}feedback round={inner['round']}{_C.RESET}{id_str}')
                else:
                    keys = list(inner.keys())[:5]
                    _stream(f'  {label} {tag} {_C.INFO}{{{', '.join(keys)}}}{_C.RESET}{id_str}')
            except (json.JSONDecodeError, AttributeError):
                preview = text[:80] + ('...' if len(text) > 80 else '')
                _stream(f'  {label} {tag} {_C.INFO}{preview}{_C.RESET}{id_str}')
        elif 'protocolVersion' in result:
            _stream(f'  {label} {tag} {_C.OK}initialized v={result['protocolVersion']}{_C.RESET}{id_str}')
        elif 'tools' in result:
            names = [t['name'] for t in result['tools']]
            _stream(f'  {label} {tag} {_C.OK}tools={names}{_C.RESET}{id_str}')
        elif result == {}:
            _stream(f'  {label} {tag} {_C.DIM}pong{_C.RESET}{id_str}')
        else:
            keys = list(result.keys())[:5]
            _stream(f'  {label} {tag} {_C.INFO}{{{', '.join(keys)}}}{_C.RESET}{id_str}')

    def on_disconnect(self) -> None:
        label = _agent_label(self.agent_id)
        _stream('')
        _stream(f'  {label} {_C.DIM}disconnected{_C.RESET}')
        _stream('')
__all__ = ['_C', '_agent_color', '_agent_label', '_divider', '_code_preview', '_stream', 'ConsoleStreamer']
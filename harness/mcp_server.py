"""
JanusMask MCP Server — stdio-based JSON-RPC 2.0 MCP server.

Exposes a single tool `execute` that mediates all agent-harness interaction
for the dual-agent differential fuzzing code synthesis system.

Protocol: MCP over stdio (JSON-RPC 2.0).
Transport: Read newline-delimited JSON from stdin, write to stdout.
"""
from __future__ import annotations
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from harness.ast_enforcer import validate_code
from harness.session_namer import generate_submission_filename
from harness.session_namer import generate_feedback_filename
from harness.hooks.rpc import submit_code as rpc_submit_code
from harness.hooks.rpc import submit_plan_draft as rpc_submit_plan_draft
from harness.hooks.rpc import submit_reconciliation as rpc_submit_reconciliation
from harness.hooks.rpc import clarification as rpc_clarification
from harness.hooks.rpc import error_report as rpc_error_report
from harness.hooks.console import ConsoleStreamer
from harness.hooks.console import _C
from harness.hooks.console import _agent_color
from harness.hooks.console import _agent_label
from harness.hooks.console import _code_preview
from harness.hooks.console import _divider
from harness.hooks.console import _stream
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG, format='[janusmask-mcp %(levelname)s] %(message)s')
log = logging.getLogger('janusmask.mcp')
MCP_PROTOCOL_VERSION = '2024-11-05'
SERVER_NAME = 'janusmask'
SERVER_VERSION = '0.1.0'

def build_execute_tool(mode: str='synthesis') -> dict:
    commands = ['request_clarification', 'report_error']
    if mode == 'planning':
        commands.extend(['get_planning_brief', 'submit_plan_draft', 'submit_reconciliation_response'])
    else:
        commands.extend(['get_task', 'submit_code', 'get_feedback'])
    return {'name': 'execute', 'description': 'JanusMask execution proxy. Submit code, get tasks, report errors.', 'inputSchema': {'type': 'object', 'properties': {'command': {'type': 'string', 'enum': commands, 'description': 'The command to execute'}, 'args': {'type': 'string', 'description': "JSON-encoded arguments. For submit_plan_draft, MUST be a JSON object containing a 'tasks' array. For submit_code, MUST contain a 'code' string."}}, 'required': ['command']}}
EXECUTE_TOOL = build_execute_tool('synthesis')
VALID_COMMANDS = frozenset(EXECUTE_TOOL['inputSchema']['properties']['command']['enum'])

def _jsonrpc_response(id: Any, result: Any) -> dict:
    """Build a JSON-RPC 2.0 success response."""
    return {'jsonrpc': '2.0', 'id': id, 'result': result}

def _jsonrpc_error(id: Any, code: int, message: str, data: Any=None) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    err: dict[str, Any] = {'code': code, 'message': message}
    if data is not None:
        err['data'] = data
    return {'jsonrpc': '2.0', 'id': id, 'error': err}
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

def _read_json_file(path: Path) -> dict:
    """Read and parse a JSON file, raising FileNotFoundError or ValueError."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _write_json_file(path: Path, data: Any) -> None:
    """Atomically write JSON to a file (create parent dirs as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')
    tmp.rename(path)

class JanusMaskServer:
    """MCP server that exposes the ``execute`` tool for a single agent."""
    MAX_SUBMISSIONS = 5
    MAX_CLARIFICATIONS = 2

    def __init__(self, agent_id: str, state_dir: Path) -> None:
        if agent_id not in ('claude', 'gemini', 'antigravity'):
            raise ValueError(f"Invalid agent_id: {agent_id!r}. Must be 'claude', 'gemini' or 'antigravity'.")
        self.agent_id: str = agent_id
        self.state_dir: Path = state_dir
        self.session_id: str = str(uuid.uuid4())
        self.task_read: bool = False
        self.submissions: int = 0
        self.clarifications: int = 0
        self._initialized: bool = False
        self.mode: str = os.environ.get('JANUSMASK_MODE', 'synthesis')
        self.plan_submitted: bool = False
        self.reconciliation_submitted: bool = False
        self._console = ConsoleStreamer(self.agent_id, self.session_id)
        self._console.on_connect()
        log.info('Server created: agent=%s state_dir=%s session=%s', self.agent_id, self.state_dir, self.session_id)

    def _read_state(self) -> dict:
        """Read the global STATE.json.  Returns empty dict on missing file."""
        state_path = self.state_dir / 'STATE.json'
        try:
            return _read_json_file(state_path)
        except FileNotFoundError:
            log.warning('STATE.json not found at %s', state_path)
            return {}
        except (json.JSONDecodeError, ValueError) as exc:
            log.error('Corrupt STATE.json: %s', exc)
            return {}

    def _current_round(self) -> int:
        """Return the current round number. Prefers JANUSMASK_ROUND env, falls back to STATE.json (default 1)."""
        env_round = os.environ.get('JANUSMASK_ROUND')
        if env_round and env_round.isdigit():
            return int(env_round)
        return int(self._read_state().get('round', 1))

    def _current_phase(self) -> str:
        """Return the current phase from STATE.json (default 'synthesis')."""
        return str(self._read_state().get('phase', 'synthesis'))

    def _inject_locked_fields(self, args: dict) -> dict:
        """Inject harness-controlled fields into the parsed args dict.

        These fields override anything the agent may have supplied.
        """
        args['session_id'] = self.session_id
        args['agent_identity'] = self.agent_id
        args['round_number'] = self._current_round()
        args['timestamp'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        return args

    def _dispatch(self, command: str, raw_args: str | None) -> dict:
        """Parse args, inject locked fields, and dispatch to the command handler."""
        parsed_args: dict = {}
        if raw_args is not None and raw_args != '':
            try:
                parsed_args = json.loads(raw_args)
                if not isinstance(parsed_args, dict):
                    return {'error': 'args must be a JSON object', 'code': 'invalid_args'}
            except json.JSONDecodeError as exc:
                return {'error': f'Malformed JSON in args: {exc}', 'code': 'invalid_args'}
        parsed_args = self._inject_locked_fields(parsed_args)
        mode_schema = build_execute_tool(self.mode)
        valid_commands = frozenset(mode_schema['inputSchema']['properties']['command']['enum'])
        if command not in valid_commands:
            return {'error': f'Command {command!r} is not valid in {self.mode} mode.', 'code': 'wrong_mode'}
        if self.mode == 'planning':
            if command != 'get_planning_brief' and (not self.task_read):
                return {'error': 'You must call get_planning_brief before any other command.', 'code': 'task_not_read'}
        elif command not in ('get_task', 'get_feedback') and (not self.task_read):
            return {'error': 'You must call get_task before any other command.', 'code': 'task_not_read'}
        handler = {'get_task': self.cmd_get_task, 'submit_code': self.cmd_submit_code, 'request_clarification': self.cmd_request_clarification, 'report_error': self.cmd_report_error, 'get_feedback': self.cmd_get_feedback, 'get_planning_brief': self.cmd_get_planning_brief, 'submit_plan_draft': self.cmd_submit_plan_draft, 'submit_reconciliation_response': self.cmd_submit_reconciliation_response}.get(command)
        return handler(parsed_args)

    def cmd_get_task(self, args: dict) -> dict:
        """Read the current task specification and set the inbox gate."""
        task_id = os.environ.get('JANUSMASK_TASK_ID')
        task_path = None
        if task_id:
            tasks_dir = self.state_dir / 'tasks'
            matches = list(tasks_dir.glob(f'*{task_id}.json.processing'))
            if matches:
                task_path = matches[0]
        if task_path is None:
            task_path = task_paths.current_task_spec_path(self.state_dir, task_id or 'default')
        if task_path is None or not task_path.is_file():
            return {'error': 'No current task found.', 'code': 'no_task'}
        try:
            task = _read_json_file(task_path)
        except (json.JSONDecodeError, ValueError) as exc:
            return {'error': f'Corrupt task file: {exc}', 'code': 'corrupt_task'}
        depends_on = task.get('dependencies', task.get('depends_on', []))
        if depends_on:
            injected_code_blocks = []
            for dep_id in depends_on:
                dep_code_path = self.state_dir / 'output' / f'{dep_id}.py'
                if dep_code_path.exists():
                    try:
                        dep_code = dep_code_path.read_text(encoding='utf-8')
                        injected_code_blocks.append(f'--- DEPENDENCY: {dep_id} ---\n{dep_code}\n-----------------------------')
                    except Exception as e:
                        log.warning(f'Failed to read dependency code for {dep_id}: {e}')
            if injected_code_blocks:
                task['specification'] = task.get('specification', '') + '\n\n' + '\n\n'.join(injected_code_blocks)
        self.task_read = True
        self._console.on_task_read(task)
        log.info('Agent %s read task: %s', self.agent_id, task.get('task_id', 'unknown'))
        return task

    def cmd_submit_code(self, args: dict) -> dict:
        """Accept a code submission from the agent.

        Delegates validation + persistence + response shapes to
        harness.hooks.rpc.submit_code (HOOK-11). Counter, console, and task
        constraint lookup remain caller-side so this module stays the sole
        owner of per-session state.
        """
        if self.submissions >= self.MAX_SUBMISSIONS:
            self._console.on_submit_rate_limited(self.MAX_SUBMISSIONS)
            return {'error': f'Maximum submissions ({self.MAX_SUBMISSIONS}) reached for this round.', 'code': 'max_submissions'}
        code = args.get('code')
        if not code or not isinstance(code, str):
            return {'error': "submit_code requires a non-empty 'code' string in args.", 'code': 'missing_field'}
        allow_nondet = False
        synthesis_target_type = ''
        task_id_env = os.environ.get('JANUSMASK_TASK_ID')
        task_path = None
        if task_id_env:
            candidates = list((self.state_dir / 'tasks').glob(f'*{task_id_env}.json.processing'))
            if candidates:
                task_path = candidates[0]
        if task_path is None or not task_path.is_file():
            task_path = task_paths.current_task_spec_path(self.state_dir, task_id_env or 'default')
        task: dict = {}
        try:
            task = _read_json_file(task_path)
            allow_nondet = task.get('constraints', {}).get('deterministic') is False
            synthesis_target_type = str(task.get('synthesis_target_type', '') or '')
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        from harness.hooks.rpc import submit_code as rpc_submit_code
        from harness.paths import relax_external_for
        # REV23 §1b: external-target submissions get the same eval/exec/__import__
        # relax as the _decide_common / _validate_submission paths, via the shared
        # predicate, so the MCP submit path cannot diverge (target-file containment
        # keeps JM-tree targets strict; fail-closed when unresolvable).
        relax_external = relax_external_for(task, content=code)
        violations: list = []
        try:
            violations = rpc_submit_code.validate(code, allow_nondeterminism=allow_nondet, relax_external_constructs=relax_external)
        except Exception:
            log.exception('AST validation error for %s', self.agent_id)
            violations = []
        errors = [v for v in violations if v.severity == 'error']
        if errors:
            payload = rpc_submit_code.rejected_payload(errors)
            self._console.on_submit_rejected(code, payload['violations'])
            rpc_submit_code.emit_ast_rejection(agent=self.agent_id, task_id=task_id_env or '', synthesis_target_type=synthesis_target_type, state_dir=self.state_dir)
            log.warning('Agent %s submission rejected: %d AST errors', self.agent_id, len(errors))
            return payload
        self.submissions += 1
        args['explanation'] = args.get('explanation', '')
        try:
            record = rpc_submit_code.build_record(args, submission_number=self.submissions)
        except rpc_submit_code.SchemaError as exc:
            self.submissions -= 1
            return {'error': str(exc), 'code': 'missing_field'}
        task_id_for_name = os.environ.get('JANUSMASK_TASK_ID', 'default')
        rpc_submit_code.persist(record, state_dir=self.state_dir, agent=self.agent_id, task_id=task_id_for_name)
        rpc_submit_code.emit_clean_success(agent=self.agent_id, task_id=task_id_env or '', synthesis_target_type=synthesis_target_type, state_dir=self.state_dir)
        warning_dicts = rpc_submit_code.warnings_from_violations(violations)
        round_number = record['round_number']
        self._console.on_submit_accepted(code, self.submissions, self.MAX_SUBMISSIONS, round_number, warning_dicts)
        log.info('Agent %s submitted code (submission %d/%d, round %d)', self.agent_id, self.submissions, self.MAX_SUBMISSIONS, round_number)
        return rpc_submit_code.accepted_payload(warning_dicts)

    def cmd_request_clarification(self, args: dict) -> dict:
        """Record a clarification request from the agent (delegates to rpc)."""
        if self.clarifications >= self.MAX_CLARIFICATIONS:
            return {'error': f'Maximum clarification requests ({self.MAX_CLARIFICATIONS}) reached.', 'code': 'max_clarifications'}
        self.clarifications += 1
        try:
            record = rpc_clarification.build_record(args, clarification_number=self.clarifications)
        except rpc_clarification.SchemaError as exc:
            self.clarifications -= 1
            return {'error': str(exc), 'code': 'missing_field'}
        rpc_clarification.persist(record, state_dir=self.state_dir, agent=self.agent_id, clarification_number=self.clarifications)
        remaining = self.MAX_CLARIFICATIONS - self.clarifications
        self._console.on_clarification(record['question'], self.clarifications, remaining)
        log.info('Agent %s requested clarification (%d/%d)', self.agent_id, self.clarifications, self.MAX_CLARIFICATIONS)
        return rpc_clarification.accepted_payload(self.clarifications, remaining)

    def cmd_report_error(self, args: dict) -> dict:
        """Record an error report from the agent (delegates to rpc)."""
        try:
            record = rpc_error_report.build_record(args)
        except rpc_error_report.SchemaError as exc:
            return {'error': str(exc), 'code': 'missing_field'}
        rpc_error_report.persist(record, state_dir=self.state_dir, agent=self.agent_id)
        self._console.on_error_report(record['error'])
        log.info('Agent %s reported error: %s', self.agent_id, record['error'][:120])
        return rpc_error_report.accepted_payload()

    def cmd_get_feedback(self, args: dict) -> dict:
        """Return cross-examination feedback for this agent."""
        phase = self._current_phase()
        if phase != 'cross_examination':
            self._console.on_feedback_unavailable(f'wrong phase ({phase!r}, need cross_examination)')
            return {'error': f'get_feedback is only available during cross_examination phase (current phase: {phase!r}).', 'code': 'wrong_phase'}
        task_id = os.environ.get('JANUSMASK_TASK_ID', '')
        round_number = self._current_round()
        feedback_path = self.state_dir / 'sessions' / generate_feedback_filename(self.agent_id, round_number, task_id)
        try:
            feedback = _read_json_file(feedback_path)
        except FileNotFoundError:
            self._console.on_feedback_unavailable('no feedback file yet')
            return {'error': 'No feedback available yet.', 'code': 'no_feedback'}
        except (json.JSONDecodeError, ValueError) as exc:
            self._console.on_feedback_unavailable(f'corrupt file: {exc}')
            return {'error': f'Corrupt feedback file: {exc}', 'code': 'corrupt_feedback'}
        self.task_read = True
        self._console.on_feedback_retrieved(feedback)
        log.info('Agent %s retrieved feedback', self.agent_id)
        return feedback

    def cmd_get_planning_brief(self, args: dict) -> dict:
        diff_path = self.state_dir / 'planning' / 'current_diff.json'
        try:
            diff = _read_json_file(diff_path)
            self.task_read = True
            log.info('Agent %s read current diff for reconciliation', self.agent_id)
            summary_items = []
            for item in diff.get('items', []):
                c_task = item.get('claude_task') or {}
                g_task = item.get('gemini_task') or {}
                title = c_task.get('title') or g_task.get('title') or 'Unknown Task'
                task_id = c_task.get('task_id') or g_task.get('task_id') or 'Unknown ID'
                summary_items.append({'diff_item_id': item.get('diff_item_id'), 'kind': item.get('kind'), 'task_id': task_id, 'title': title, 'field_divergences': item.get('field_divergences', []), 'match_reason': item.get('match_reason')})
            return {'note': 'This is a summarized diff. Use read_file or grep_search on current_diff.json for full details.', 'items': summary_items}
        except FileNotFoundError:
            pass
        brief_path = self.state_dir / 'planning' / 'brief.json'
        try:
            brief = _read_json_file(brief_path)
        except FileNotFoundError:
            return {'error': 'No planning brief found.', 'code': 'no_brief'}
        self.task_read = True
        log.info('Agent %s read planning brief', self.agent_id)
        return brief

    def cmd_submit_plan_draft(self, args: dict) -> dict:
        if self.plan_submitted:
            return {'error': 'Already submitted plan draft.', 'code': 'already_submitted'}
        violations = rpc_submit_plan_draft.validate(args)
        if violations:
            return rpc_submit_plan_draft.rejected_payload(violations)
        self.plan_submitted = True
        rpc_submit_plan_draft.persist(args, state_dir=self.state_dir, agent=self.agent_id)
        _stream(f'  {_C.HEADER}[PLAN]{_C.RESET} {_agent_label(self.agent_id)} submitted plan draft')
        return rpc_submit_plan_draft.accepted_payload()

    def cmd_submit_reconciliation_response(self, args: dict) -> dict:
        if self.reconciliation_submitted:
            return {'error': 'Already submitted reconciliation response.', 'code': 'already_submitted'}
        responses = args.get('responses', [])
        valid_ids = rpc_submit_reconciliation.load_valid_diff_ids(self.state_dir)
        err = rpc_submit_reconciliation.validate_responses(responses, valid_ids=valid_ids)
        if err is not None:
            if err.startswith('Unknown diff item'):
                return {'error': err, 'code': 'unknown_diff_item'}
            if err.startswith('Unknown stance'):
                return {'error': err, 'code': 'missing_field'}
            return {'error': err, 'code': 'invalid_args'}
        self.reconciliation_submitted = True
        rpc_submit_reconciliation.persist(args, state_dir=self.state_dir, agent=self.agent_id)
        _stream(f'  {_C.HEADER}[PLAN]{_C.RESET} {_agent_label(self.agent_id)} submitted reconciliation response')
        return rpc_submit_reconciliation.accepted_payload()

    def handle_initialize(self, params: dict) -> dict:
        """Handle the MCP ``initialize`` request."""
        self._initialized = True
        log.info('MCP initialize from client: %s', params.get('clientInfo', {}).get('name', 'unknown'))
        return {'protocolVersion': MCP_PROTOCOL_VERSION, 'capabilities': {'tools': {}}, 'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION}}

    def handle_initialized(self, _params: dict) -> None:
        """Handle the MCP ``notifications/initialized`` notification (no response)."""
        log.info('MCP initialized notification received')

    def handle_tools_list(self, _params: dict) -> dict:
        """Handle ``tools/list`` — return the single execute tool."""
        return {'tools': [build_execute_tool(self.mode)]}

    def handle_tools_call(self, params: dict) -> dict:
        """Handle ``tools/call`` — dispatch the execute tool invocation."""
        tool_name = params.get('name')
        if tool_name != 'execute':
            return {'content': [{'type': 'text', 'text': json.dumps({'error': f'Unknown tool: {tool_name!r}', 'code': 'unknown_tool'})}], 'isError': True}
        arguments = params.get('arguments', {})
        command = arguments.get('command')
        raw_args = arguments.get('args')
        result = self._dispatch(command, raw_args)
        is_error = isinstance(result, dict) and 'error' in result
        return {'content': [{'type': 'text', 'text': json.dumps(result, indent=2, ensure_ascii=False)}], 'isError': is_error}

    def handle_message(self, msg: dict) -> dict | None:
        """Route an incoming JSON-RPC message to the appropriate handler.

        Returns a JSON-RPC response dict, or None for notifications.
        """
        method = msg.get('method')
        params = msg.get('params', {})
        msg_id = msg.get('id')
        if msg_id is None:
            if method == 'notifications/initialized':
                self.handle_initialized(params)
            elif method == 'notifications/cancelled':
                log.info('Received cancellation notification')
            else:
                log.debug('Ignoring notification: %s', method)
            return None
        try:
            if method == 'initialize':
                result = self.handle_initialize(params)
            elif method == 'tools/list':
                result = self.handle_tools_list(params)
            elif method == 'tools/call':
                result = self.handle_tools_call(params)
            elif method == 'ping':
                result = {}
            else:
                return _jsonrpc_error(msg_id, METHOD_NOT_FOUND, f'Method not found: {method!r}')
            return _jsonrpc_response(msg_id, result)
        except Exception as exc:
            log.exception('Internal error handling %s', method)
            return _jsonrpc_error(msg_id, INTERNAL_ERROR, f'Internal server error: {exc}')

    def run(self) -> None:
        """Run the stdio JSON-RPC event loop.

        Reads newline-delimited JSON from stdin, writes responses to stdout.
        """
        log.info('Starting stdio event loop for agent=%s', self.agent_id)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                response = _jsonrpc_error(None, PARSE_ERROR, f'Parse error: {exc}')
                self._send(response)
                continue
            if not isinstance(msg, dict):
                response = _jsonrpc_error(None, INVALID_REQUEST, 'Request must be a JSON object')
                self._send(response)
                continue
            self._console.on_input(msg)
            log.debug('Received: method=%s id=%s', msg.get('method'), msg.get('id'))
            response = self.handle_message(msg)
            if response is not None:
                self._console.on_output(response)
                self._send(response)
        self._console.on_disconnect()
        log.info('stdin closed, shutting down')

    @staticmethod
    def _send(msg: dict) -> None:
        """Write a JSON-RPC message to stdout."""
        payload = json.dumps(msg, ensure_ascii=False)
        sys.stdout.write(payload + '\n')
        sys.stdout.flush()

def main() -> None:
    agent_id = os.environ.get('JANUSMASK_AGENT')
    if not agent_id:
        print("Error: JANUSMASK_AGENT environment variable not set. Must be 'claude' or 'gemini'.", file=sys.stderr)
        sys.exit(1)
    state_dir_str = os.environ.get('JANUSMASK_STATE_DIR')
    if not state_dir_str:
        print('Error: JANUSMASK_STATE_DIR environment variable not set.', file=sys.stderr)
        sys.exit(1)
    state_dir = Path(state_dir_str)
    if not state_dir.is_dir():
        log.warning('State directory does not exist yet: %s (will be created on first write)', state_dir)
    try:
        server = JanusMaskServer(agent_id=agent_id, state_dir=state_dir)
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
    server.run()
from harness import task_paths
"R-PROMOTE-7: route MCP server fallbacks through harness.task_paths.\n\nEliminates the bare ``state/tasks/current_task.json`` fallback in\n``cmd_get_task`` and ``cmd_submit_code`` by routing through the per-task\nspec helper added in AW10a (commit b408b18). Closes the parallel miss\nbetween the AW10c six-site orchestrator patch and the MCP server's two\nfallback sites surfaced as R-PROMOTE-7 in session #20.\n"
if __name__ == '__main__':
    main()
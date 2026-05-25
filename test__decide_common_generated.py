# ----- format_ast_reason -----
import pytest
from harness.hooks._decide_common import format_ast_reason

def test_format_ast_reason_with_error_only():
    payload = {"error": "Specific error message"}
    result = format_ast_reason(payload)
    assert result == "Specific error message"

def test_format_ast_reason_with_message_only():
    payload = {"message": "General message"}
    result = format_ast_reason(payload)
    assert result == "General message"

def test_format_ast_reason_with_default_header():
    payload = {}
    result = format_ast_reason(payload)
    assert result == "AST validation failed."

def test_format_ast_reason_prefers_error_over_message():
    payload = {"error": "Primary error", "message": "Secondary message"}
    result = format_ast_reason(payload)
    assert result == "Primary error"

def test_format_ast_reason_empty_error_falls_back_to_message():
    payload = {"error": "", "message": "Fallback message"}
    result = format_ast_reason(payload)
    assert result == "Fallback message"

def test_format_ast_reason_empty_violations_list():
    payload = {"error": "Base error", "violations": []}
    result = format_ast_reason(payload)
    assert result == "Base error"

def test_format_ast_reason_with_single_violation():
    payload = {
        "error": "Syntax issue",
        "violations": [
            {"line": 42, "rule": "W0101", "message": "Unreachable code"}
        ]
    }
    result = format_ast_reason(payload)
    assert result == "Syntax issue\n- L42: [W0101] Unreachable code"

def test_format_ast_reason_with_multiple_violations():
    payload = {
        "violations": [
            {"line": 10, "rule": "E1", "message": "First error"},
            {"line": 20, "rule": "E2", "message": "Second error"}
        ]
    }
    result = format_ast_reason(payload)
    expected = (
        "AST validation failed.\n"
        "- L10: [E1] First error\n"
        "- L20: [E2] Second error"
    )
    assert result == expected


# ----- format_plan_reason -----
from harness.hooks._decide_common import format_plan_reason

def test_format_plan_reason_empty_payload():
    """Test format_plan_reason with an empty payload falls back to defaults."""
    payload = {}
    result = format_plan_reason(payload)
    assert result == "plan_draft validation failed."

def test_format_plan_reason_with_error_only():
    """Test format_plan_reason uses the provided error string if there are no violations."""
    payload = {"error": "Custom validation error."}
    result = format_plan_reason(payload)
    assert result == "Custom validation error."

def test_format_plan_reason_with_violations_only():
    """Test format_plan_reason formats a single violation with the default header."""
    payload = {
        "violations": [
            {"code": "MISSING_FIELD", "path": "tasks[0]", "message": "field is required"}
        ]
    }
    result = format_plan_reason(payload)
    expected = "plan_draft validation failed.\n- [MISSING_FIELD] tasks[0]: field is required"
    assert result == expected

def test_format_plan_reason_with_error_and_multiple_violations():
    """Test format_plan_reason combines a custom error header with multiple formatted violations."""
    payload = {
        "error": "Failed to parse plan draft.",
        "violations": [
            {"code": "V01", "path": "task1", "message": "missing description"},
            {"code": "V02", "path": "task2", "message": "invalid status"}
        ]
    }
    result = format_plan_reason(payload)
    expected = (
        "Failed to parse plan draft.\n"
        "- [V01] task1: missing description\n"
        "- [V02] task2: invalid status"
    )
    assert result == expected


# ----- decide_submission -----
import pytest
from unittest.mock import Mock, patch
from harness.hooks import _decide_common
from harness.hooks._decide_common import decide_submission

class MockContext:
    def __init__(self):
        self.agent = "test_agent"
        self.journal_calls = []

    def journal(self, action, outcome, detail=None):
        self.journal_calls.append((action, outcome, detail))

    def allow_with_warnings(self, warnings):
        return {"status": "allow_with_warnings", "warnings": warnings}

@pytest.fixture
def mock_deps():
    with patch('harness.hooks._decide_common._ledger', create=True) as ledger_mock, \
         patch('harness.hooks._decide_common._state_gates', create=True) as gates_mock, \
         patch('harness.hooks._decide_common._paths', create=True) as paths_mock, \
         patch('harness.hooks._decide_common._common', create=True) as common_mock, \
         patch('harness.hooks._decide_common.rpc_submit_code', create=True) as rpc_mock, \
         patch('harness.hooks._decide_common.MAX_VIOLATIONS', 10, create=True), \
         patch('harness.hooks._decide_common.format_ast_reason', create=True) as format_mock:
         
        ledger_mock.count_verb.return_value = 0
        gates_mock.MAX_SUBMISSIONS = 5
        paths_mock.load_inbox_task.return_value = {'files_touched': ['test.py']}
        common_mock.decision_payload.side_effect = lambda status, **kw: {'status': status, **kw}
        paths_mock.state_dir.return_value = "/state"
        
        rpc_mock.validate.return_value = []
        rpc_mock.warnings_from_violations.return_value = []
        rpc_mock.rejected_payload.return_value = "rejected"
        format_mock.return_value = "formatted"
             
        yield {
            'ledger': ledger_mock,
            'gates': gates_mock,
            'paths': paths_mock,
            'common': common_mock,
            'rpc': rpc_mock,
            'format': format_mock
        }

def test_decide_submission_rate_limit(mock_deps):
    mock_deps['ledger'].count_verb.return_value = 5
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'deny'
    assert 'Submission rate limit reached' in res['reason']
    assert ctx.journal_calls[0] == ('submit_code', 'rate_limited', {'reason': 'Submission rate limit reached (5/5).', 'counters': {'submissions': 5}})

def test_decide_submission_non_py_target(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {'files_touched': ['test.txt'], 'task_id': 't1'}
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'allow'
    assert ctx.journal_calls[0] == ('submit_code', 'allow', {'reason': 'non-py target', 'task_id': 't1'})

def test_decide_submission_empty_files_touched(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {'files_touched': []}
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    mock_deps['rpc'].validate.assert_called_once()
    assert res['status'] == 'allow'

def test_decide_submission_non_string_file_touched(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {'files_touched': [123]}
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    mock_deps['rpc'].validate.assert_called_once()
    assert res['status'] == 'allow'

def test_decide_submission_nondeterminism_via_constraints(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {
        'files_touched': ['test.py'],
        'constraints': {'deterministic': False}
    }
    
    ctx = MockContext()
    decide_submission(ctx, "content", [], "inbox")
    mock_deps['rpc'].validate.assert_called_once_with("content", allow_nondeterminism=True)

def test_decide_submission_nondeterminism_via_mtt(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {
        'files_touched': ['test.py'],
        'meta_task_type': 'io_adapter'
    }
    
    ctx = MockContext()
    decide_submission(ctx, "content", [], "inbox")
    mock_deps['rpc'].validate.assert_called_once_with("content", allow_nondeterminism=True)

def test_decide_submission_nondeterminism_via_mtt_prefix(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {
        'files_touched': ['test.py'],
        'meta_task_type': 'test_feature'
    }
    
    ctx = MockContext()
    decide_submission(ctx, "content", [], "inbox")
    mock_deps['rpc'].validate.assert_called_once_with("content", allow_nondeterminism=True)
    
def test_decide_submission_nondeterminism_via_mtt_in_constraints(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {
        'files_touched': ['test.py'],
        'constraints': {'meta_task_type': 'logging_observability'}
    }
    
    ctx = MockContext()
    decide_submission(ctx, "content", [], "inbox")
    mock_deps['rpc'].validate.assert_called_once_with("content", allow_nondeterminism=True)

def test_decide_submission_nondeterminism_false(mock_deps):
    mock_deps['paths'].load_inbox_task.return_value = {
        'files_touched': ['test.py'],
        'meta_task_type': 'regular_feature'
    }
    
    ctx = MockContext()
    decide_submission(ctx, "content", [], "inbox")
    mock_deps['rpc'].validate.assert_called_once_with("content", allow_nondeterminism=False)

def test_decide_submission_errors_rejected(mock_deps):
    class Violation:
        severity = 'error'
    
    mock_deps['rpc'].validate.return_value = [Violation(), Violation()]
    mock_deps['paths'].load_inbox_task.return_value = {'files_touched': ['test.py'], 'task_id': 't2', 'synthesis_target_type': 'stt'}
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'deny'
    assert res['reason'] == 'formatted'
    assert len(ctx.journal_calls) == 1
    assert ctx.journal_calls[0] == ('submit_code', 'deny', {'error_count': 2, 'truncated': False, 'task_id': 't2'})
    
    mock_deps['rpc'].emit_ast_rejection.assert_called_once_with(agent="test_agent", task_id="t2", synthesis_target_type="stt", state_dir="/state")

def test_decide_submission_errors_truncated(mock_deps):
    class Violation:
        severity = 'error'
    
    mock_deps['rpc'].validate.return_value = [Violation()] * 11
    mock_deps['paths'].load_inbox_task.return_value = {'files_touched': ['test.py'], 'task_id': 't2'}
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'deny'
    assert res['reason'] == 'formatted'
    assert len(ctx.journal_calls) == 1
    assert ctx.journal_calls[0] == ('submit_code', 'deny', {'error_count': 11, 'truncated': True, 'task_id': 't2'})

def test_decide_submission_warnings(mock_deps):
    class WarningViolation:
        severity = 'warning'
        
    mock_deps['rpc'].validate.return_value = [WarningViolation()]
    mock_deps['rpc'].warnings_from_violations.return_value = ["warning1"]
    
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'allow_with_warnings'
    assert res['warnings'] == ["warning1"]

def test_decide_submission_valid(mock_deps):
    ctx = MockContext()
    res = decide_submission(ctx, "content", [], "inbox")
    
    assert res['status'] == 'allow'
    assert len(ctx.journal_calls) == 0


# ----- decide_plan_draft -----
import json
from unittest.mock import patch

from harness.hooks._decide_common import decide_plan_draft


class MockPlanContext:
    def __init__(self):
        self.journal_calls = []

    def journal(self, verb, outcome, detail=None):
        self.journal_calls.append((verb, outcome, detail))


def test_decide_plan_draft_already_submitted():
    ctx = MockPlanContext()
    events = [{'some': 'event'}]
    with patch('harness.hooks._decide_common._ledger.has_verb', return_value=True) as mock_has_verb, \
         patch('harness.hooks._decide_common._common.decision_payload', return_value={'mocked': 'decision'}) as mock_decision:
        
        result = decide_plan_draft(ctx, '{"valid": "json"}', events)
        
        mock_has_verb.assert_called_once_with(events, 'plan_draft', outcome='allow')
        assert len(ctx.journal_calls) == 1
        assert ctx.journal_calls[0] == ('plan_draft', 'deny', {'reason': 'plan_draft already submitted (single-shot per round).'})
        
        mock_decision.assert_called_once_with('deny', reason='plan_draft already submitted (single-shot per round).')
        assert result == {'mocked': 'decision'}


def test_decide_plan_draft_invalid_json():
    ctx = MockPlanContext()
    events = []
    with patch('harness.hooks._decide_common._ledger.has_verb', return_value=False), \
         patch('harness.hooks._decide_common._common.decision_payload', return_value={'mocked': 'decision'}) as mock_decision:
        
        result = decide_plan_draft(ctx, 'not valid json', events)
        
        assert len(ctx.journal_calls) == 1
        assert ctx.journal_calls[0][0] == 'plan_draft'
        assert ctx.journal_calls[0][1] == 'invalid'
        assert 'plan_draft content must be valid JSON:' in ctx.journal_calls[0][2]['reason']
        
        mock_decision.assert_called_once()
        assert mock_decision.call_args[0][0] == 'deny'
        assert 'plan_draft content must be valid JSON:' in mock_decision.call_args[1]['reason']
        assert result == {'mocked': 'decision'}


def test_decide_plan_draft_validation_fails():
    ctx = MockPlanContext()
    events = []
    content = '{"key": "value"}'
    with patch('harness.hooks._decide_common._ledger.has_verb', return_value=False), \
         patch('harness.hooks._decide_common._common.decision_payload', return_value={'mocked': 'decision'}) as mock_decision, \
         patch('harness.hooks._decide_common.rpc_submit_plan_draft.validate', return_value=['v1', 'v2']) as mock_validate, \
         patch('harness.hooks._decide_common.rpc_submit_plan_draft.rejected_payload', return_value={'error': 'rejected'}) as mock_rejected, \
         patch('harness.hooks._decide_common.format_plan_reason', return_value='formatted reason') as mock_format:
        
        result = decide_plan_draft(ctx, content, events)
        
        mock_validate.assert_called_once_with({'key': 'value'})
        mock_rejected.assert_called_once()
        assert mock_rejected.call_args[0][0] == ['v1', 'v2']
        assert 'max_show' in mock_rejected.call_args[1]
        mock_format.assert_called_once_with({'error': 'rejected'})
        
        assert len(ctx.journal_calls) == 1
        assert ctx.journal_calls[0] == ('plan_draft', 'deny', {'violation_count': 2})
        
        mock_decision.assert_called_once_with('deny', reason='formatted reason')
        assert result == {'mocked': 'decision'}


def test_decide_plan_draft_success():
    ctx = MockPlanContext()
    events = []
    content = '{"key": "value"}'
    with patch('harness.hooks._decide_common._ledger.has_verb', return_value=False), \
         patch('harness.hooks._decide_common._common.decision_payload', return_value={'mocked': 'decision'}) as mock_decision, \
         patch('harness.hooks._decide_common.rpc_submit_plan_draft.validate', return_value=[]) as mock_validate:
        
        result = decide_plan_draft(ctx, content, events)
        
        mock_validate.assert_called_once_with({'key': 'value'})
        assert len(ctx.journal_calls) == 0
        
        mock_decision.assert_called_once_with('allow')
        assert result == {'mocked': 'decision'}


# ----- decide_reconciliation -----
import pytest
import json
from unittest.mock import patch, MagicMock
from harness.hooks._decide_common import decide_reconciliation

class DummyContext:
    def __init__(self):
        self.journals = []
    
    def journal(self, verb, outcome, detail=None):
        self.journals.append((verb, outcome, detail))

@pytest.fixture
def mocks():
    with patch('harness.hooks._decide_common._ledger.has_verb') as m_has_verb, \
         patch('harness.hooks._decide_common._paths.state_dir') as m_state_dir, \
         patch('harness.hooks._decide_common.rpc_submit_reconciliation.load_valid_diff_ids') as m_load_valid, \
         patch('harness.hooks._decide_common.rpc_submit_reconciliation.validate_responses') as m_validate, \
         patch('harness.hooks._decide_common._common.decision_payload') as m_payload:
        
        m_payload.side_effect = lambda outcome, reason=None: {"outcome": outcome, "reason": reason} if reason is not None else {"outcome": outcome}
        yield {
            'has_verb': m_has_verb,
            'state_dir': m_state_dir,
            'load_valid': m_load_valid,
            'validate': m_validate,
            'payload': m_payload,
        }

def test_decide_reconciliation_already_submitted(mocks):
    mocks['has_verb'].return_value = True
    ctx = DummyContext()
    events = [{'some': 'event'}]
    
    result = decide_reconciliation(ctx, "{}", events)
    
    mocks['has_verb'].assert_called_once_with(events, 'reconciliation', outcome='allow')
    assert result == {"outcome": "deny", "reason": "reconciliation already submitted (single-shot per round)."}
    assert len(ctx.journals) == 1
    assert ctx.journals[0] == ('reconciliation', 'deny', {'reason': 'reconciliation already submitted (single-shot per round).'})

def test_decide_reconciliation_invalid_json(mocks):
    mocks['has_verb'].return_value = False
    ctx = DummyContext()
    events = []
    
    result = decide_reconciliation(ctx, "{invalid_json", events)
    
    assert result['outcome'] == 'deny'
    assert 'reconciliation content must be valid JSON' in result['reason']
    assert len(ctx.journals) == 1
    assert ctx.journals[0][0] == 'reconciliation'
    assert ctx.journals[0][1] == 'invalid'
    assert 'reconciliation content must be valid JSON' in ctx.journals[0][2]['reason']

def test_decide_reconciliation_validation_error(mocks):
    mocks['has_verb'].return_value = False
    mocks['state_dir'].return_value = '/mock/state/dir'
    mocks['load_valid'].return_value = ['diff-1', 'diff-2']
    mocks['validate'].return_value = "Some validation error message."
    
    ctx = DummyContext()
    events = []
    content = json.dumps({"responses": [{"id": "diff-3", "action": "accept"}]})
    
    result = decide_reconciliation(ctx, content, events)
    
    mocks['load_valid'].assert_called_once_with('/mock/state/dir')
    mocks['validate'].assert_called_once_with([{"id": "diff-3", "action": "accept"}], valid_ids=['diff-1', 'diff-2'])
    
    assert result == {"outcome": "deny", "reason": "Some validation error message."}
    assert len(ctx.journals) == 1
    assert ctx.journals[0] == ('reconciliation', 'deny', {'reason': 'Some validation error message.'})

def test_decide_reconciliation_allow(mocks):
    mocks['has_verb'].return_value = False
    mocks['state_dir'].return_value = '/mock/state/dir'
    mocks['load_valid'].return_value = ['diff-1']
    mocks['validate'].return_value = None
    
    ctx = DummyContext()
    events = []
    content = json.dumps({"responses": [{"id": "diff-1", "action": "accept"}]})
    
    result = decide_reconciliation(ctx, content, events)
    
    mocks['validate'].assert_called_once_with([{"id": "diff-1", "action": "accept"}], valid_ids=['diff-1'])
    assert result == {"outcome": "allow"}
    assert len(ctx.journals) == 0

def test_decide_reconciliation_missing_responses_key(mocks):
    mocks['has_verb'].return_value = False
    mocks['state_dir'].return_value = '/mock/state/dir'
    mocks['load_valid'].return_value = []
    mocks['validate'].return_value = None
    
    ctx = DummyContext()
    events = []
    
    result = decide_reconciliation(ctx, "{}", events)
    
    mocks['validate'].assert_called_once_with([], valid_ids=[])
    assert result == {"outcome": "allow"}
    assert len(ctx.journals) == 0


# ----- decide_error_report -----
import pytest
from unittest.mock import patch, MagicMock

from harness.hooks._decide_common import decide_error_report
import harness.hooks._decide_common as module_under_test

class MockDeciderContext:
    def __init__(self):
        self.journal_calls = []

    def journal(self, action, decision, **kwargs):
        self.journal_calls.append((action, decision, kwargs))

def test_decide_error_report_allows_within_limit():
    """Test that a report under the max byte limit is allowed."""
    ctx = MockDeciderContext()
    content = "A brief error report."
    
    with patch.object(module_under_test, 'ERROR_MAX_BYTES', 1000), \
         patch.object(module_under_test._common, 'decision_payload') as mock_payload:
        
        mock_payload.return_value = {"status": "allow"}
        
        result = decide_error_report(ctx, content)
        
        assert result == {"status": "allow"}
        mock_payload.assert_called_once_with('allow')
        assert len(ctx.journal_calls) == 0

def test_decide_error_report_denies_over_limit():
    """Test that a report strictly exceeding the max byte limit is denied and journaled."""
    ctx = MockDeciderContext()
    content = "This error report is too long."
    size = len(content.encode('utf-8'))
    limit = 10
    
    with patch.object(module_under_test, 'ERROR_MAX_BYTES', limit), \
         patch.object(module_under_test._common, 'decision_payload') as mock_payload:
        
        mock_payload.return_value = {"status": "deny"}
        
        result = decide_error_report(ctx, content)
        
        assert result == {"status": "deny"}
        mock_payload.assert_called_once_with(
            'deny', 
            reason=f'error.md exceeds 64 KB cap ({size} bytes > {limit}).'
        )
        assert len(ctx.journal_calls) == 1
        assert ctx.journal_calls[0] == ('error', 'deny', {'detail': {'size': size}})

def test_decide_error_report_multibyte_encoding():
    """Test that the byte size accurately reflects multi-byte utf-8 characters, denying if they cause limit exceedance."""
    ctx = MockDeciderContext()
    # ☃ is 3 bytes in UTF-8. 5 snowmen = 15 bytes.
    content = "☃☃☃☃☃" 
    size = len(content.encode('utf-8'))
    limit = 10
    
    with patch.object(module_under_test, 'ERROR_MAX_BYTES', limit), \
         patch.object(module_under_test._common, 'decision_payload') as mock_payload:
        
        mock_payload.return_value = {"status": "deny"}
        
        result = decide_error_report(ctx, content)
        
        assert result == {"status": "deny"}
        mock_payload.assert_called_once_with(
            'deny', 
            reason=f'error.md exceeds 64 KB cap ({size} bytes > {limit}).'
        )
        assert len(ctx.journal_calls) == 1
        assert ctx.journal_calls[0] == ('error', 'deny', {'detail': {'size': size}})


# ----- decide_read_like -----
import pytest
import pathlib
from unittest.mock import patch
from harness.hooks._decide_common import decide_read_like

@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_no_file_path(mock_decision_payload):
    mock_decision_payload.return_value = {"decision": "mock_allow"}
    tool_input = {"other_key": "some_value"}
    allowed_roots = ["/allowed"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path", "path"), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_allow"}
    mock_decision_payload.assert_called_once_with('allow')

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_safe_subpath(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_allow"}
    mock_is_safe_subpath.side_effect = lambda path, root: root == "/allowed2"
    
    tool_input = {"path": "/allowed2/file.txt"}
    allowed_roots = ["/allowed1", "/allowed2"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path", "path"), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_allow"}
    mock_decision_payload.assert_called_once_with('allow')
    assert mock_is_safe_subpath.call_count == 2
    mock_is_safe_subpath.assert_any_call("/allowed2/file.txt", "/allowed1")
    mock_is_safe_subpath.assert_any_call("/allowed2/file.txt", "/allowed2")

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_unsafe_subpath(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_deny"}
    mock_is_safe_subpath.return_value = False
    
    tool_input = {"file_path": "/unsafe/file.txt"}
    allowed_roots = ["/allowed1"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path", "path"), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_deny"}
    mock_decision_payload.assert_called_once_with(
        'deny', 
        reason='read_tool path outside allowed roots: /unsafe/file.txt. Allowed roots: JANUSMASK_WORK_DIR, $STATE_DIR, project docs/, project briefs/.'
    )
    mock_is_safe_subpath.assert_called_once_with("/unsafe/file.txt", "/allowed1")

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_empty_file_path_value(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_allow"}
    
    tool_input = {"file_path": ""}
    allowed_roots = ["/allowed1"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path", "path"), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_allow"}
    mock_decision_payload.assert_called_once_with('allow')
    mock_is_safe_subpath.assert_not_called()

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_path_keys_order(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_deny"}
    mock_is_safe_subpath.return_value = False
    
    tool_input = {"path": "/unsafe/file.txt", "file_path": ""}
    allowed_roots = ["/allowed1"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path", "path"), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_deny"}
    mock_decision_payload.assert_called_once_with(
        'deny', 
        reason='read_tool path outside allowed roots: /unsafe/file.txt. Allowed roots: JANUSMASK_WORK_DIR, $STATE_DIR, project docs/, project briefs/.'
    )
    mock_is_safe_subpath.assert_called_once_with("/unsafe/file.txt", "/allowed1")

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_pathlib_roots(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_allow"}
    mock_is_safe_subpath.return_value = True
    
    tool_input = {"file_path": "/allowed1/file.txt"}
    allowed_roots = [pathlib.Path("/allowed1")]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("file_path",), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_allow"}
    mock_is_safe_subpath.assert_called_once_with("/allowed1/file.txt", "/allowed1")

@patch('harness.hooks._decide_common.is_safe_subpath')
@patch('harness.hooks._decide_common._common.decision_payload')
def test_decide_read_like_non_string_path(mock_decision_payload, mock_is_safe_subpath):
    mock_decision_payload.return_value = {"decision": "mock_deny"}
    mock_is_safe_subpath.return_value = False
    
    tool_input = {"path": pathlib.Path("/unsafe/file.txt")}
    allowed_roots = ["/allowed1"]
    
    result = decide_read_like(
        tool_input, 
        allowed_roots, 
        path_keys=("path",), 
        tool_name_for_reason="read_tool"
    )
    
    assert result == {"decision": "mock_deny"}
    mock_is_safe_subpath.assert_called_once_with("/unsafe/file.txt", "/allowed1")

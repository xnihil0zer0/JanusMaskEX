"""RED oracle for harness.orchestrator._auto_approve_content_safe.

Drives the AST capability gate DIRECTLY against artifacts staged in a pytest
``tmp_path`` (hermetic: no network, no live ``state/``, no shared global state).

The keystone assertion is RED on HEAD: a staged patch whose ``code`` is an
indented class-method body makes a bare ``ast.parse`` raise ``IndentationError``
-> the gate returns ``False`` today. Once the implementation normalizes with
``textwrap.dedent`` the indented body parses cleanly and the gate returns
``True`` -- so this oracle FAILS on HEAD (expected for a test_authoring oracle)
and turns GREEN once the fix lands. The capability bans (eval/exec/... ) must
stay UNWEAKENED: an indented body that still calls ``eval`` must still be
rejected.
"""
import json
from pathlib import Path
from harness.orchestrator import _auto_approve_content_safe
TASK_ID = 'gate_dedent_task'
INDENTED_METHOD_CODE = '\n    def visit_Assign(self, node):\n        if isinstance(node.value, ast.Call):\n            self._add(node)\n        self.generic_visit(node)\n'
FLUSH_CLEAN_CODE = '\ndef helper(x):\n    return x + 1\n'
FLUSH_EVAL_CODE = '\ndef run(x):\n    return eval(x)\n'
INDENTED_EVAL_CODE = '\n    def run(x):\n        return eval(x)\n'

def _stage_patch_and_gate(tmp_path, code, task_id=TASK_ID):
    """Stage <tmp_path>/output/<task_id>.patches.json as a JSON list of one
    {file, kind, name, code} entry (creating the output dir) and return
    _auto_approve_content_safe(str(tmp_path), task_id)."""
    output_dir = Path(tmp_path) / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    patches = [{'file': 'harness/foo.py', 'kind': 'method', 'name': 'visit_Assign', 'code': code}]
    (output_dir / f'{task_id}.patches.json').write_text(json.dumps(patches), encoding='utf-8')
    return _auto_approve_content_safe(str(tmp_path), task_id)

def test_indented_class_method_body_is_accepted_returns_true(tmp_path):
    assert _stage_patch_and_gate(tmp_path, INDENTED_METHOD_CODE) is True

def test_flush_column0_clean_patch_returns_true(tmp_path):
    assert _stage_patch_and_gate(tmp_path, FLUSH_CLEAN_CODE) is True

def test_flush_eval_patch_is_rejected_returns_false(tmp_path):
    assert _stage_patch_and_gate(tmp_path, FLUSH_EVAL_CODE) is False

def test_indented_eval_patch_still_rejected_returns_false(tmp_path):
    assert _stage_patch_and_gate(tmp_path, INDENTED_EVAL_CODE) is False

def test_helper_stages_patches_json_and_invokes_gate(tmp_path):
    result = _stage_patch_and_gate(tmp_path, FLUSH_CLEAN_CODE)
    staged = Path(tmp_path) / 'output' / f'{TASK_ID}.patches.json'
    assert staged.exists()
    data = json.loads(staged.read_text(encoding='utf-8'))
    assert isinstance(data, list) and data[0]['code'] == FLUSH_CLEAN_CODE
    assert result is True

def test_absence_policy_no_artifact_returns_true(tmp_path):
    assert _auto_approve_content_safe(str(tmp_path), 'no_artifact_task') is True

def test_malformed_invalid_json_returns_false(tmp_path):
    output_dir = Path(tmp_path) / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f'{TASK_ID}.patches.json').write_text('this is not valid json {{{', encoding='utf-8')
    assert _auto_approve_content_safe(str(tmp_path), TASK_ID) is False

def test_malformed_non_string_code_returns_false(tmp_path):
    output_dir = Path(tmp_path) / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    patches = [{'file': 'harness/foo.py', 'kind': 'method', 'name': 'visit_Assign', 'code': 123}]
    (output_dir / f'{TASK_ID}.patches.json').write_text(json.dumps(patches), encoding='utf-8')
    assert _auto_approve_content_safe(str(tmp_path), TASK_ID) is False
"""RED oracle for harness.orchestrator._auto_approve_content_safe non-py skip.

Drives the AST capability gate DIRECTLY against a ``state/output/<id>.files.json``
whole-file manifest staged in a pytest ``tmp_path`` (hermetic: no network, no live
``state/``, no shared global state).

DEFECT (RED on HEAD): the files.json branch collects EVERY manifest value into
``sources`` and ``ast.parse``s each. A non-.py manifest value (e.g. the bytes of
``harness/config.yaml``) is NOT valid Python -> ``ast.parse`` raises -> the gate
returns ``False`` (fail-closed) -> a widened auto-approve grant for a legitimate
config-file edit is revoked -> ``auto_commit_failed``. This blocks EVERY config
edit through the harness_self_fix path.

FIX: in the files.json branch, only collect values whose manifest KEY ends in
``.py`` (config/data are not executed as Python, so eval/exec/os.system/shell=True
detection is meaningless for them). Mirrors the existing non-py skip precedent at
orchestrator.py ~L1622 (manifest) / ~L1676 (single-file).

SAFETY (regression, must stay GREEN): a ``.py`` manifest value containing a
prohibited capability (``os.system(...)`` / ``eval(...)``) STILL returns False --
the .py danger detection is UNCHANGED.
"""
import json
from pathlib import Path
from harness.orchestrator import _auto_approve_content_safe

TASK_ID = 'content_safe_nonpy_task'

# A real-shaped YAML body (NOT valid Python: bare ``key: value`` mapping lines
# make ``ast.parse`` raise a SyntaxError today).
YAML_BODY = (
    "workers:\n"
    "  agy_pool:\n"
    "    enabled: true\n"
    "    size: 8\n"
    "autowork:\n"
    "  parallel_cap: 5\n"
)
# A clean .py body -- must still be accepted.
PY_CLEAN = "def helper(x):\n    return x + 1\n"
# A dangerous .py body -- must still be REJECTED (safety unweakened).
PY_DANGEROUS = "import os\n\ndef run(cmd):\n    return os.system(cmd)\n"
PY_EVAL = "def run(x):\n    return eval(x)\n"


def _stage_files_and_gate(tmp_path, manifest, task_id=TASK_ID):
    """Stage <tmp_path>/output/<task_id>.files.json as a JSON {relpath: source}
    map (creating the output dir) and return the gate result."""
    output_dir = Path(tmp_path) / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f'{task_id}.files.json').write_text(json.dumps(manifest), encoding='utf-8')
    return _auto_approve_content_safe(str(tmp_path), task_id)


def test_nonpy_yaml_value_is_skipped_returns_true(tmp_path):
    # KEYSTONE: a config-only manifest (YAML body under a non-.py key) must NOT
    # be ast.parse'd. RED on HEAD (returns False), GREEN after fix.
    assert _stage_files_and_gate(tmp_path, {'harness/config.yaml': YAML_BODY}) is True


def test_mixed_py_and_yaml_clean_returns_true(tmp_path):
    # A .py value (clean) alongside a YAML value: skip the YAML, scan the .py.
    manifest = {'harness/config.yaml': YAML_BODY, 'harness/helper.py': PY_CLEAN}
    assert _stage_files_and_gate(tmp_path, manifest) is True


def test_py_value_with_os_system_still_rejected_returns_false(tmp_path):
    # REGRESSION / SAFETY: a .py manifest value calling os.system STILL rejected.
    manifest = {'harness/config.yaml': YAML_BODY, 'harness/evil.py': PY_DANGEROUS}
    assert _stage_files_and_gate(tmp_path, manifest) is False


def test_py_value_with_eval_still_rejected_returns_false(tmp_path):
    # REGRESSION / SAFETY: a .py manifest value calling eval STILL rejected even
    # when a benign non-.py value is also present.
    manifest = {'config/x.yaml': YAML_BODY, 'harness/evil.py': PY_EVAL}
    assert _stage_files_and_gate(tmp_path, manifest) is False


def test_clean_py_only_returns_true(tmp_path):
    # REGRESSION: a clean .py-only manifest is still accepted.
    assert _stage_files_and_gate(tmp_path, {'harness/helper.py': PY_CLEAN}) is True

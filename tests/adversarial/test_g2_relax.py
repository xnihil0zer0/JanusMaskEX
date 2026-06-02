"""Oracle for PHASE_G2_RELAX (REV22 §4-3, CR-1/CR-2).

Proves the EXTERNAL-only AST relax for eval/exec/__import__ at BOTH submit-time
and commit-time, while keeping credentials + os_system + bare_except +
nondeterminism STRICT for ALL targets, and ALL constructs strict for self.

The relax is keyed on ``not _target_is_self(task['working_dir'])`` (fail-safe
to self when working_dir is absent/None).

RED on HEAD (no relax param exists): for an EXTERNAL working_dir, eval/exec/
__import__ are STILL blocked at submit and commit -> the "external allowed"
assertions fail.

GREEN after fix: external eval/exec/__import__ allowed at submit AND commit
(including the partial-edit __JANUSMASK_PATCHES__ path); credentials/os_system/
bare_except still blocked external; self still strict.

Real seams exercised:
  * SUBMIT: harness.ast_enforcer.validate_code(..., relax_external_constructs=)
            and harness.hooks.rpc.submit_code.validate/ensure_valid(...,
            relax_external_constructs=)
  * SUBMIT-decider: harness.hooks._decide_common.decide_submission reading
            task['working_dir'] from the staged inbox task.
  * COMMIT: harness.orchestrator._validate_submission(code, agent, task)
            with task['working_dir'] set -> reaches the manifest/partial-edit/
            single-file validate_code calls (orchestrator.py ~:1149/:1188/:1209).
"""
import json
import pathlib
import textwrap
from typing import Any

import pytest

from harness.ast_enforcer import validate_code, Violation
from harness.hooks.rpc import submit_code as rpc_submit_code
from harness.hooks import _decide_common as decide_common
from harness.hooks._decide_common import DeciderContext
from harness import orchestrator


# ---- code fixtures -------------------------------------------------------

EVAL_CODE = "def foo(x):\n    return eval('1 + 1')\n"
EXEC_CODE = "def foo(x):\n    exec('y = 1')\n    return x\n"
IMPORT_CODE = "def foo(x):\n    return __import__('os')\n"

# credentials: must STAY blocked even external (rule 'security')
CRED_CODE = "def foo():\n    api_secret = 'hunter2'\n    return api_secret\n"
# os_system: must STAY blocked even external (rule 'os_system')
OSSYS_CODE = "import os\n\n\ndef foo():\n    os.system('rm -rf /')\n"
# bare_except: must STAY blocked even external (rule 'bare_except')
BAREEXC_CODE = "def foo():\n    try:\n        pass\n    except:\n        pass\n"


def _errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if getattr(v, "severity", "") == "error"]


def _has_rule(violations: list[Violation], rule: str) -> bool:
    return any(v.rule == rule and v.severity == "error" for v in violations)


def _external_dir(tmp_path) -> str:
    """A real directory OUTSIDE the JanusMask tree -> _target_is_self False."""
    from harness.paths import _target_is_self
    d = tmp_path / "external_target"
    d.mkdir()
    s = str(d)
    assert not _target_is_self(s), (
        "test fixture broken: external dir classified as self; pick a dir "
        "outside the repo/state/workroot"
    )
    return s


# ====================================================================== #
# 1. ast_enforcer.validate_code — the relax param, eval/exec/__import__   #
# ====================================================================== #

class TestEnforcerRelaxParam:
    @pytest.mark.parametrize("code", [EVAL_CODE, EXEC_CODE, IMPORT_CODE])
    def test_external_relax_allows_eval_exec_import(self, code):
        # RED on HEAD: validate_code has no relax_external_constructs kwarg ->
        # TypeError; even if tolerated, the security error still fires.
        violations = validate_code(code, relax_external_constructs=True)
        assert not _has_rule(violations, "security"), (
            f"external relax must SUPPRESS eval/exec/__import__ security error; "
            f"got {[(v.rule, v.message) for v in violations]}"
        )
        assert not _errors(violations), (
            f"external eval/exec/__import__ must be clean; got "
            f"{[(v.rule, v.message) for v in violations]}"
        )

    @pytest.mark.parametrize("code", [EVAL_CODE, EXEC_CODE, IMPORT_CODE])
    def test_self_strict_blocks_eval_exec_import(self, code):
        # relax defaults to False -> self semantics unchanged.
        violations = validate_code(code)
        assert _has_rule(violations, "security"), (
            "self/default must STILL block eval/exec/__import__"
        )

    def test_external_relax_keeps_credentials_strict(self):
        violations = validate_code(CRED_CODE, relax_external_constructs=True)
        assert _has_rule(violations, "security"), (
            "credentials must STAY strict (rule 'security') even external"
        )
        assert any(
            "credential" in v.message.lower() for v in violations
        ), "the surviving security error must be the credential one"

    def test_external_relax_keeps_os_system_strict(self):
        violations = validate_code(OSSYS_CODE, relax_external_constructs=True)
        assert _has_rule(violations, "os_system"), (
            "os.system must STAY strict (rule 'os_system') even external"
        )

    def test_external_relax_keeps_bare_except_strict(self):
        violations = validate_code(BAREEXC_CODE, relax_external_constructs=True)
        assert _has_rule(violations, "bare_except"), (
            "bare except:pass must STAY strict even external"
        )

    def test_external_relax_forces_determinism_strict(self):
        # Even if a caller asks allow_nondeterminism=True, external relax must
        # force nondeterminism strict (CR-3): a random import is still blocked.
        code = "import random\n\n\ndef foo():\n    return random.random()\n"
        violations = validate_code(
            code, allow_nondeterminism=True, relax_external_constructs=True
        )
        assert _has_rule(violations, "nondeterminism"), (
            "external relax must force allow_nondeterminism=False -> "
            "nondeterminism stays strict"
        )

    def test_security_rule_name_preserved_for_credentials(self):
        # downstream telemetry depends on the 'security' rule name; the relax
        # must not rename or drop the rule for credentials.
        violations = validate_code(CRED_CODE, relax_external_constructs=True)
        rules = {v.rule for v in violations}
        assert "security" in rules


# ====================================================================== #
# 2. submit_code.validate / ensure_valid — param threaded through        #
# ====================================================================== #

class TestSubmitCodeRelaxParam:
    @pytest.mark.parametrize("code", [EVAL_CODE, EXEC_CODE, IMPORT_CODE])
    def test_validate_external_allows(self, code):
        violations = rpc_submit_code.validate(code, relax_external_constructs=True)
        assert not _errors(violations)

    @pytest.mark.parametrize("code", [EVAL_CODE, EXEC_CODE, IMPORT_CODE])
    def test_validate_self_blocks(self, code):
        violations = rpc_submit_code.validate(code)
        assert _errors(violations)

    def test_ensure_valid_external_allows(self):
        # no AstValidationError for external eval
        warnings = rpc_submit_code.ensure_valid(
            EVAL_CODE, relax_external_constructs=True
        )
        assert all(getattr(w, "severity", "") != "error" for w in warnings)

    def test_ensure_valid_self_raises(self):
        with pytest.raises(rpc_submit_code.AstValidationError):
            rpc_submit_code.ensure_valid(EVAL_CODE)

    def test_ensure_valid_external_credentials_still_raises(self):
        with pytest.raises(rpc_submit_code.AstValidationError):
            rpc_submit_code.ensure_valid(CRED_CODE, relax_external_constructs=True)


# ====================================================================== #
# 3. decide_submission — reads task['working_dir'] from the inbox        #
# ====================================================================== #

class _Journal:
    def __init__(self):
        self.calls = []

    def __call__(self, verb, outcome, *, detail=None):
        self.calls.append((verb, outcome, detail))


def _make_ctx():
    journal = _Journal()
    return DeciderContext(
        session_id="s",
        agent="claude",
        phase="synthesis",
        round_number=1,
        journal=journal,
        allow_with_warnings=lambda w: {"decision": "allow", "warnings": w},
    ), journal


def _write_task(inbox: pathlib.Path, *, working_dir=None):
    inbox.mkdir(parents=True, exist_ok=True)
    task: dict[str, Any] = {
        "task_id": "G2T",
        "synthesis_target_type": "pure_function",
        "files_touched": ["mod.py"],
        "constraints": {"deterministic": True},
    }
    if working_dir is not None:
        task["working_dir"] = working_dir
    (inbox / "task.json").write_text(json.dumps(task))


def _stage_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    return state


class TestDecideSubmissionExternalRelax:
    def test_external_eval_allowed(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        wd = _external_dir(tmp_path)
        ctx, _ = _make_ctx()
        inbox = tmp_path / "inbox"
        _write_task(inbox, working_dir=wd)
        out = decide_common.decide_submission(ctx, EVAL_CODE, [], inbox)
        assert out["decision"] == "allow", (
            f"external eval must be ALLOWED at submit; got {out}"
        )

    def test_self_eval_denied(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        ctx, _ = _make_ctx()
        inbox = tmp_path / "inbox"
        _write_task(inbox, working_dir=None)  # absent -> self
        out = decide_common.decide_submission(ctx, EVAL_CODE, [], inbox)
        assert out["decision"] == "deny", "self eval must be DENIED at submit"

    def test_external_credentials_still_denied(self, tmp_path, monkeypatch):
        _stage_state(tmp_path, monkeypatch)
        wd = _external_dir(tmp_path)
        ctx, _ = _make_ctx()
        inbox = tmp_path / "inbox"
        _write_task(inbox, working_dir=wd)
        out = decide_common.decide_submission(ctx, CRED_CODE, [], inbox)
        assert out["decision"] == "deny", "external credentials must be DENIED"


# ====================================================================== #
# 4. orchestrator._validate_submission — COMMIT-TIME relax (CR-2)        #
#    incl. the partial-edit __JANUSMASK_PATCHES__ path                    #
# ====================================================================== #

def _patches_payload(symbol_code: str, name: str = "foo") -> str:
    patches = [{"file": "mod.py", "kind": "symbol", "name": name, "code": symbol_code}]
    return "__JANUSMASK_PATCHES__ = " + json.dumps(patches) + "\n"


class TestCommitTimeRelax:
    def _task(self, *, working_dir=None, partial_edit=False):
        t: dict[str, Any] = {
            "task_id": "G2T",
            "files_touched": ["mod.py"],
            "constraints": {"deterministic": True},
        }
        if working_dir is not None:
            t["working_dir"] = working_dir
        if partial_edit:
            t["partial_edit"] = True
        return t

    def test_commit_external_eval_allowed_singlefile(self, tmp_path):
        wd = _external_dir(tmp_path)
        ok, violations = orchestrator._validate_submission(
            EVAL_CODE, "claude", self._task(working_dir=wd)
        )
        assert ok is True, (
            f"external eval must PASS commit-time validation; "
            f"violations={[(v.rule, v.message) for v in violations]}"
        )

    def test_commit_self_eval_blocked_singlefile(self, tmp_path):
        ok, _ = orchestrator._validate_submission(
            EVAL_CODE, "claude", self._task(working_dir=None)
        )
        assert ok is False, "self eval must FAIL commit-time validation"

    def test_commit_external_eval_allowed_partial_edit(self, tmp_path):
        wd = _external_dir(tmp_path)
        payload = _patches_payload("def foo(x):\n    return eval('1+1')\n")
        ok, violations = orchestrator._validate_submission(
            payload, "claude", self._task(working_dir=wd, partial_edit=True)
        )
        assert ok is True, (
            f"external eval in a partial-edit patch must PASS commit-time; "
            f"violations={[(v.rule, v.message) for v in violations]}"
        )

    def test_commit_self_eval_blocked_partial_edit(self, tmp_path):
        payload = _patches_payload("def foo(x):\n    return eval('1+1')\n")
        ok, _ = orchestrator._validate_submission(
            payload, "claude", self._task(working_dir=None, partial_edit=True)
        )
        assert ok is False, "self eval in a partial-edit patch must FAIL commit-time"

    def test_commit_external_credentials_still_blocked(self, tmp_path):
        wd = _external_dir(tmp_path)
        ok, _ = orchestrator._validate_submission(
            CRED_CODE, "claude", self._task(working_dir=wd)
        )
        assert ok is False, "external credentials must FAIL commit-time"

    def test_commit_external_os_system_still_blocked(self, tmp_path):
        wd = _external_dir(tmp_path)
        ok, _ = orchestrator._validate_submission(
            OSSYS_CODE, "claude", self._task(working_dir=wd)
        )
        assert ok is False, "external os.system must FAIL commit-time"

"""RED oracle for overseer/gates.py — the deterministic recipe gates.

Each gate is a PURE function returning a typed ``GateResult(ok, reason, fix_hint)``
over INJECTED seams (``run_seam`` executes a test and returns its exit code;
``git_seam`` answers HEAD-membership; ``validator`` wraps the real plan_validator)
or plain filesystem reads under an injected ``state_dir``. No gate spawns a real
process, model, network, or un-injected subprocess — the oracle drives every gate
hermetically. One gate encodes one operator lesson.
"""
import pytest

from overseer.gates import (
    GateResult,
    oracle_is_red,
    oracles_committed_at_head,
    brief_lint,
    plan_preflight,
    suite_green_zero_reg,
    posture_locked,
)


def test_gateresult_carries_ok_reason_fixhint():
    r = GateResult(ok=True, reason='', fix_hint='')
    assert r.ok is True and r.reason == '' and r.fix_hint == ''


# --- oracle_is_red: a FAILING test is RED (good); a passing test is not -------

def test_oracle_is_red_true_when_test_fails():
    # run_seam returns the test's exit code; nonzero == failed == RED == ok.
    res = oracle_is_red('tests/x.py', run_seam=lambda p: 1)
    assert res.ok is True


def test_oracle_is_red_false_when_test_passes():
    res = oracle_is_red('tests/x.py', run_seam=lambda p: 0)
    assert res.ok is False
    assert 'green' in (res.reason + ' ' + res.fix_hint).lower()


# --- oracles_committed_at_head: every path committed at HEAD, not just on disk -

def test_committed_at_head_true_when_all_committed():
    res = oracles_committed_at_head(['a.py', 'b.py'], git_seam=lambda p: True)
    assert res.ok is True


def test_committed_at_head_false_names_the_uncommitted_path():
    res = oracles_committed_at_head(['a.py', 'b.py'], git_seam=lambda p: p != 'b.py')
    assert res.ok is False
    assert 'b.py' in res.reason


# --- brief_lint: Required plan shape present + no source line-number citations -

GOOD_BRIEF = (
    "# Title\noverseer/foo.py\n\n# Required plan shape\n"
    "Emit EXACTLY ONE task for overseer/foo.py described structurally.\n"
)


def test_brief_lint_ok_for_well_formed_brief():
    assert brief_lint(GOOD_BRIEF).ok is True


def test_brief_lint_flags_missing_required_plan_shape():
    res = brief_lint("# Title\nno shape section at all\n")
    assert res.ok is False
    assert 'required plan shape' in res.reason.lower()


def test_brief_lint_flags_naked_line_number_citation():
    res = brief_lint(GOOD_BRIEF + "see overseer/foo.py:123 for the bug\n")
    assert res.ok is False
    assert 'line' in (res.reason + ' ' + res.fix_hint).lower()


# --- plan_preflight: wraps the validator + the recipe checks ------------------

def _ok_validator(plan):
    return []


VALID_TASK = {
    'task_id': 'build_foo',
    'spec': {
        'non_goals': ['integration is explicitly out of scope'],
        'test_spec': {'regression_tests': ['t_edge_a', 't_edge_b']},
    },
}


def test_plan_preflight_ok_for_clean_task(tmp_path):
    res = plan_preflight(VALID_TASK, state_dir=tmp_path, validator=_ok_validator)
    assert res.ok is True


def test_plan_preflight_rejects_generic_T1_task_id(tmp_path):
    bad = dict(VALID_TASK, task_id='T1')
    res = plan_preflight(bad, state_dir=tmp_path, validator=_ok_validator)
    assert res.ok is False
    assert 't1' in res.reason.lower() or 'task_id' in res.reason.lower()


def test_plan_preflight_rejects_processed_marker_collision(tmp_path):
    proc = tmp_path / 'tasks' / 'processed'
    proc.mkdir(parents=True)
    (proc / 'build_foo.json').write_text('{}')
    res = plan_preflight(VALID_TASK, state_dir=tmp_path, validator=_ok_validator)
    assert res.ok is False


def test_plan_preflight_requires_integration_in_non_goals(tmp_path):
    bad = {'task_id': 'x', 'spec': {'non_goals': ['nope'],
           'test_spec': {'regression_tests': ['a', 'b']}}}
    res = plan_preflight(bad, state_dir=tmp_path, validator=_ok_validator)
    assert res.ok is False
    assert 'integration' in res.reason.lower()


def test_plan_preflight_requires_two_edge_case_tests(tmp_path):
    bad = {'task_id': 'x', 'spec': {'non_goals': ['integration'],
           'test_spec': {'regression_tests': ['only_one']}}}
    res = plan_preflight(bad, state_dir=tmp_path, validator=_ok_validator)
    assert res.ok is False


def test_plan_preflight_propagates_validator_violations(tmp_path):
    res = plan_preflight(VALID_TASK, state_dir=tmp_path, validator=lambda p: ['boom'])
    assert res.ok is False


# --- suite_green_zero_reg: oracle GREEN and zero new regressions --------------

def test_suite_gate_ok_when_green_and_no_regressions():
    assert suite_green_zero_reg({'oracle_green': True, 'new_regressions': 0}).ok is True


def test_suite_gate_fails_on_red_oracle():
    assert suite_green_zero_reg({'oracle_green': False, 'new_regressions': 0}).ok is False


def test_suite_gate_fails_and_counts_regressions():
    res = suite_green_zero_reg({'oracle_green': True, 'new_regressions': 3})
    assert res.ok is False and '3' in res.reason


# --- posture_locked: full_stop + flag==pause + allowlist deny-all -------------

def _lock(state_dir, *, full_stop=True, flag='pause', allowlist_deny_all=True):
    ctl = state_dir / 'control'
    (ctl / 'autowork').mkdir(parents=True, exist_ok=True)
    if full_stop:
        (ctl / 'autowork' / 'full_stop').write_text('')
    (ctl / 'orchestrator.flag').write_text(flag)
    al = ctl / 'autowork' / 'auto_promote.allowlist'
    al.write_text('# comment only — deny-all\n' if allowlist_deny_all else '# c\nmyslug\n')


def test_posture_locked_ok_when_all_three_gates_set(tmp_path):
    _lock(tmp_path)
    assert posture_locked(state_dir=tmp_path).ok is True


def test_posture_unlocked_when_full_stop_missing(tmp_path):
    _lock(tmp_path, full_stop=False)
    assert posture_locked(state_dir=tmp_path).ok is False


def test_posture_unlocked_when_flag_not_pause(tmp_path):
    _lock(tmp_path, flag='run')
    assert posture_locked(state_dir=tmp_path).ok is False


def test_posture_unlocked_when_allowlist_has_entries(tmp_path):
    _lock(tmp_path, allowlist_deny_all=False)
    assert posture_locked(state_dir=tmp_path).ok is False

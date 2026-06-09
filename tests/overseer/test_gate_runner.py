"""Oracle for overseer/gate_runner.py — the production gate resolver.

This is the missing wire that makes the procedure FSM actually advance at
runtime. make_default_gate_runner returns a callable
``gate_runner(mode, phase, rec, state_dir) -> GateResult`` (exactly what
turn_runner.run_chat_turn's procedure loop calls). For each phase it resolves
the phase's gate-LABEL (via procedure.PROCEDURE_REGISTRY) to a real check:

  * BACKED gates run the real overseer.gates function on inputs gathered from
    rec['procedure_artifacts'] + injected seams (pytest/git) or state_dir,
  * DERIVED gates (preflight_clean/swept/registry_zeroed/pushed) use injected
    status/pending/pushed seams,
  * ATTESTED judgment gates (scope_locked, etc.) pass only when the operator has
    attested the phase in rec['procedure_attested'].

A backed gate with no recorded artifact yields ok=False with an actionable hint
(it does NOT silently pass — no theater).
"""
from overseer.gate_runner import make_default_gate_runner, gate_label_for
from overseer.gates import GateResult


def _runner(tmp_path, **seams):
    return make_default_gate_runner(repo_root=tmp_path, state_dir=tmp_path / "state", **seams)


def _lock_posture(state_dir):
    aw = state_dir / "control" / "autowork"
    aw.mkdir(parents=True, exist_ok=True)
    (aw / "full_stop").write_text("")
    (state_dir / "control" / "orchestrator.flag").write_text("pause")
    (aw / "auto_promote.allowlist").write_text("# deny-all\n")


# --- label resolution ------------------------------------------------------

def test_gate_label_for_resolves_phase_to_its_gate():
    assert gate_label_for("push", "POSTURE") == "posture_ok"
    assert gate_label_for("brief-author", "SCOPE") == "scope_locked"
    assert gate_label_for("oracle-author", "RED") == "oracle_is_red"
    assert gate_label_for("nope", "X") is None


def test_runner_is_a_four_arg_callable(tmp_path):
    gr = _runner(tmp_path)
    res = gr("push", "POSTURE", {}, tmp_path / "state")
    assert isinstance(res, GateResult)


# --- self-contained backed gate: posture_ok -------------------------------

def test_posture_ok_passes_when_locked(tmp_path):
    _lock_posture(tmp_path / "state")
    gr = _runner(tmp_path)
    assert gr("push", "POSTURE", {}, tmp_path / "state").ok is True


def test_posture_ok_fails_when_unlocked(tmp_path):
    gr = _runner(tmp_path)
    res = gr("push", "POSTURE", {}, tmp_path / "state")
    assert res.ok is False and "full_stop" in res.reason


# --- backed gates over artifacts + injected seams -------------------------

def test_oracle_is_red_runs_recorded_oracle_via_run_seam(tmp_path):
    calls = {}
    def run_seam(path):
        calls["path"] = path
        return 1  # non-zero => RED => pass
    gr = _runner(tmp_path, run_seam=run_seam)
    rec = {"procedure_artifacts": {"oracle_path": "tests/overseer/test_x.py"}}
    res = gr("oracle-author", "RED", rec, tmp_path / "state")
    assert res.ok is True
    assert calls["path"] == "tests/overseer/test_x.py"


def test_oracle_committed_checks_git_seam(tmp_path):
    gr = _runner(tmp_path, git_seam=lambda p: False)  # uncommitted
    rec = {"procedure_artifacts": {"oracle_paths": ["tests/overseer/test_x.py"]}}
    res = gr("oracle-author", "COMMIT", rec, tmp_path / "state")
    assert res.ok is False and "not committed" in res.reason


def test_brief_written_lints_recorded_brief(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Title\n\nDoes things to one_file.py\n\n# Required plan shape\nstuff\n")
    gr = _runner(tmp_path)
    rec = {"procedure_artifacts": {"brief_path": str(brief)}}
    assert gr("brief-author", "BRIEF", rec, tmp_path / "state").ok is True


def test_plan_ready_preflights_recorded_plan(tmp_path):
    gr = _runner(tmp_path)
    # an empty/garbage plan must fail preflight (not silently pass)
    rec = {"procedure_artifacts": {"plan": {"task_id": "T1"}}}
    assert gr("brief-author", "PLAN", rec, tmp_path / "state").ok is False


def test_verified_uses_recorded_report(tmp_path):
    gr = _runner(tmp_path)
    ok_rec = {"procedure_artifacts": {"report": {"oracle_green": True, "new_regressions": 0}}}
    bad_rec = {"procedure_artifacts": {"report": {"oracle_green": False, "new_regressions": 0}}}
    assert gr("dispatch", "VERIFY", ok_rec, tmp_path / "state").ok is True
    assert gr("dispatch", "VERIFY", bad_rec, tmp_path / "state").ok is False


def test_backed_gate_without_artifact_fails_with_hint(tmp_path):
    gr = _runner(tmp_path)
    res = gr("oracle-author", "RED", {}, tmp_path / "state")  # no oracle recorded
    assert res.ok is False and res.fix_hint  # actionable, not silent-pass


# --- derived gate via injected seam ---------------------------------------

def test_pushed_uses_pushed_seam(tmp_path):
    gr = _runner(tmp_path, pushed_seam=lambda: True)
    assert gr("push", "PUSH", {}, tmp_path / "state").ok is True
    gr2 = _runner(tmp_path, pushed_seam=lambda: False)
    assert gr2("push", "PUSH", {}, tmp_path / "state").ok is False


# --- attested judgment gate ------------------------------------------------

def test_attested_gate_blocks_until_attested(tmp_path):
    gr = _runner(tmp_path)
    blocked = gr("brief-author", "SCOPE", {}, tmp_path / "state")
    assert blocked.ok is False
    passed = gr("brief-author", "SCOPE", {"procedure_attested": {"SCOPE": True}}, tmp_path / "state")
    assert passed.ok is True

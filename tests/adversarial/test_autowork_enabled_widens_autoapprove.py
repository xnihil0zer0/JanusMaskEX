"""Phase-2 bootstrap oracle: ``autowork.enabled`` WIDENS auto-approve to fully unattended.

Owner decision 2026-06-05 (memory: phase2-autonomy-security-posture): the
auto-approve security posture is conditional on the webui-controlled
``autowork.enabled`` toggle (written to harness/config.yaml by put_config_autowork).

  * autowork.enabled == True  -> WIDENED: any ``harness/**`` path NOT on the
    ``_NEVER_AUTO_APPROVE`` deny-list is auto-approvable regardless of
    meta_task_type / self-heal HMAC provenance / ceiling. Fully unattended.
  * autowork.enabled in (False, absent) -> STRICT floor unchanged (self-heal only:
    harness_self_fix + HMAC provenance + ceiling).

RED on HEAD: HEAD requires harness_self_fix + HMAC + ceiling for ANY auto-approve,
so a plain domain task under autowork.enabled returns False.
"""
import json

from harness import orchestrator


def _mk_state(tmp_path):
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True, exist_ok=True)
    return sd


def _plain_task():
    # A normal planner-emitted task: domain meta_task_type, NOT a self-heal brief.
    return {"meta_task_type": "data_model"}


def test_widened_grants_plain_harness_task(tmp_path):
    sd = _mk_state(tmp_path)
    cfg = {"autowork": {"enabled": True, "auto_approve_sensitive_harness": True}}
    ok = orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "phase2_symbol_ledger",
        ["harness/symbol_ledger.py"], cfg, repo_root=tmp_path,
    )
    assert ok is True, "autowork.enabled must widen auto-approve to any non-deny harness/** path"


def test_widened_still_blocks_denylist(tmp_path):
    sd = _mk_state(tmp_path)
    cfg = {"autowork": {"enabled": True, "auto_approve_sensitive_harness": True}}
    for denied in ("harness/orchestrator.py", "harness/agent_jail.py",
                   "harness/autowork_daemon.py", "harness/git_integration.py",
                   "harness/dbus_proxy.py", "harness/interceptors.py",
                   "harness/paths.py", "harness/selfheal.py"):
        ok = orchestrator._auto_approve_sensitive_eligible(
            sd, _plain_task(), "t", [denied], cfg, repo_root=tmp_path,
        )
        assert ok is False, f"{denied} is escape/controller-critical and must NEVER auto-approve"


def test_widened_ignores_ceiling(tmp_path):
    sd = _mk_state(tmp_path)
    (sd / "control" / "autowork" / "auto_approve_count.json").write_text(
        json.dumps({"count": 999}), encoding="utf-8")
    cfg = {"autowork": {"enabled": True, "auto_approve_sensitive_harness": True,
                        "auto_approve_sensitive_ceiling": 3}}
    ok = orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["harness/symbol_ledger.py"], cfg, repo_root=tmp_path,
    )
    assert ok is True, "widened mode must not be capped by the strict ceiling"


def test_widened_rejects_traversal_and_nonharness(tmp_path):
    sd = _mk_state(tmp_path)
    cfg = {"autowork": {"enabled": True, "auto_approve_sensitive_harness": True}}
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["harness/agent_jail.py/../foo.py"], cfg, repo_root=tmp_path) is False
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["tools/webui_control.py"], cfg, repo_root=tmp_path) is False
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", [], cfg, repo_root=tmp_path) is False


def test_strict_floor_preserved_when_disabled(tmp_path):
    sd = _mk_state(tmp_path)
    cfg = {"autowork": {"auto_approve_sensitive_harness": True}}
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["harness/symbol_ledger.py"], cfg, repo_root=tmp_path) is False, \
        "with autowork disabled the strict self-heal-only floor must hold"
    cfg2 = {"autowork": {"enabled": False, "auto_approve_sensitive_harness": True}}
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["harness/symbol_ledger.py"], cfg2, repo_root=tmp_path) is False


def test_outer_flag_still_required_when_widened(tmp_path):
    sd = _mk_state(tmp_path)
    cfg = {"autowork": {"enabled": True, "auto_approve_sensitive_harness": False}}
    assert orchestrator._auto_approve_sensitive_eligible(
        sd, _plain_task(), "t", ["harness/symbol_ledger.py"], cfg, repo_root=tmp_path) is False

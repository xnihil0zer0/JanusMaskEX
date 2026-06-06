"""Oracle for the flag-gated resolve_interfaces wiring at the staging seam.

RED on HEAD (f6dd7f8): ``harness/planner/staging._maybe_resolve_interfaces`` loads
config via ``from harness import config`` — a module that does NOT exist — so the
try/except always raises ImportError, ``cfg`` stays None, and the function returns
early. The feature is SILENTLY INERT: even with the symbol_ledger flag ON and a
real resolver hit, ``spec.interfaces`` is never rewritten. These tests fail.

GREEN after the fix: the helper loads config via the canonical
``harness.orchestrator.load_config`` and, when
``config['hierarchical_planning']['symbol_ledger']`` is truthy and the task has a
non-empty str ``spec.interfaces``, rewrites it in place with
``resolve_interfaces(interfaces, state_dir)``. Flag off / missing spec / resolver
miss / any error => task left untouched, never raises.

Hermetic: config and the resolver are monkeypatched; no real config.yaml or
symbol ledger is read. ``stage_task`` cases use tmp_path only.
"""
import json

import pytest

import harness.planner.staging as staging


def _cfg(symbol_ledger):
    return {"hierarchical_planning": {"symbol_ledger": symbol_ledger}}


def _patch_loader(monkeypatch, cfg):
    """Patch the canonical loader the fixed impl uses (lazy-imported in-body)."""
    import harness.orchestrator as orch
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg, raising=False)


def _patch_resolver(monkeypatch, fn):
    import harness.symbol_ledger as sl
    monkeypatch.setattr(sl, "resolve_interfaces", fn, raising=False)


def test_flag_on_and_hit_rewrites_interfaces(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(True))
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: "RESOLVED::" + interfaces)
    task = {"task_id": "t", "spec": {"interfaces": "foo(x: int) -> str"}}
    staging._maybe_resolve_interfaces(task, tmp_path)
    assert task["spec"]["interfaces"] == "RESOLVED::foo(x: int) -> str"


def test_flag_off_leaves_interfaces_unchanged(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(False))
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: "RESOLVED::" + interfaces)
    task = {"task_id": "t", "spec": {"interfaces": "foo(x: int) -> str"}}
    staging._maybe_resolve_interfaces(task, tmp_path)
    assert task["spec"]["interfaces"] == "foo(x: int) -> str"


def test_resolver_miss_returns_input_unchanged(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(True))
    # A miss: resolver returns its input unchanged (symbol not derivable).
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: interfaces)
    task = {"task_id": "t", "spec": {"interfaces": "foo(x: int) -> str"}}
    staging._maybe_resolve_interfaces(task, tmp_path)
    assert task["spec"]["interfaces"] == "foo(x: int) -> str"


def test_missing_spec_interfaces_is_noop(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(True))
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: "RESOLVED::" + interfaces)
    task_no_spec = {"task_id": "t"}
    staging._maybe_resolve_interfaces(task_no_spec, tmp_path)  # must not raise
    assert "spec" not in task_no_spec or not task_no_spec.get("spec")
    task_no_iface = {"task_id": "t", "spec": {"objective": "x"}}
    staging._maybe_resolve_interfaces(task_no_iface, tmp_path)
    assert "interfaces" not in task_no_iface["spec"]


def test_resolver_exception_is_swallowed(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(True))

    def _boom(interfaces, state_dir):
        raise RuntimeError("ledger blew up")

    _patch_resolver(monkeypatch, _boom)
    task = {"task_id": "t", "spec": {"interfaces": "foo(x: int) -> str"}}
    staging._maybe_resolve_interfaces(task, tmp_path)  # must not propagate
    assert task["spec"]["interfaces"] == "foo(x: int) -> str"


def test_stage_task_invokes_resolution_at_the_seam(tmp_path, monkeypatch):
    """End-to-end at the seam: stage_task materializes a task whose spec.interfaces
    has been rewritten when the flag is on."""
    _patch_loader(monkeypatch, _cfg(True))
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: "RESOLVED::" + interfaces)
    plan = {"tasks": [{"task_id": "task-a", "spec": {"interfaces": "bar() -> None"}}]}
    plan_path = tmp_path / "plan_hooks_x.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    state_dir = tmp_path / "state"
    out = staging.stage_task(plan_path, "task-a", state_dir)
    staged = json.loads(out.read_text(encoding="utf-8"))
    assert staged["spec"]["interfaces"] == "RESOLVED::bar() -> None"


def test_stage_task_seam_noop_when_flag_off(tmp_path, monkeypatch):
    _patch_loader(monkeypatch, _cfg(False))
    _patch_resolver(monkeypatch, lambda interfaces, state_dir: "RESOLVED::" + interfaces)
    plan = {"tasks": [{"task_id": "task-b", "spec": {"interfaces": "bar() -> None"}}]}
    plan_path = tmp_path / "plan_hooks_y.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    state_dir = tmp_path / "state"
    out = staging.stage_task(plan_path, "task-b", state_dir)
    staged = json.loads(out.read_text(encoding="utf-8"))
    assert staged["spec"]["interfaces"] == "bar() -> None"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

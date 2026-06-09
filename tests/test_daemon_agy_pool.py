"""Wiring oracle: the daemon assigns an agy-pool slot to each spawned worker.

Pillar B lifecycle: when workers.agy_pool.enabled, the daemon gives every
concurrent worker a distinct slot (0..size-1) recorded as a <task_id>.slot
sidecar next to its <task_id>.pid, and injects JANUSMASK_AGY_SLOT into the
worker's env. orchestrator._apply_agy_pool_env (separate leaf) turns that slot
into a private $HOME. Busy slots are derived from the .slot sidecars of
still-LIVE pidfiles, so a reaped worker's slot frees implicitly.

Hermetic: no real worker is spawned; subprocess.Popen and load_config are
monkeypatched.
"""
import inspect

from harness import autowork_daemon as d


def _running_dir(state_dir):
    rd = d._running_dir(state_dir)
    rd.mkdir(parents=True, exist_ok=True)
    return rd


def _enabled_cfg(size=8):
    return {"workers": {"agy_pool": {"enabled": True, "size": size}},
            "autowork": {"parallel_cap": 5}}


def test_busy_slots_read_from_live_pidfile_sidecars(tmp_path):
    rd = _running_dir(tmp_path)
    # task A: live (.pid present) on slot 0; task B: live on slot 2.
    (rd / "A.pid").write_text("111"); (rd / "A.slot").write_text("0")
    (rd / "B.pid").write_text("222"); (rd / "B.slot").write_text("2")
    # task C: stale .slot with NO .pid -> must be ignored (slot 1 stays free).
    (rd / "C.slot").write_text("1")
    busy = d._agy_pool_busy_slots(tmp_path)
    assert busy == {0, 2}


def test_assign_picks_lowest_free_slot_and_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.orchestrator.load_config", lambda: _enabled_cfg())
    rd = _running_dir(tmp_path)
    (rd / "A.pid").write_text("111"); (rd / "A.slot").write_text("0")
    slot = d._agy_pool_assign(tmp_path, "newtask")
    assert slot == 1                                  # lowest free
    assert (rd / "newtask.slot").read_text().strip() == "1"


def test_assign_returns_none_when_pool_disabled(tmp_path, monkeypatch):
    cfg = _enabled_cfg(); cfg["workers"]["agy_pool"]["enabled"] = False
    monkeypatch.setattr("harness.orchestrator.load_config", lambda: cfg)
    assert d._agy_pool_assign(tmp_path, "t") is None
    assert not (d._running_dir(tmp_path) / "t.slot").exists()


class _FakeProc:
    pid = 4242


def test_spawn_worker_injects_slot_env_when_assigned(tmp_path, monkeypatch):
    captured = {}

    def fake_popen(cmd, **kw):
        captured["env"] = kw.get("env")
        return _FakeProc()

    monkeypatch.setattr(d.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(d, "_agy_pool_assign", lambda state_dir, task_id: 3)
    (tmp_path / "tasks").mkdir(parents=True, exist_ok=True)
    pid = d._spawn_worker(tmp_path, "tid")
    assert pid == 4242
    assert captured["env"]["JANUSMASK_AGY_SLOT"] == "3"


def test_spawn_worker_no_slot_env_when_pool_off(tmp_path, monkeypatch):
    captured = {}

    def fake_popen(cmd, **kw):
        captured["env"] = kw.get("env")
        return _FakeProc()

    monkeypatch.setattr(d.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(d, "_agy_pool_assign", lambda state_dir, task_id: None)
    (tmp_path / "tasks").mkdir(parents=True, exist_ok=True)
    d._spawn_worker(tmp_path, "tid")
    assert "JANUSMASK_AGY_SLOT" not in captured["env"]


def test_spawn_worker_calls_pool_assign():
    # Anti-orphan guard: the spawn path consults the pool assigner + env var.
    src = inspect.getsource(d._spawn_worker)
    assert "_agy_pool_assign" in src and "JANUSMASK_AGY_SLOT" in src

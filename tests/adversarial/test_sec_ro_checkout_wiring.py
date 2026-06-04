import json
import hashlib
import hmac
import os
import pathlib
import subprocess
import time
import pytest

import harness.orchestrator as orch
import harness.selfheal as sh
import harness.git_integration as git_integration

def _git(args, cwd):
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True, env=env)

def _mint_marker(state_dir: pathlib.Path, slug: str, tid: str, brief_bytes: bytes, secret_file: pathlib.Path) -> None:
    secret = secret_file.read_bytes()
    digest = hashlib.sha256(brief_bytes).hexdigest()
    marker = hmac.new(secret, (slug + ':' + digest).encode(), hashlib.sha256).hexdigest()
    prov_dir = state_dir / 'control' / 'autowork' / 'selfheal_provenance'
    prov_dir.mkdir(parents=True, exist_ok=True)
    prov_path = prov_dir / f'{slug}.json'
    prov_path.write_text(json.dumps({
        'slug': slug,
        'origin_task_id': tid,
        'marker': marker,
        'ts': int(time.time()),
        'version': 1,
    }))

@pytest.fixture
def test_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "harness").mkdir(parents=True)
    sd = repo / "state"
    (sd / "output").mkdir(parents=True)
    (repo / "harness" / "test_author.py").write_text("def f():\n    return 1\n")
    
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)

    # Monkeypatch the secret path to a temp file
    secret_file = tmp_path / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))

    # Generate the secret using selfheal's secret helper
    sh._selfheal_secret()

    # Monkeypatch processed marking and blocked marking to no-ops
    monkeypatch.setattr(orch, "_mark_processed", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_mark_blocked", lambda *a, **k: None)

    return repo, sd, secret_file, tmp_path

def test_sec_ro_checkout_wiring_abort_on_fail(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    # Monkeypatch _verify_from_ro_parent to return False
    monkeypatch.setattr(git_integration, "_verify_from_ro_parent", lambda *a, **k: False)

    task_id = "task_ro_fail"
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix test_author.py\n"
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)

    artifact_file = sd / "output" / f"{task_id}.py"
    artifact_file.write_text("def f():\n    return 2\n")

    cfg = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3,
            "auto_approve_ro_gate": True
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    # Operator decision is not granted (auto-approve path)
    monkeypatch.setattr(orch, "_apply_approval_granted", lambda state_dir, task_id: False)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    ok = orch._auto_commit_accepted(sd, task, task_id)

    # On HEAD: _verify_from_ro_parent is NOT consulted, so it commits normally, returns True, and count bumps to 1.
    # On fixed: it aborts, returns False, and count stays 0.
    assert ok is False, "Expected auto-approve commit to be aborted due to RO-parent gate failure"

    # Assert count was not incremented
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    if count_file.exists():
        count_data = json.loads(count_file.read_text(encoding="utf-8"))
        assert count_data.get("count", 0) == 0, f"Expected ceiling count to stay 0, got {count_data.get('count')}"

def test_sec_ro_checkout_wiring_succeed_on_pass(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    # Monkeypatch _verify_from_ro_parent to return True
    monkeypatch.setattr(git_integration, "_verify_from_ro_parent", lambda *a, **k: True)

    task_id = "task_ro_pass"
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix test_author.py again\n"
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)

    artifact_file = sd / "output" / f"{task_id}.py"
    artifact_file.write_text("def f():\n    return 2\n")

    cfg = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3,
            "auto_approve_ro_gate": True
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(orch, "_apply_approval_granted", lambda state_dir, task_id: False)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is True, "With passing RO-parent gate, auto-approve commit should succeed"

    # Assert count was incremented
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    assert count_file.exists()
    count_data = json.loads(count_file.read_text(encoding="utf-8"))
    assert count_data.get("count") == 1

def test_sec_ro_checkout_wiring_flag_off_operator_unchanged(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    # Monkeypatch _verify_from_ro_parent to return False
    monkeypatch.setattr(git_integration, "_verify_from_ro_parent", lambda *a, **k: False)

    task_id = "task_ro_flag_off"
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix test_author.py\n"
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)

    artifact_file = sd / "output" / f"{task_id}.py"
    artifact_file.write_text("def f():\n    return 2\n")

    # Scenario 1: Auto-approve flag is OFF (RO-gate flag ON to prove it is dead
    # without the auto-approve grant).
    cfg = {
        "autowork": {
            "auto_approve_sensitive_harness": False,
            "auto_approve_sensitive_ceiling": 3,
            "auto_approve_ro_gate": True
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(orch, "_apply_approval_granted", lambda state_dir, task_id: False)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is False, "When auto-approve flag is OFF, commit should fail"
    
    # Assert count was not created
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    assert not count_file.exists()

    # Scenario 2: Operator approved (bypasses auto-approve, so RO gate not consulted)
    monkeypatch.setattr(orch, "_apply_approval_granted", lambda state_dir, task_id: True)

    ok_op = orch._auto_commit_accepted(sd, task, task_id)
    assert ok_op is True, "With operator approval, commit should succeed despite RO gate returning False"
    
    # Assert count was not bumped (it is operator-approved, not auto-approved)
    if count_file.exists():
        count_data = json.loads(count_file.read_text(encoding="utf-8"))
        assert count_data.get("count", 0) == 0

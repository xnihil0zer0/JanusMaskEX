"""Oracle for security INV5: TOCTOU artifact pin on the auto-approve commit.

RED on HEAD: the pin and re-verify do not exist, so Case (A) and (B) commit normally.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import pathlib
import subprocess
import time
import pytest
import fcntl

import harness.orchestrator as orch
import harness.selfheal as sh

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

def test_sec_inv5_toctou_pin_artifact_tamper(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskA"
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
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # Monkeypatch fcntl.flock to perform artifact tamper on locking
    orig_flock = fcntl.flock
    def mock_flock(fd, operation):
        # §4b (2026-06-10): acquisition is now bounded LOCK_NB|LOCK_EX, so match
        # any EX acquisition (and not LOCK_UN) rather than the bare blocking form.
        if operation & fcntl.LOCK_EX:
            artifact_file.write_text("def f():\n    return 999\n")
        return orig_flock(fd, operation)
    monkeypatch.setattr(fcntl, "flock", mock_flock)

    ok = orch._auto_commit_accepted(sd, task, task_id)
    
    # On HEAD: it does not check the pin, so the commit lands and it returns True.
    # On fixed: it detects the mismatch between original pin and mutated artifact, aborts and returns False.
    assert ok is False, "Expected auto-commit to be aborted due to artifact tamper"

    # Assert count was not incremented
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    if count_file.exists():
        count_data = json.loads(count_file.read_text(encoding="utf-8"))
        assert count_data.get("count", 0) == 0, f"Expected ceiling count to be 0 or not exist, got {count_data.get('count')}"


def test_sec_inv5_toctou_pin_head_shift(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskB"
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
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # Monkeypatch fcntl.flock to shift HEAD on locking
    orig_flock = fcntl.flock
    def mock_flock(fd, operation):
        # §4b (2026-06-10): acquisition is now bounded LOCK_NB|LOCK_EX, so match
        # any EX acquisition (and not LOCK_UN) rather than the bare blocking form.
        if operation & fcntl.LOCK_EX:
            # Shift HEAD in the parent repository by making a commit
            (repo / "harness" / "test_author.py").write_text("def f():\n    return 42\n")
            _git(["add", "-A"], repo)
            _git(["commit", "-qm", "shifted HEAD commit"], repo)
        return orig_flock(fd, operation)
    monkeypatch.setattr(fcntl, "flock", mock_flock)

    ok = orch._auto_commit_accepted(sd, task, task_id)

    # On HEAD there is no pin/re-verify: the staging commit SUCCEEDS (so the
    # ceiling counter is bumped to 1 inside the flock), and only the LATER
    # fast-forward merge fails because the parent HEAD moved -- so the function
    # already returns False on HEAD for an UNRELATED reason. The return value
    # therefore cannot discriminate HEAD from fixed. The CEILING COUNT does: on
    # HEAD it is incremented to 1 (commit landed); on the fixed code the pin
    # re-verify detects the parent-HEAD shift and ABORTS before
    # commit_accepted_output is ever called, so no commit -> count stays 0.
    assert ok is False, "Auto-commit must not succeed after a parent HEAD shift"
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    if count_file.exists():
        count_data = json.loads(count_file.read_text(encoding="utf-8"))
        assert count_data.get("count", 0) == 0, (
            "Expected ceiling count to stay 0 (pin aborts before commit on HEAD shift); "
            f"got {count_data.get('count')} -- on HEAD the commit lands and bumps the counter."
        )


def test_sec_inv5_toctou_pin_no_tamper(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskC"
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix test_author.py yet again\n"
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)

    artifact_file = sd / "output" / f"{task_id}.py"
    artifact_file.write_text("def f():\n    return 2\n")

    cfg = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is True, "Without tamper, auto-approve commit should succeed"

    # Assert count was incremented
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    assert count_file.exists()
    count_data = json.loads(count_file.read_text(encoding="utf-8"))
    assert count_data.get("count") == 1


def test_sec_inv5_toctou_pin_flag_off(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskD"
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix test_author.py yet again\n"
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)

    artifact_file = sd / "output" / f"{task_id}.py"
    artifact_file.write_text("def f():\n    return 2\n")

    cfg = {
        "autowork": {
            "auto_approve_sensitive_harness": False,
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    task = {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is False, "When flag is OFF, auto-commit should fail"

    # Assert count was not created
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    assert not count_file.exists()

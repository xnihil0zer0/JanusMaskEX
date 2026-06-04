"""Oracle for P10-B: consulting auto-approve helper and ceiling increment inside auto-commit.

RED on HEAD: _auto_commit_accepted does not fall back to _auto_approve_sensitive_eligible,
so Case (A) returns False.
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

def test_p10b_consult_ceiling(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    # 1. CASE (A): flag ON + valid provenance marker + NO operator decision file -> commit lands, count=1.
    task_id_a = "taskA"
    slug_a = f"selfheal_{task_id_a}"
    brief_path_a = repo / f"brief_hooks_{slug_a}.md"
    brief_content_a = b"# Objective\nFix test_author.py\n"
    brief_path_a.write_bytes(brief_content_a)
    _mint_marker(sd, slug_a, task_id_a, brief_content_a, secret_file)

    (sd / "output" / f"{task_id_a}.py").write_text("def f():\n    return 2\n")

    cfg_a = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg_a)

    task_a = {
        "task_id": task_id_a,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # Verify return value
    # On HEAD, this returns False because no operator decision file exists and fallback isn't wired.
    # On fixed code, it should return True and auto_approve_count should be 1.
    ok = orch._auto_commit_accepted(sd, task_a, task_id_a)
    
    # Assert return value is True (commit succeeded)
    assert ok is True, "Case (A): Expected auto-commit to succeed via auto-approve fallback"

    # Assert count is 1
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    assert count_file.exists(), "Case (A): auto_approve_count.json was not created"
    
    count_data = json.loads(count_file.read_text(encoding="utf-8"))
    assert count_data.get("count") == 1, f"Case (A): Expected count to be 1, got {count_data.get('count')}"


def test_p10b_consult_ceiling_other_cases(test_env, monkeypatch) -> None:
    repo, sd, secret_file, tmp_path = test_env

    # Setup common task properties for other cases
    task_id_b = "taskB"
    slug_b = f"selfheal_{task_id_b}"
    brief_path_b = repo / f"brief_hooks_{slug_b}.md"
    brief_content_b = b"# Objective\nFix test_author.py again\n"
    brief_path_b.write_bytes(brief_content_b)
    _mint_marker(sd, slug_b, task_id_b, brief_content_b, secret_file)

    (sd / "output" / f"{task_id_b}.py").write_text("def f():\n    return 3\n")

    cfg_common = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg_common)

    task_b = {
        "task_id": task_id_b,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # 2. CASE (B): flag ON + count.json pre-seeded at the ceiling -> no commit, count unchanged.
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    count_file.parent.mkdir(parents=True, exist_ok=True)
    count_file.write_text(json.dumps({"count": 3}), encoding="utf-8")

    ok = orch._auto_commit_accepted(sd, task_b, task_id_b)
    assert ok is False, "Case (B): Expected commit to be refused when count is at the ceiling"
    
    count_data = json.loads(count_file.read_text(encoding="utf-8"))
    assert count_data.get("count") == 3, f"Case (B): Count should remain 3, got {count_data.get('count')}"

    # 3. CASE (C): flag OFF (default) + no operator grant -> refused, no commit, no increment.
    task_id_c = "taskC"
    slug_c = f"selfheal_{task_id_c}"
    brief_path_c = repo / f"brief_hooks_{slug_c}.md"
    brief_content_c = b"# Objective\nFix test_author.py yet again\n"
    brief_path_c.write_bytes(brief_content_c)
    _mint_marker(sd, slug_c, task_id_c, brief_content_c, secret_file)

    (sd / "output" / f"{task_id_c}.py").write_text("def f():\n    return 4\n")

    cfg_c = {
        "autowork": {
            "auto_approve_sensitive_harness": False,
            "auto_approve_sensitive_ceiling": 3
        },
        "agent_sandbox": {
            "bwrap": False
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg_c)

    task_c = {
        "task_id": task_id_c,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # Reset count file to not exist or be 0
    if count_file.exists():
        count_file.unlink()

    ok = orch._auto_commit_accepted(sd, task_c, task_id_c)
    assert ok is False, "Case (C): Expected commit to be refused when flag is OFF"
    assert not count_file.exists(), "Case (C): Count file should not have been created/incremented"

    # 4. CASE (D): operator decision file grants -> commit lands but count NOT incremented.
    task_id_d = "taskD"
    (sd / "output" / f"{task_id_d}.py").write_text("def f():\n    return 5\n")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg_common)

    # Write operator decision file
    decision_dir = sd / 'control' / 'decisions'
    decision_dir.mkdir(parents=True, exist_ok=True)
    (decision_dir / f'{task_id_d}.json').write_text(json.dumps({"decision": "approved"}), encoding="utf-8")

    task_d = {
        "task_id": task_id_d,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix"
    }

    # Set count to 1 initially
    count_file.write_text(json.dumps({"count": 1}), encoding="utf-8")

    ok = orch._auto_commit_accepted(sd, task_d, task_id_d)
    assert ok is True, "Case (D): Expected commit to succeed via operator decision file"
    
    count_data = json.loads(count_file.read_text(encoding="utf-8"))
    assert count_data.get("count") == 1, f"Case (D): Count should remain 1 (no auto-approve increment), got {count_data.get('count')}"

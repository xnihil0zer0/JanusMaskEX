"""Oracle for security INV9: capability gate on auto-approve content.

RED on HEAD: the content gate does not exist, so Case (A) commits the eval patch.

Anti-overcorrection: Case (B) (benign .patches.json) and Case (B2) (benign
whole-file .py artifact -- the EXACT form the consult-ceiling fixture uses,
state/output/<id>.py with NO .patches.json) must STILL commit under auto-approve
on both HEAD and the fixed tree. B2 guards against the regression where the gate
only handled .patches.json and fail-closed on its absence, wrongly refusing the
benign consult-ceiling auto-approve.
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


def _cfg(flag_on: bool):
    return {
        "autowork": {
            "auto_approve_sensitive_harness": flag_on,
            "auto_approve_sensitive_ceiling": 3,
        },
        "agent_sandbox": {"bwrap": False},
    }


def _setup_marker(repo, sd, secret_file, task_id):
    slug = f"selfheal_{task_id}"
    brief_path = repo / f"brief_hooks_{slug}.md"
    brief_content = f"# Objective\nFix test_author.py {task_id}\n".encode()
    brief_path.write_bytes(brief_content)
    _mint_marker(sd, slug, task_id, brief_content, secret_file)


def _task(task_id):
    return {
        "task_id": task_id,
        "files_touched": ["harness/test_author.py"],
        "verification_command": "true",
        "meta_task_type": "harness_self_fix",
    }


def _count(sd):
    count_file = sd / "control" / "autowork" / "auto_approve_count.json"
    if not count_file.exists():
        return 0
    return json.loads(count_file.read_text(encoding="utf-8")).get("count", 0)


def test_sec_inv9_case_a_eval_refused(test_env, monkeypatch) -> None:
    """Case (A) RED-on-HEAD: a .patches.json whose new source calls eval(...)
    must be REFUSED under the auto-approve flow (no commit, count NOT bumped).
    On HEAD there is no content gate, so the eval patch is auto-approved and
    committed -> ok is True -> this assertion fails -> RED."""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskA"
    _setup_marker(repo, sd, secret_file, task_id)

    patches = [{
        "file": "harness/test_author.py",
        "kind": "symbol",
        "name": "f",
        "code": "def f():\n    eval('2')\n",
    }]
    (sd / "output" / f"{task_id}.patches.json").write_text(json.dumps(patches), encoding="utf-8")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(True))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)

    assert ok is False, "Case (A): auto-commit must be refused due to dangerous eval capability"
    assert _count(sd) == 0, "Case (A): auto_approve_count must NOT be incremented for a refused patch"


def test_sec_inv9_case_b_benign_patches_accepted(test_env, monkeypatch) -> None:
    """Case (B) anti-overcorrection: a benign .patches.json (new import + def,
    no dangerous capability) under auto-approve STILL commits, count -> 1.
    Must pass on BOTH HEAD and fixed tree."""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskB"
    _setup_marker(repo, sd, secret_file, task_id)

    patches = [{
        "file": "harness/test_author.py",
        "kind": "symbol",
        "name": "f",
        "code": "import time\ndef f():\n    return 2\n",
    }]
    (sd / "output" / f"{task_id}.patches.json").write_text(json.dumps(patches), encoding="utf-8")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(True))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)
    assert ok is True, "Case (B): benign .patches.json must be accepted"
    assert _count(sd) == 1, "Case (B): count must be 1"


def test_sec_inv9_case_b2_benign_py_accepted(test_env, monkeypatch) -> None:
    """Case (B2) REGRESSION GUARD: the consult-ceiling fixture stages a
    whole-file `state/output/<id>.py` artifact (NO .patches.json). A benign one
    must STILL commit under auto-approve (count -> 1). This is the EXACT artifact
    form test_p10b_consult_ceiling uses; it asserts the gate inspects the .py
    form and does NOT fail-closed merely because .patches.json is absent.
    Must pass on BOTH HEAD and fixed tree."""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskB2"
    _setup_marker(repo, sd, secret_file, task_id)

    # Whole-file .py artifact (no .patches.json) -- the consult-ceiling form.
    (sd / "output" / f"{task_id}.py").write_text("def f():\n    return 2\n")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(True))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)
    assert ok is True, "Case (B2): benign whole-file .py auto-approve must still commit (no .patches.json regression)"
    assert _count(sd) == 1, "Case (B2): count must be 1"


def test_sec_inv9_case_b3_py_eval_refused(test_env, monkeypatch) -> None:
    """Case (B3): a whole-file `.py` artifact carrying eval(...) must ALSO be
    refused under auto-approve -- proving the gate inspects the .py form for
    danger, not just .patches.json. (Not the clean RED; on HEAD this commits.)"""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskB3"
    _setup_marker(repo, sd, secret_file, task_id)

    (sd / "output" / f"{task_id}.py").write_text("def f():\n    eval('2')\n    return 2\n")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(True))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)
    assert ok is False, "Case (B3): eval in a whole-file .py auto-approve must be refused"
    assert _count(sd) == 0, "Case (B3): count must NOT be incremented"


def test_sec_inv9_case_c_operator_approved_danger_allowed(test_env, monkeypatch) -> None:
    """Case (C): when the operator decision file grants the apply, the gate is
    NOT consulted -- eval is allowed to commit, and the auto-approve ceiling is
    NOT incremented."""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskC"
    patches = [{
        "file": "harness/test_author.py",
        "kind": "symbol",
        "name": "f",
        "code": "def f():\n    eval('2')\n",
    }]
    (sd / "output" / f"{task_id}.patches.json").write_text(json.dumps(patches), encoding="utf-8")

    decision_dir = sd / "control" / "decisions"
    decision_dir.mkdir(parents=True, exist_ok=True)
    (decision_dir / f"{task_id}.json").write_text(json.dumps({"decision": "approved"}), encoding="utf-8")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(True))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)
    assert ok is True, "Case (C): operator-approved eval patch must be allowed"
    assert _count(sd) == 0, "Case (C): count must remain 0 (no auto-approve increment)"


def test_sec_inv9_case_d_flag_off_rejected(test_env, monkeypatch) -> None:
    """Case (D): flag off -> no auto-approve grant -> refused (gate irrelevant)."""
    repo, sd, secret_file, tmp_path = test_env

    task_id = "taskD"
    _setup_marker(repo, sd, secret_file, task_id)

    patches = [{
        "file": "harness/test_author.py",
        "kind": "symbol",
        "name": "f",
        "code": "def f():\n    return 3\n",
    }]
    (sd / "output" / f"{task_id}.patches.json").write_text(json.dumps(patches), encoding="utf-8")

    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _cfg(False))

    ok = orch._auto_commit_accepted(sd, _task(task_id), task_id)
    assert ok is False, "Case (D): auto-commit must be refused because the flag is OFF"

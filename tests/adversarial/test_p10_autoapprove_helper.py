"""Oracle for P10-A2: net-new auto-approve eligibility helper.

RED on HEAD: harness/orchestrator.py does not contain the helper.
"""
from __future__ import annotations

import json
import hashlib
import hmac
import os
import pathlib
import time
import pytest

import harness.orchestrator as orchestrator
import harness.selfheal as sh

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

def test_p10_autoapprove_helper(tmp_path, monkeypatch) -> None:
    # 1. Clean assertion that the helper exists on orchestrator.
    # On HEAD, this will fail cleanly, making the test RED on parent.
    assert hasattr(orchestrator, '_auto_approve_sensitive_eligible'), (
        "orchestrator._auto_approve_sensitive_eligible helper is missing"
    )

    helper = getattr(orchestrator, '_auto_approve_sensitive_eligible')

    # Setup temp environment paths
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create a dummy self-heal brief in repo_root
    tid = "test_task_id"
    slug = f"selfheal_{tid}"
    brief_path = repo_root / f"brief_hooks_{slug}.md"
    brief_content = b"# Objective\nFix something\n"
    brief_path.write_bytes(brief_content)

    # Monkeypatch the secret path to a temp file
    secret_file = tmp_path / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))

    # Generate the secret using selfheal's secret helper
    sh._selfheal_secret()

    # Mint the provenance marker for this brief
    _mint_marker(state_dir, slug, tid, brief_content, secret_file)

    # Base valid config and task inputs
    config = {
        "autowork": {
            "auto_approve_sensitive_harness": True,
            "auto_approve_sensitive_ceiling": 3
        }
    }
    task = {
        "meta_task_type": "harness_self_fix"
    }

    # Case 1: Base successful validation
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is True

    # Case 2: Config flag auto_approve_sensitive_harness is False (flag off -> False)
    cfg_off = {
        "autowork": {
            "auto_approve_sensitive_harness": False,
            "auto_approve_sensitive_ceiling": 3
        }
    }
    assert helper(state_dir, task, tid, ["harness/test_author.py"], cfg_off, repo_root=repo_root) is False

    # Case 3: Config flag auto_approve_sensitive_harness is missing (default-deny -> False)
    cfg_missing = {"autowork": {"auto_approve_sensitive_ceiling": 3}}
    assert helper(state_dir, task, tid, ["harness/test_author.py"], cfg_missing, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/test_author.py"], {}, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/test_author.py"], None, repo_root=repo_root) is False

    # Case 4: Invalid task metadata (not harness_self_fix -> False)
    task_invalid = {"meta_task_type": "refactor"}
    assert helper(state_dir, task_invalid, tid, ["harness/test_author.py"], config, repo_root=repo_root) is False

    # Case 5: Path is deny-listed (in NEVER-AUTO-APPROVE set -> False)
    assert helper(state_dir, task, tid, ["harness/agent_jail.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/dbus_proxy.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/paths.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/git_integration.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/orchestrator.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/interceptors.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["services/web_service.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/test_author.py", "harness/agent_jail.py"], config, repo_root=repo_root) is False

    # Case 6: Path is outside harness/ -> False
    assert helper(state_dir, task, tid, ["tests/test_something.py"], config, repo_root=repo_root) is False

    # Case 7: Path contains '..' -> False
    assert helper(state_dir, task, tid, ["harness/../services/web.py"], config, repo_root=repo_root) is False
    assert helper(state_dir, task, tid, ["harness/agent_jail.py/../test_author.py"], config, repo_root=repo_root) is False

    # Case 8: Missing / Invalid provenance marker -> False
    assert helper(state_dir, task, "unknown_task_id", ["harness/test_author.py"], config, repo_root=repo_root) is False

    # Case 9: repo_root is None -> False
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=None) is False

    # Case 10: Counter file exists and ceiling is exceeded -> False
    count_file = state_dir / "control" / "autowork" / "auto_approve_count.json"
    
    # 10a. Dict style count >= ceiling (count=3, ceiling=3)
    count_file.write_text(json.dumps({"count": 3}), encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is False

    # 10b. Int style count >= ceiling (count=3, ceiling=3)
    count_file.write_text("3", encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is False

    # 10c. Count is within ceiling (count=2, ceiling=3)
    count_file.write_text(json.dumps({"count": 2}), encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is True

    # 10d. Count is within default ceiling (count=2, default ceiling=3)
    cfg_default_ceil = {"autowork": {"auto_approve_sensitive_harness": True}}
    count_file.write_text(json.dumps({"count": 2}), encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], cfg_default_ceil, repo_root=repo_root) is True

    # 10e. Count exceeds default ceiling (count=3, default ceiling=3)
    count_file.write_text(json.dumps({"count": 3}), encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], cfg_default_ceil, repo_root=repo_root) is False

    # 10f. Counter file is garbled/malformed JSON -> False (fail-closed)
    count_file.write_text("not json", encoding="utf-8")
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is False

    # Case 11: Empty paths list -> False
    assert helper(state_dir, task, tid, [], config, repo_root=repo_root) is False

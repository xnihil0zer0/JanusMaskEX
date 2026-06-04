"""RED oracle for P10b auto-approve never-list widening.
Verifies that:
1. When everything else is valid (provenance marker, autowork.auto_approve_sensitive_harness=True, meta_task_type=harness_self_fix),
   attempts to auto-approve changes to 'harness/selfheal.py' or 'harness/autowork_daemon.py' return False.
2. Under the same conditions, changes to a benign path like 'harness/test_author.py' still return True.
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

def test_p10b_denylist_widen(tmp_path, monkeypatch) -> None:
    # Verify the helper exists
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

    # 1. Assert that a benign path returns True (sanity/regression check)
    assert helper(state_dir, task, tid, ["harness/test_author.py"], config, repo_root=repo_root) is True, (
        "Benign path harness/test_author.py should be auto-approved"
    )

    # 2. Assert that harness/selfheal.py returns False
    assert helper(state_dir, task, tid, ["harness/selfheal.py"], config, repo_root=repo_root) is False, (
        "harness/selfheal.py is sensitive and must never be auto-approved"
    )

    # 3. Assert that harness/autowork_daemon.py returns False
    assert helper(state_dir, task, tid, ["harness/autowork_daemon.py"], config, repo_root=repo_root) is False, (
        "harness/autowork_daemon.py is sensitive and must never be auto-approved"
    )

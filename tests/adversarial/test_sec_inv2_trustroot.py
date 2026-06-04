"""Self-heal §2c security INV2 oracle: validate self-heal HMAC secret-path override rejection."""
from __future__ import annotations

import json
import os
import pathlib
import time
import pytest

from harness import selfheal as sh


def test_sec_inv2_trustroot_jail_readable_override_fail_closed(tmp_path, monkeypatch) -> None:
    """(A) Set JANUSMASK_SELFHEAL_SECRET_PATH to a path under state_dir (jail-readable)
    and verify that provenance validation fails-closed (returns False)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    
    secret_file = state_dir / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))
    
    slug = "selfheal_test_task"
    brief_path = repo_root / "brief_hooks_selfheal_test_task.md"
    brief_path.write_text("# Test Brief\nFiles touched: ['harness/selfheal.py']\n", encoding="utf-8")
    
    # Pre-seed the secret and expected marker.
    # On HEAD, this causes _selfheal_provenance_valid to succeed.
    # After the INV2 hardening, it must fail-closed because the secret path override is rejected.
    secret_content = b"A" * 32
    secret_file.write_bytes(secret_content)
    
    import hashlib
    import hmac
    digest = hashlib.sha256(brief_path.read_bytes()).hexdigest()
    expected_marker = hmac.new(secret_content, (slug + ':' + digest).encode(), hashlib.sha256).hexdigest()
    
    marker_file = state_dir / 'control' / 'autowork' / 'selfheal_provenance' / f'{slug}.json'
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(json.dumps({
        'slug': slug,
        'origin_task_id': 'test_task',
        'marker': expected_marker,
        'ts': int(time.time()),
        'version': 1,
    }))
    
    assert sh._selfheal_provenance_valid(slug, brief_path, state_dir) is False, (
        "Provenance validation must FAIL if the secret override is inside state_dir (jail-readable)"
    )


def test_sec_inv2_trustroot_safe_override_succeeds(tmp_path, monkeypatch) -> None:
    """(B) Regression/anti-overcorrection check: setting override to a safe tmp path
    OUTSIDE all binds and verifying that mint+validate still succeeds."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    secret_file = safe_dir / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))
    
    slug = "selfheal_test_task"
    brief_path = repo_root / "brief_hooks_selfheal_test_task.md"
    brief_path.write_text("# Test Brief\nFiles touched: ['harness/selfheal.py']\n", encoding="utf-8")
    
    secret_content = b"B" * 32
    secret_file.write_bytes(secret_content)
    
    import hashlib
    import hmac
    digest = hashlib.sha256(brief_path.read_bytes()).hexdigest()
    expected_marker = hmac.new(secret_content, (slug + ':' + digest).encode(), hashlib.sha256).hexdigest()
    
    marker_file = state_dir / 'control' / 'autowork' / 'selfheal_provenance' / f'{slug}.json'
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(json.dumps({
        'slug': slug,
        'origin_task_id': 'test_task',
        'marker': expected_marker,
        'ts': int(time.time()),
        'version': 1,
    }))
    
    assert sh._selfheal_provenance_valid(slug, brief_path, state_dir) is True, (
        "Provenance validation must succeed when secret override is outside all binds (safe)"
    )


def test_sec_inv2_trustroot_under_repo_root_fail_closed(tmp_path, monkeypatch) -> None:
    """(C) Verify that override under repo_root resolves and fail-closed too."""
    # Find the real repo root.
    real_repo_root = pathlib.Path(__file__).resolve().parents[2]
    
    # Use a non-existent temp file name under the real repo root.
    secret_file = real_repo_root / "temp_secret_under_repo_root_test_file"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))
    
    # We expect sh._selfheal_secret to reject it and raise ValueError.
    # Note: we pass state_dir as a tmp path.
    with pytest.raises(ValueError):
        sh._selfheal_secret(state_dir=tmp_path / "state")

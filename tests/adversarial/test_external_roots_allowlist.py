"""Adversarial oracle for the external roots allowlist capability (REV23 §4 §C7/§C8).

Covers:
* Empty target directory NOT in allowlist -> refuses with BootstrapRefused, no .git or marker created.
* Empty target directory IN allowlist -> proceeds (git init runs, marker created).
* Missing allowlist file (points to nonexistent) -> refuses.
* Comment-only/empty allowlist -> refuses.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from harness import target_bootstrap as tb


def test_empty_tmp_dir_not_in_allowlist(tmp_path, monkeypatch):
    # Setup isolated agent workroot
    agent_work = tmp_path / "agentwork"
    agent_work.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_work))

    target = tmp_path / "target"
    target.mkdir()

    # Allowlist exists but contains some unrelated directory
    allowlist_file = tmp_path / "external_roots.allow"
    allowlist_file.write_text("/some/other/path\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allowlist_file))

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(target)
    
    assert not (target / ".git").exists()
    assert not (target / ".janusmask").exists()


def test_empty_tmp_dir_in_allowlist(tmp_path, monkeypatch):
    # Setup isolated agent workroot
    agent_work = tmp_path / "agentwork"
    agent_work.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_work))

    target = tmp_path / "target"
    target.mkdir()

    # Allowlist includes tmp_path (so target, being under it, is allowed)
    allowlist_file = tmp_path / "external_roots.allow"
    allowlist_file.write_text(f"# comment\n{tmp_path}\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allowlist_file))

    res = tb.bootstrap_target(target)
    assert res == target.resolve()
    assert (target / ".git").exists()
    assert (target / ".janusmask" / "bootstrap.json").is_file()


def test_missing_allowlist_file(tmp_path, monkeypatch):
    # Setup isolated agent workroot
    agent_work = tmp_path / "agentwork"
    agent_work.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_work))

    target = tmp_path / "target"
    target.mkdir()

    # Nonexistent allowlist file path
    nonexistent = tmp_path / "does_not_exist.allow"
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(nonexistent))

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(target)
    
    assert not (target / ".git").exists()
    assert not (target / ".janusmask").exists()


def test_comment_only_or_empty_allowlist(tmp_path, monkeypatch):
    # Setup isolated agent workroot
    agent_work = tmp_path / "agentwork"
    agent_work.mkdir()
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_work))

    target = tmp_path / "target"
    target.mkdir()

    # Empty/comment-only allowlist
    allowlist_file = tmp_path / "external_roots.allow"
    allowlist_file.write_text("# Only comments\n   \n# Another comment\n", encoding="utf-8")
    monkeypatch.setenv("JANUSMASK_EXTERNAL_ROOTS_ALLOW", str(allowlist_file))

    with pytest.raises(tb.BootstrapRefused):
        tb.bootstrap_target(target)
    
    assert not (target / ".git").exists()
    assert not (target / ".janusmask").exists()

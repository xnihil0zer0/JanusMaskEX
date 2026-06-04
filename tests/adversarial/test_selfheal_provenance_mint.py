"""Self-heal §2c PART 1 oracle: mint HMAC provenance marker and validate.

Asserts that harvested self-heal briefs are successfully marked with an HMAC
provenance marker and validated, and that forged briefs are rejected.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import pytest

import harness.paths as _paths
from harness import selfheal as sh
from harness import autowork_daemon as d


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str, content: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-cafef00d" / "outbox"
    sess.mkdir(parents=True, exist_ok=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(content, encoding="utf-8")


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_selfheal_provenance_verification(tmp_path, monkeypatch) -> None:
    # 1. Setup paths
    workroot = tmp_path / "agentwork"
    workroot.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "control" / "autowork").mkdir(parents=True)

    # 2. Seed configuration
    config = {"autowork": {"selfheal_auto_promote": True}}

    # 3. Seed initial fix brief in outbox
    tid = "method_d_05_taxonomy_flip"
    content = "# Title\nGoal: Resolve issues.\nFiles touched: ['harness/selfheal.py']\nCorrective constraint: constraint A\n"
    _seed_outbox(workroot, "claude", tid, content)
    _patch_workroot(monkeypatch, workroot)

    # 4. Seed realistic post-escalation blocked state
    blocked_task_path = state_dir / "tasks" / "blocked" / f"{tid}.json"
    blocked_task_data = {
        "task_id": tid,
        "meta_task_type": "harness_self_fix",
        "dependencies": ["dependency_task_id"],
        "files_touched": ["harness/selfheal.py"],
        "objective": "Resolve banned eval AST violation in selfheal.py."
    }
    blocked_task_path.write_text(json.dumps(blocked_task_data, indent=2), encoding="utf-8")

    retry_path = state_dir / "tasks" / "blocked" / f"{tid}.retry.json"
    retry_path.write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8",
    )

    exhausted_path = state_dir / "tasks" / "blocked" / f"{tid}.exhausted"
    exhausted_path.write_text("", encoding="utf-8")

    # 5. Monkeypatch the secret path to a temp file path so we don't write to real ~/.config
    secret_file = tmp_path / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))

    # Assert helper existence behaviorally to have clean assertion errors instead of import failures
    assert hasattr(sh, "_selfheal_secret"), "sh._selfheal_secret helper missing"
    assert hasattr(sh, "_selfheal_provenance_valid"), "sh._selfheal_provenance_valid helper missing"

    # 6. Drive the loop for harvest
    res = d._auto_promote(repo_root, state_dir, config)

    # 7. Verify harvested brief exists
    delivered_brief = repo_root / f"brief_hooks_selfheal_{tid}.md"
    assert delivered_brief.exists(), "Harvest should copy the brief to repo_root"

    # 8. Assert: marker file state/control/autowork/selfheal_provenance/selfheal_<tid>.json EXISTS
    slug = f"selfheal_{tid}"
    marker_file = state_dir / "control" / "autowork" / "selfheal_provenance" / f"{slug}.json"
    assert marker_file.exists(), f"Marker file {marker_file} should have been minted"

    # Verify marker json format
    marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
    assert marker_data.get("slug") == slug
    assert marker_data.get("origin_task_id") == tid
    assert "marker" in marker_data
    assert "ts" in marker_data
    assert marker_data.get("version") == 1

    # Verify secret file was created and has 0o600 permissions
    assert secret_file.exists(), "Secret file should have been minted"
    # Mode on unix: mask with 0o777 to get permission bits
    mode = secret_file.stat().st_mode & 0o777
    assert mode == 0o600, f"Secret file mode should be 0o600, got {oct(mode)}"

    # 9. Assert: validator returns True for the valid harvested brief
    assert sh._selfheal_provenance_valid(slug, delivered_brief, state_dir) is True, (
        "Provenance validation must succeed for authentic brief and marker"
    )

    # 10. Assert: forged brief returns False
    # Case A: Brief content modified (different bytes)
    forged_brief = tmp_path / "forged_brief.md"
    forged_brief.write_text("forged content", encoding="utf-8")
    assert sh._selfheal_provenance_valid(slug, forged_brief, state_dir) is False, (
        "Provenance validation must fail if brief content does not match marker HMAC"
    )

    # Case B: Missing/empty marker file
    empty_state_dir = tmp_path / "empty_state"
    assert sh._selfheal_provenance_valid(slug, delivered_brief, empty_state_dir) is False, (
        "Provenance validation must fail if marker file is missing"
    )

    # Case C: Garbled marker
    garbled_state_dir = tmp_path / "garbled_state"
    g_marker_dir = garbled_state_dir / "control" / "autowork" / "selfheal_provenance"
    g_marker_dir.mkdir(parents=True)
    g_marker_file = g_marker_dir / f"{slug}.json"
    g_marker_file.write_text("invalid json or wrong marker", encoding="utf-8")
    assert sh._selfheal_provenance_valid(slug, delivered_brief, garbled_state_dir) is False, (
        "Provenance validation must fail if marker JSON is garbled"
    )

    # Case D: Correct format but wrong marker hash
    wrong_state_dir = tmp_path / "wrong_state"
    w_marker_dir = wrong_state_dir / "control" / "autowork" / "selfheal_provenance"
    w_marker_dir.mkdir(parents=True)
    w_marker_file = w_marker_dir / f"{slug}.json"
    w_marker_data = {
        "slug": slug,
        "origin_task_id": tid,
        "marker": "wrong_hmac_hash_value",
        "ts": int(time.time()),
        "version": 1
    }
    w_marker_file.write_text(json.dumps(w_marker_data), encoding="utf-8")
    assert sh._selfheal_provenance_valid(slug, delivered_brief, wrong_state_dir) is False, (
        "Provenance validation must fail if marker hash does not match"
    )


def test_selfheal_secret_default_path_is_jail_invisible(tmp_path, monkeypatch) -> None:
    """SECURITY (C2): with NO env override, the secret must default to a path
    OUTSIDE state/ and repo_root and under ~/.config (genuinely jail-invisible
    per agent_jail.build_jail_argv, which only binds repo_root, state_dir and
    ~/.nvm|~/.gemini|~/.claude). A buggy default under state/ would let a jailed
    agent read the secret and forge markers."""
    assert hasattr(sh, "_selfheal_secret"), "sh._selfheal_secret helper missing"
    monkeypatch.delenv("JANUSMASK_SELFHEAL_SECRET_PATH", raising=False)
    # Mint into a sandboxed fake HOME so the real ~/.config is never written.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: fake_home))
    sh._selfheal_secret()
    minted = list(fake_home.rglob("selfheal_hmac_secret"))
    assert minted, "default-path secret must be minted under fake $HOME (~/.config/janusmask)"
    p = minted[0].resolve()
    cfg = (fake_home / ".config").resolve()
    assert str(p).startswith(str(cfg)), f"secret must live under ~/.config, got {p}"
    # Must NOT be under any jail-bound home subdir.
    for sub in (".nvm", ".gemini", ".claude"):
        assert not str(p).startswith(str((fake_home / sub).resolve())), (
            f"secret must not live under jail-bound ~/{sub}"
        )
    mode = minted[0].stat().st_mode & 0o777
    assert mode == 0o600, f"default secret mode should be 0o600, got {oct(mode)}"

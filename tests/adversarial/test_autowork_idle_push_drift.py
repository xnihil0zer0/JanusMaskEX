"""Adversarial tests for the truly-hands-off daemon gaps G-IDLE / G-PUSH / G-DRIFT.

- G-IDLE: the idle daemon must notice an allowlist edit or a new brief without
  waiting out the full heartbeat. ``_autowork_watch_mtime`` is the wake signal.
- G-PUSH/G-DRIFT: post-commit push + drift-pin rebase is opt-in, gated by
  ``state/control/autowork/push.enabled``. It must be a strict no-op (NO git
  invocation) when the flag is absent so a daemon stays local-only by default.
"""

from __future__ import annotations

import pathlib

from harness import autowork_daemon as ad


def _mk_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    return repo_root, state_dir


def test_push_disabled_is_strict_noop(tmp_path, monkeypatch):
    """With no push.enabled flag, _maybe_push_and_rebase_pin must not touch git."""
    repo_root, state_dir = _mk_state(tmp_path)

    def _boom(*a, **k):
        raise AssertionError(f"subprocess.run must not be called when push disabled: {a!r}")

    monkeypatch.setattr(ad.subprocess, "run", _boom)
    res = ad._maybe_push_and_rebase_pin(repo_root, state_dir)
    assert res == {"pushed": False, "reason": "disabled"}, res


def test_push_enabled_up_to_date_does_not_push(tmp_path, monkeypatch):
    """With push.enabled set but HEAD == origin/main, no `git push` is issued."""
    repo_root, state_dir = _mk_state(tmp_path)
    (state_dir / "control" / "autowork" / "push.enabled").write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    class _R:
        def __init__(self, rc=0, out="0", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def _fake_run(cmd, *a, **k):
        calls.append(cmd)
        # rev-list count returns 0 -> up to date
        if cmd[:2] == ["git", "rev-list"]:
            return _R(0, "0\n")
        raise AssertionError(f"unexpected git call when up-to-date: {cmd!r}")

    monkeypatch.setattr(ad.subprocess, "run", _fake_run)
    res = ad._maybe_push_and_rebase_pin(repo_root, state_dir)
    assert res.get("pushed") is False, res
    assert res.get("reason") == "up_to_date", res
    assert not any(c[:2] == ["git", "push"] for c in calls), calls


def test_push_enabled_ahead_pushes(tmp_path, monkeypatch):
    """With push.enabled and HEAD ahead, a `git push origin main` is issued."""
    repo_root, state_dir = _mk_state(tmp_path)
    (state_dir / "control" / "autowork" / "push.enabled").write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    class _R:
        def __init__(self, rc=0, out="", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def _fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-list"]:
            return _R(0, "1\n")
        if cmd[:3] == ["git", "push", "origin"]:
            return _R(0)
        # drift-pin rebase script + diff: pretend pin unchanged (diff rc 0)
        if cmd[:2] == ["git", "diff"]:
            return _R(0)
        return _R(0)

    monkeypatch.setattr(ad.subprocess, "run", _fake_run)
    res = ad._maybe_push_and_rebase_pin(repo_root, state_dir)
    assert res.get("pushed") is True, res
    assert any(c[:3] == ["git", "push", "origin"] for c in calls), calls


def test_idle_watch_mtime_reacts_to_allowlist_and_brief(tmp_path):
    """G-IDLE wake signal changes when the allowlist or a brief mtime changes."""
    repo_root, state_dir = _mk_state(tmp_path)
    allow = state_dir / "control" / "autowork" / "auto_promote.allowlist"
    allow.write_text("# empty\n", encoding="utf-8")
    base = ad._autowork_watch_mtime(repo_root, state_dir)

    # bump allowlist mtime well past the baseline
    import os
    future = base + 100.0
    os.utime(allow, (future, future))
    after_allow = ad._autowork_watch_mtime(repo_root, state_dir)
    assert after_allow > base, (base, after_allow)

    # a newly added brief bumps the signal again
    brief = repo_root / "brief_hooks_new.md"
    brief.write_text("# Title\nx\n", encoding="utf-8")
    os.utime(brief, (future + 100.0, future + 100.0))
    after_brief = ad._autowork_watch_mtime(repo_root, state_dir)
    assert after_brief > after_allow, (after_allow, after_brief)

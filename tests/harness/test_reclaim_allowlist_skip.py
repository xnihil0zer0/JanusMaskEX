"""RED oracle for the allowlist-skip hardening of
``harness/autowork_daemon.py::_reclaim_zombie_briefs``.

This file pins the observable contract of the allowlist-skip behaviour: an
actively-allowlisted, sha-stale, not-fully-landed brief must be KEPT (its stale
plan archived for re-planning), while an UNallowlisted sha-stale brief retains
today's eviction behaviour (the brief itself is archived).

The two cases call ``_reclaim_zombie_briefs(repo_root, state_dir, set())``
against the REAL function:

* ``test_allowlisted_stale_brief_kept_plan_archived`` is RED on HEAD because the
  current PLANNED_STALE arm archives the BRIEF in the allowlisted case too (it
  does not consult the auto_promote allowlist); it is GREEN once the
  reclaim-allowlist-skip-impl lands (brief KEPT, plan archived).
* ``test_unallowlisted_stale_brief_still_archived`` pins the unchanged HEAD
  eviction path for a non-allowlisted brief; it is a positive control that a
  mutant which fails to archive would break.

The scaffolding mirrors tests/harness/test_sha_staleness_enforcement_arm.py:
each test builds its own ``tmp_path``-based ``repo_root`` / ``state_dir`` tree
with the gate-ON ``harness/config.yaml`` and monkeypatches (via
``monkeypatch.setattr`` ONLY -- the B0 fix) the three
``harness.state_reconciler`` locator functions to hermetic tmp dirs so the
orphaned-workdir reap stays inert. No live ``state/``, no network, no
live-daemon run.

(integration: no integration test is authored here -- this oracle pins a
single-function unit contract.)
"""
from __future__ import annotations
import hashlib
import json
import pathlib
from harness.autowork_daemon import _reclaim_zombie_briefs
from harness.brief_status import compute_brief_status
_STALE_SHA = 'deadbeef' * 8

def _setup(tmp_path: pathlib.Path, monkeypatch) -> tuple:
    """Return (repo_root, state_dir, aw) freshly scaffolded under tmp_path.

    Scaffolds repo_root, state_dir=repo_root/'state' with
    tasks/{processed,processing,blocked} and control/autowork, writes the
    gate-ON repo_root/'harness'/'config.yaml' (autowork.state_reconcile: true)
    so ARM 2 (the sha-staleness sweep) is armed, and monkeypatches the three sr
    locator functions to hermetic tmp dirs via monkeypatch.setattr (NOT raw
    module-attribute assignment, which would leak process-wide) so the
    orphaned-workdir reap stays inert.
    """
    import harness.state_reconciler as sr
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = repo_root / 'state'
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    (state_dir / 'tasks' / 'processing').mkdir(parents=True)
    (state_dir / 'tasks' / 'blocked').mkdir(parents=True)
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    harness_dir = repo_root / 'harness'
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / 'config.yaml').write_text('autowork:\n  state_reconcile: true\n', encoding='utf-8')
    aw = tmp_path / 'aw'
    aw.mkdir(parents=True, exist_ok=True)
    staging = tmp_path / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sr, 'agent_workroot', lambda r: aw, raising=False)
    monkeypatch.setattr(sr, 'external_staging_root', lambda r: staging, raising=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    return (repo_root, state_dir, aw)

def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _write_brief(repo_root: pathlib.Path, slug: str, body: str) -> pathlib.Path:
    p = repo_root / f'brief_hooks_{slug}.md'
    p.write_text(body, encoding='utf-8')
    return p

def _write_plan(repo_root: pathlib.Path, slug: str, task_ids: list[str], source_brief_sha256: str | None=None) -> pathlib.Path:
    plan: dict = {'tasks': [{'task_id': t} for t in task_ids]}
    if source_brief_sha256 is not None:
        plan['source_brief_sha256'] = source_brief_sha256
    p = repo_root / f'plan_hooks_{slug}.json'
    p.write_text(json.dumps(plan), encoding='utf-8')
    return p

def _write_allowlist(state_dir: pathlib.Path, slug: str) -> pathlib.Path:
    """Write state/control/autowork/auto_promote.allowlist with one slug line.

    Matches harness.autowork_daemon._auto_promote_allowlist (one slug per line,
    '#' comments). A trailing newline keeps the line-splitting parser happy.
    """
    p = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    p.write_text(slug + '\n', encoding='utf-8')
    return p

def _active_slugs(repo_root: pathlib.Path, state_dir: pathlib.Path) -> set[str]:
    return {r['slug'] for r in compute_brief_status(repo_root, state_dir)}

def test_allowlisted_stale_brief_kept_plan_archived(tmp_path: pathlib.Path, monkeypatch) -> None:
    """An actively-allowlisted, sha-stale, not-landed brief is KEPT; its stale
    plan is archived for re-planning. RED on HEAD (HEAD archives the brief in the
    allowlisted case too)."""
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'allowarm'
    brief = _write_brief(repo_root, slug, '# allowlisted stale brief body\n')
    _write_plan(repo_root, slug, ['t1'], source_brief_sha256=_STALE_SHA)
    _write_allowlist(state_dir, slug)
    raw = json.loads((repo_root / f'plan_hooks_{slug}.json').read_text(encoding='utf-8'))
    assert raw['source_brief_sha256'] != _sha_bytes(brief.read_bytes())
    assert slug in _active_slugs(repo_root, state_dir)
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert (repo_root / f'brief_hooks_{slug}.md').exists() is True
    assert (repo_root / f'plan_hooks_{slug}.json').exists() is False
    assert slug in _active_slugs(repo_root, state_dir)

def test_unallowlisted_stale_brief_still_archived(tmp_path: pathlib.Path, monkeypatch) -> None:
    """An identical sha-stale, not-landed brief with NO allowlist entry retains
    today's eviction behaviour: the brief itself is archived (no longer at repo
    root). Positive control -- unchanged HEAD behaviour."""
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'denyarm'
    brief = _write_brief(repo_root, slug, '# unallowlisted stale brief body\n')
    _write_plan(repo_root, slug, ['t1'], source_brief_sha256=_STALE_SHA)
    assert not (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').exists()
    raw = json.loads((repo_root / f'plan_hooks_{slug}.json').read_text(encoding='utf-8'))
    assert raw['source_brief_sha256'] != _sha_bytes(brief.read_bytes())
    assert slug in _active_slugs(repo_root, state_dir)
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert (repo_root / f'brief_hooks_{slug}.md').exists() is False
    assert slug not in _active_slugs(repo_root, state_dir)
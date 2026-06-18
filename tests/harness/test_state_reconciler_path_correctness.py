"""RED oracle pinning the desired post-fix behaviour of three pure/near-pure
functions in ``harness.state_reconciler``:

* a NEW ``_running_dir`` helper that returns the canonical running directory
  ``<root>/state/control/autowork/running`` (so pidfile liveness is decided
  against that dir, never the legacy ``<root>/state/running``),
* the ``external_staging_root`` typo fix (``external_staging`` -- no leading
  underscore), and
* ``cleanup_state`` enumerating the REAL product layout (repo-root
  ``brief_hooks_*.md`` plus ``<root>/state/plans/``) rather than a nonexistent
  ``<root>/products/`` directory.

On HEAD these functions resolve the OLD paths and ``_running_dir`` does not
exist, so the unit oracles FAIL on HEAD -- correct for a test-authoring RED
oracle. Every case is hermetic under ``tmp_path`` and drives the real module
functions directly (no monkeypatching of functions under test).
"""
import os
from pathlib import Path
import harness.state_reconciler as sr
_BRIEF_CONTENT = '# Hooks brief: demo_slug\n\nThis is a hermetic repo-root product brief named brief_hooks_demo_slug.md.\nIt exists to be enumerated by cleanup_state real-product scanning.\n'
_PLAN_CONTENT = '{\n  "source_brief_sha256": "0000000000000000000000000000000000000000000000000000000000000000",\n  "tasks": [\n    {"task_id": "demo_slug"}\n  ]\n}\n'

def test_running_dir_canonical_value(tmp_path):
    """``_running_dir(root)`` pins the canonical running dir under state/control."""
    root = tmp_path
    expected = Path(root) / 'state' / 'control' / 'autowork' / 'running'
    assert Path(sr._running_dir(root)) == expected

def test_pidfile_liveness_uses_canonical_dir(tmp_path):
    """Liveness reads the canonical running dir; the legacy state/running is dead."""
    root_new = tmp_path / 'rnew'
    canonical = root_new / 'state' / 'control' / 'autowork' / 'running'
    canonical.mkdir(parents=True, exist_ok=True)
    (canonical / 'tid_x.pid').write_text(str(os.getpid()), encoding='utf-8')
    assert sr._classify_pidfile_is_live(root_new, 'tid_x') is True
    root_old = tmp_path / 'rold'
    old_dir = root_old / 'state' / 'running'
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / 'tid_x.pid').write_text(str(os.getpid()), encoding='utf-8')
    assert sr._classify_pidfile_is_live(root_old, 'tid_x') is False

def test_external_staging_no_underscore(tmp_path):
    """external_staging_root has the exact name external_staging (no underscore)."""
    root = tmp_path
    expected = Path(sr.agent_workroot(root)) / 'external_staging'
    result = Path(sr.external_staging_root(root))
    assert result == expected
    assert result.name == 'external_staging'

def test_cleanup_state_scans_real_products_not_products_dir(tmp_path):
    """report mode enumerates the repo-root brief product, not a products/ dir."""
    root = tmp_path
    assert not (root / 'products').exists()
    brief = root / 'brief_hooks_demo_slug.md'
    brief.write_text(_BRIEF_CONTENT, encoding='utf-8')
    plans_dir = root / 'state' / 'plans'
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan = plans_dir / 'demo_slug.json'
    plan.write_text(_PLAN_CONTENT, encoding='utf-8')
    status = sr.cleanup_state(root, mode='report')
    identifiers = []
    for product in status.products:
        identifiers.append(str(product.task_id))
        identifiers.append(str(product.path))
    joined = '\n'.join(identifiers)
    assert len(status.products) >= 1
    assert 'demo_slug' in joined

def test_report_mode_is_pure_read(tmp_path):
    """report mode mutates nothing: no archive dir, planted products stay put."""
    root = tmp_path
    brief = root / 'brief_hooks_demo_slug.md'
    brief.write_text(_BRIEF_CONTENT, encoding='utf-8')
    plans_dir = root / 'state' / 'plans'
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan = plans_dir / 'demo_slug.json'
    plan.write_text(_PLAN_CONTENT, encoding='utf-8')
    sr.cleanup_state(root, mode='report')
    assert not (root / '_autowork_archive').exists()
    assert brief.exists()
    assert plan.exists()

def test_staging_guard_unweakened_under_agent_workroot(tmp_path):
    """external_staging_root stays a direct child of agent_workroot (guard intact)."""
    root = tmp_path
    aw = Path(sr.agent_workroot(root))
    staging = Path(sr.external_staging_root(root))
    assert staging.parent == aw
    assert sr._reap_is_at_or_under(staging, aw)
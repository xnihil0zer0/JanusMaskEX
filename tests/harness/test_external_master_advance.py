"""RED oracle for gap #2 (NGv2 rebuild): accumulation across dependent external
children.

Accepted external output lands on ``janusmask/work`` via ref-update, but the
staging worktree detaches from the checked-out branch, which JM never advances --
so a DEPENDENT child cannot see a prior child's output. Fix: in
``merge_staging_to_parent``, for a JM-OWNED external repo (valid
``.janusmask/bootstrap.json`` marker), ALSO fast-forward the checked-out branch to
the accepted commit. Gated on the marker so a FOREIGN repo's branch is never
advanced; ff-only so it is non-destructive.
"""
import json
import subprocess

from harness import git_integration
from harness.git_integration import merge_staging_to_parent
from harness.paths import _target_is_self


def _git(args, cwd):
    return subprocess.run(['git', *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def _init_external(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(['init', '-q', '-b', 'main'], path)
    _git(['config', 'user.name', 'T'], path)
    _git(['config', 'user.email', 't@janusmask.local'], path)
    (path / 'seed.txt').write_text('seed\n', encoding='utf-8')
    _git(['add', '-A'], path)
    _git(['commit', '-q', '-m', 'seed'], path)
    _git(['branch', 'janusmask/work'], path)
    assert _target_is_self(str(path)) is False


def _write_marker(path):
    mp = path / '.janusmask' / 'bootstrap.json'
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps({'owner': 'janusmask', 'schema': 1}), encoding='utf-8')


def _make_staging_commit(parent):
    # sibling placement satisfies create_staging_worktree's sibling rule
    staging = parent.parent / (parent.name + '_staging')
    git_integration.create_staging_worktree(str(staging), parent_root=parent)
    (staging / 'built.py').write_text('def f():\n    return 1\n', encoding='utf-8')
    _git(['add', '-A'], staging)
    _git(['commit', '-q', '-m', 'built'], staging)
    sha = _git(['rev-parse', 'HEAD'], staging).stdout.strip()
    return staging, sha


def test_marked_external_advances_checked_out_branch(tmp_path):
    parent = (tmp_path / 'owned').resolve()
    _init_external(parent)
    _write_marker(parent)
    staging, sha = _make_staging_commit(parent)

    merge_staging_to_parent(staging, parent_root=parent, working_dir=str(parent))

    # janusmask/work advanced (existing behavior)...
    assert _git(['rev-parse', 'refs/heads/janusmask/work'], parent).stdout.strip() == sha
    # ...AND the checked-out branch (main) fast-forwarded to the same commit.
    assert _git(['rev-parse', 'HEAD'], parent).stdout.strip() == sha
    assert _git(['rev-parse', '--abbrev-ref', 'HEAD'], parent).stdout.strip() == 'main'
    assert (parent / 'built.py').exists()  # working tree updated by the ff


def test_unmarked_external_leaves_checked_out_branch_untouched(tmp_path):
    parent = (tmp_path / 'foreign').resolve()
    _init_external(parent)  # NO JM marker -> foreign
    head_before = _git(['rev-parse', 'HEAD'], parent).stdout.strip()
    staging, sha = _make_staging_commit(parent)

    merge_staging_to_parent(staging, parent_root=parent, working_dir=str(parent))

    # janusmask/work still advances...
    assert _git(['rev-parse', 'refs/heads/janusmask/work'], parent).stdout.strip() == sha
    # ...but the checked-out branch is NEVER touched for a foreign repo.
    assert _git(['rev-parse', 'HEAD'], parent).stdout.strip() == head_before
    assert not (parent / 'built.py').exists()

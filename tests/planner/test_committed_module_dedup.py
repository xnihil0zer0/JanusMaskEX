"""RED oracle for the committed-module clobber guard in normalize_plan.

PRIMARY clobber root cause: the planner decomposes each brief in isolation
and only dedups test_authoring oracles -- never impl ``files_touched``.  It
therefore emits impl tasks targeting modules ALREADY COMMITTED in the
(possibly external) target tree, silently overwriting them with NO oracle to
catch the regression (evidence: ``67dc8d0`` overwrote ``ngv2/workers/report.py``
already built by ``8c5198c``).

The fix adds a conservative repo_root-aware guard to ``normalize_plan``: for
each impl task, for each rel path in ``files_touched``, if the module already
EXISTS at HEAD in the resolved target root (``git cat-file -e HEAD:<rel>``
succeeds), the task is a RE-BUILD clobber and is DROPPED together with its
paired test_authoring oracle, surfacing the telemetry marker
``duplicate_module_skipped``.

CRITICAL caveat pinned below: a legitimate fix-forward EDIT of an existing
module -- one with NO paired (re-creating) test_authoring oracle in the same
plan -- must STILL be allowed (KEEP).  The drop fires only on a whole-file /
re-build impl (module-in-HEAD AND a paired test_authoring oracle re-creating
that same module in this plan), never on every touch of an existing file.

The seam is the real ``git cat-file -e HEAD:<rel>`` HEAD-existence check run
in the resolved target root, so these tests build a REAL git repo under
``tmp_path`` and commit (or omit) the module to exercise HEAD membership --
working-tree presence alone must NOT trigger the drop.
"""
import subprocess
import pytest
from harness.planner.plan_normalizer import normalize_plan


def _git(args, cwd):
    subprocess.run(['git'] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A real git repo with pkg/mod.py committed at HEAD (a DIFFERENT brief
    already built this module). The working tree also contains pkg/other.py
    UNCOMMITTED, so HEAD-membership (not working-tree presence) is exercised."""
    _git(['init', '-q'], tmp_path)
    _git(['config', 'user.email', 't@t'], tmp_path)
    _git(['config', 'user.name', 't'], tmp_path)
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'mod.py').write_text('def f():\n    return 1\n')
    _git(['add', 'pkg/mod.py'], tmp_path)
    _git(['commit', '-q', '-m', 'prior brief built pkg/mod.py'], tmp_path)
    return tmp_path


def _impl(task_id, relpath, vcmd, meta='io_adapter', deps=None):
    return {
        'task_id': task_id,
        'title': 'impl ' + relpath,
        'meta_task_type': meta,
        'priority': 'high',
        'dependencies': list(deps or []),
        'files_touched': [relpath],
        'verification_command': vcmd,
    }


def _oracle(task_id, target, oracle_file, deps=None):
    return {
        'task_id': task_id,
        'title': 'oracle for ' + target,
        'meta_task_type': 'test_authoring',
        'priority': 'high',
        'dependencies': list(deps or []),
        'mutation_target': target,
        'files_touched': [oracle_file],
        'verification_command': 'python -m pytest ' + oracle_file + ' -q',
    }


# ---------------------------------------------------------------------------
# (a) DROP: impl re-creates a module ALREADY committed at HEAD (from a
#     different brief), paired with a test_authoring oracle that re-builds the
#     same module -> BOTH impl and its paired oracle are dropped, surfacing
#     the duplicate_module_skipped marker.
# ---------------------------------------------------------------------------
def test_committed_module_rebuild_impl_and_paired_oracle_dropped(repo):
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('REBUILD_IMPL', 'pkg/mod.py',
                  'python -m pytest tests/pkg/test_mod_rebuild.py -q'),
            _oracle('REBUILD_ORACLE', 'pkg.mod',
                    'tests/pkg/test_mod_rebuild.py'),
        ],
    }
    out = normalize_plan(plan, repo_root=repo)
    ids = {t['task_id'] for t in out['tasks']}
    # the impl that would clobber the already-committed module is dropped...
    assert 'REBUILD_IMPL' not in ids, 'clobbering impl must be dropped'
    # ...together with its paired (re-creating) oracle.
    assert 'REBUILD_ORACLE' not in ids, 'paired oracle must be dropped too'
    # telemetry marker surfaced somewhere on the plan.
    blob = repr(out)
    assert 'duplicate_module_skipped' in blob, \
        'duplicate_module_skipped marker must be surfaced'


# ---------------------------------------------------------------------------
# (b) KEEP: a genuinely-NEW module (not present at HEAD) -> impl + oracle KEPT.
# ---------------------------------------------------------------------------
def test_new_module_not_in_head_is_kept(repo):
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('NEW_IMPL', 'pkg/brand_new.py',
                  'python -m pytest tests/pkg/test_brand_new.py -q'),
            _oracle('NEW_ORACLE', 'pkg.brand_new',
                    'tests/pkg/test_brand_new.py'),
        ],
    }
    out = normalize_plan(plan, repo_root=repo)
    ids = {t['task_id'] for t in out['tasks']}
    assert 'NEW_IMPL' in ids, 'new-module impl must be kept'
    assert 'NEW_ORACLE' in ids, 'new-module oracle must be kept'
    assert 'duplicate_module_skipped' not in repr(out)


# ---------------------------------------------------------------------------
# (c) KEEP (fix-forward): an EDIT of a module that exists at HEAD, with NO
#     paired (re-creating) test_authoring oracle in the same plan, is a
#     legitimate same-brief fix-forward and must be KEPT.
# ---------------------------------------------------------------------------
def test_fix_forward_edit_of_existing_module_is_kept(repo):
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('FIXFWD_IMPL', 'pkg/mod.py',
                  'python -m pytest tests/pkg/test_mod.py -q'),
        ],
    }
    out = normalize_plan(plan, repo_root=repo)
    ids = {t['task_id'] for t in out['tasks']}
    assert 'FIXFWD_IMPL' in ids, \
        'fix-forward edit (no paired re-creating oracle) must be kept'
    assert 'duplicate_module_skipped' not in repr(out)


# ---------------------------------------------------------------------------
# (d) conservative no-op: repo_root=None -> no filesystem/git access, the
#     plan is returned byte-identical (the clobbering impl survives because the
#     guard cannot run without a resolved root).
# ---------------------------------------------------------------------------
def test_repo_root_none_is_strict_noop():
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('REBUILD_IMPL', 'pkg/mod.py',
                  'python -m pytest tests/pkg/test_mod_rebuild.py -q'),
            _oracle('REBUILD_ORACLE', 'pkg.mod',
                    'tests/pkg/test_mod_rebuild.py'),
        ],
    }
    out = normalize_plan(plan, repo_root=None)
    ids = {t['task_id'] for t in out['tasks']}
    assert 'REBUILD_IMPL' in ids
    assert 'REBUILD_ORACLE' in ids
    assert 'duplicate_module_skipped' not in repr(out)


# ---------------------------------------------------------------------------
# (e) dependents of a dropped clobber-impl are rewired -- no dangling
#     dependency reference to the removed task is left behind.
# ---------------------------------------------------------------------------
def test_dependents_of_dropped_clobber_rewired(repo):
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('REBUILD_IMPL', 'pkg/mod.py',
                  'python -m pytest tests/pkg/test_mod_rebuild.py -q'),
            _oracle('REBUILD_ORACLE', 'pkg.mod',
                    'tests/pkg/test_mod_rebuild.py'),
            # a downstream NEW-module impl that (wrongly) depended on the
            # clobber-impl; after the drop it must carry no dangling ref.
            _impl('DOWNSTREAM_IMPL', 'pkg/brand_new.py',
                  'python -m pytest tests/pkg/test_brand_new.py -q',
                  deps=['REBUILD_IMPL']),
        ],
    }
    out = normalize_plan(plan, repo_root=repo)
    by_id = {t['task_id']: t for t in out['tasks']}
    assert 'DOWNSTREAM_IMPL' in by_id, 'downstream new-module impl must survive'
    assert 'REBUILD_IMPL' not in by_id['DOWNSTREAM_IMPL'].get('dependencies', []), \
        'dropped clobber-impl id must be removed from dependents'

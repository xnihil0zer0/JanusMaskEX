"""Oracle for the committed-module clobber guard in normalize_plan.

PRIMARY clobber root cause: the planner decomposes each brief in isolation
and only dedups test_authoring oracles -- never impl ``files_touched``.  It
therefore emits impl tasks targeting modules ALREADY COMMITTED in the
(possibly external) target tree, silently overwriting them with NO oracle to
catch the regression (evidence: ``67dc8d0`` overwrote ``ngv2/workers/report.py``
already built by ``8c5198c``).

The guard adds a conservative repo_root-aware pass to ``normalize_plan``: for
each impl task, for each rel path in ``files_touched``, if the module already
EXISTS at HEAD in the resolved target root (``git cat-file -e HEAD:<rel>``
succeeds) AND a paired test_authoring oracle re-creates that same module, it is
an accidental RE-BUILD clobber and is DROPPED together with that oracle,
surfacing the telemetry marker ``duplicate_module_skipped``.

KEYSTONE red-pair refinement: an impl that re-creates a module present at HEAD
but is VERIFIED BY its paired oracle's OWN authored test file is NOT an
accidental clobber -- it is a deliberate fix-forward (a "red-pair": the impl is
gated by the new RED oracle it ships with).  Such a pair must be KEPT by both
normalizer passes.  The accidental-clobber drop still fires when the impl is
verified by a DIFFERENT / pre-existing committed test (the genuine-redundancy
case, pinned in test_dedupe_precommitted_oracle.py).

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
    already built this module), so HEAD-membership (not working-tree presence)
    is exercised by the guard."""
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
# (a) KEEP (red-pair fix-forward): an impl re-creates a module present at HEAD
#     but is VERIFIED BY its paired oracle's OWN authored test file -- a
#     deliberate fix-forward (red-pair), so BOTH the impl and its oracle are
#     KEPT and NO duplicate_module_skipped marker is surfaced. (The accidental
#     clobber drop -- impl verified by a different/pre-existing test -- is
#     pinned by the sibling genuine-redundancy oracle, which still drops.)
# ---------------------------------------------------------------------------
def test_committed_module_rebuild_with_verified_oracle_is_kept_redpair(repo):
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
    # the impl is verified by the oracle's OWN file -> red-pair fix-forward -> KEPT
    assert 'REBUILD_IMPL' in ids, 'red-pair fix-forward impl must be kept'
    assert 'REBUILD_ORACLE' in ids, 'red-pair verified oracle must be kept'
    # no accidental-clobber marker for a deliberate red-pair.
    assert 'duplicate_module_skipped' not in repr(out), \
        'a verified red-pair must not surface duplicate_module_skipped'


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
#     plan is returned byte-identical.
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
# (e) dependents of a KEPT red-pair impl keep their dependency intact -- the
#     red-pair impl survives (it is verified by its own paired oracle), so
#     nothing is dropped and no rewire occurs.
# ---------------------------------------------------------------------------
def test_dependents_of_kept_redpair_clobber_preserved(repo):
    plan = {
        'plan_kind': 'implementation',
        'tasks': [
            _impl('REBUILD_IMPL', 'pkg/mod.py',
                  'python -m pytest tests/pkg/test_mod_rebuild.py -q'),
            _oracle('REBUILD_ORACLE', 'pkg.mod',
                    'tests/pkg/test_mod_rebuild.py'),
            # a downstream NEW-module impl that depends on the red-pair impl;
            # since the red-pair impl is KEPT, the dependency must be preserved.
            _impl('DOWNSTREAM_IMPL', 'pkg/brand_new.py',
                  'python -m pytest tests/pkg/test_brand_new.py -q',
                  deps=['REBUILD_IMPL']),
        ],
    }
    out = normalize_plan(plan, repo_root=repo)
    by_id = {t['task_id']: t for t in out['tasks']}
    assert 'REBUILD_IMPL' in by_id, 'kept red-pair impl must survive'
    assert 'DOWNSTREAM_IMPL' in by_id, 'downstream new-module impl must survive'
    assert 'REBUILD_IMPL' in by_id['DOWNSTREAM_IMPL'].get('dependencies', []), \
        'dependency on a KEPT red-pair impl must be preserved'

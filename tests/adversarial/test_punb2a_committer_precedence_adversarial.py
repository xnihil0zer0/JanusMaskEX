"""P-UNB2(a) RED oracle: committer precedence / files.json synthesis corruption.

Reproduces the prior hand-land root cause in
``harness/git_integration.commit_accepted_output``:

For a SELF target (working_dir absent/None -> ``_target_is_self`` True) on a
``partial_edit`` task, ``state/output/<id>.py`` holds the RAW
``__JANUSMASK_PATCHES__`` literal (not real file content) and the real edit
lives in ``state/output/<id>.patches.json``. When an untracked ``tests/test_*.py``
file is also present, the ``if _is_self:`` block synthesizes a
``<id>.files.json`` manifest SEEDED FROM the raw ``<id>.py`` literal, and the
committer precedence prefers ``.files.json`` over ``.patches.json`` -- so the
``__JANUSMASK_PATCHES__`` literal is written verbatim into the target file,
corrupting it.

DETERMINISTIC OUTCOME (must hold after fix): the committed target file must
NEVER contain the ``__JANUSMASK_PATCHES__`` marker; the patch must be applied
instead. This test FAILS on HEAD (proving the bug) and would pass after the fix
(patches sidecar takes precedence; synthesized manifest is not seeded from the
raw literal).
"""
import json
import subprocess
import pathlib
import pytest

from harness import git_integration


def _git(args, cwd):
    subprocess.run(['git'] + args, cwd=str(cwd), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _git(['init', '-q'], root)
    _git(['config', 'user.email', 'punb2a@test'], root)
    _git(['config', 'user.name', 'punb2a'], root)
    # tracked target file (non-sensitive so no operator-approval gate needed;
    # _target_is_self keys on working_dir, not on this path, so the _is_self
    # untracked-detection path still fires).
    pkg = root / 'pkg'
    pkg.mkdir()
    target = pkg / 'mod.py'
    target.write_text(
        'def greet(name):\n'
        '    return "hi " + name\n',
        encoding='utf-8',
    )
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    # tests/ must already be a TRACKED directory so a later untracked
    # tests/test_*.py file is reported individually by `git status --porcelain
    # tests/` (a wholly-untracked dir is reported as `?? tests/`, which does NOT
    # match the tests/test_*.py fnmatch and never triggers the synthesis).
    tests_dir = root / 'tests'
    tests_dir.mkdir()
    (tests_dir / 'test_existing_punb2a.py').write_text(
        'def test_existing():\n    assert True\n', encoding='utf-8')
    _git(['add', '-A'], root)
    _git(['commit', '-q', '-m', 'init'], root)
    return root, target


def test_partial_edit_patches_not_overwritten_by_files_json_literal(repo, tmp_path):
    root, target = repo
    task_id = 'rev26_punb2a_demo'

    # --- state/output sidecars exactly as the synthesis/promotion layer emits ---
    # state_dir lives INSIDE the repo so the _is_self block's
    # `git rev-parse --show-toplevel` (cwd=state_dir) resolves (mirrors the real
    # pipeline, where state/ is inside the JanusMask repo).
    state_dir = root / 'state'
    out_dir = state_dir / 'output'
    out_dir.mkdir(parents=True)

    # The real edit: replace the greet() symbol via a patch.
    new_symbol = 'def greet(name):\n    return "HELLO " + name\n'
    patches = [{
        'file': 'pkg/mod.py',
        'kind': 'symbol',
        'name': 'greet',
        'code': new_symbol,
    }]
    (out_dir / f'{task_id}.patches.json').write_text(
        json.dumps(patches, indent=2), encoding='utf-8')

    # On a partial_edit task, <id>.py is the RAW __JANUSMASK_PATCHES__ literal
    # (this is what _save_final_output persisted -- the submission text).
    patches_literal = (
        '__JANUSMASK_PATCHES__ = [\n'
        '    {\n'
        '        "file": "pkg/mod.py",\n'
        '        "kind": "symbol",\n'
        '        "name": "greet",\n'
        '        "code": "def greet(name):\\n    return \\"HELLO \\" + name\\n",\n'
        '    },\n'
        ']\n'
    )
    (out_dir / f'{task_id}.py').write_text(patches_literal, encoding='utf-8')

    # A NEW untracked test file under the already-tracked tests/ dir -> reported
    # individually by `git status --porcelain tests/` -> triggers the _is_self
    # files.json synthesis branch that seeds the manifest from <id>.py (literal).
    (root / 'tests' / 'test_greet_punb2a_new.py').write_text(
        'def test_greet():\n    assert True\n', encoding='utf-8')

    result = git_integration.commit_accepted_output(
        task_id,
        str(target),
        state_dir,
        worktree_root=root,
        meta_task_type='harness_self_fix',
        approval_ok=True,
        working_dir=None,  # SELF
    )

    committed_text = target.read_text(encoding='utf-8')

    # DETERMINISTIC OUTCOME: the target must never contain the raw patches
    # literal. On HEAD the synthesized files.json (seeded from <id>.py) wins
    # precedence and writes the literal verbatim -> this assertion FAILS (RED).
    assert '__JANUSMASK_PATCHES__' not in committed_text, (
        'committer wrote the raw __JANUSMASK_PATCHES__ literal into the target '
        '(files.json synthesized from <id>.py preferred over patches.json):\n'
        + committed_text[:400]
    )
    # And the real patch must have been applied.
    assert 'HELLO ' in committed_text, (
        'patches.json edit was not applied to the target:\n' + committed_text[:400]
    )

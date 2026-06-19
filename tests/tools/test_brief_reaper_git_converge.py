"""RED oracle: ``tools.brief_reaper.reap_for_task`` must converge the git working tree.

This is a self-contained pytest oracle (it does NOT import from
``tests/tools/test_brief_reaper.py``). It proves that archive-on-integrate is a
*git-converging* MOVE:

* the moved-FROM ``brief_hooks_<slug>.md`` + ``plan_hooks_<slug>.json`` deletions
  must be **staged in the index** (porcelain ``"D "`` -- index-column ``D``),
  not left as an unstaged worktree deletion (``" D"``);
* the ``_autowork_archive/`` destination must NOT show up as untracked porcelain
  noise (``?? _autowork_archive...``) because it is gitignored;
* yet the archived copies must physically exist under
  ``_autowork_archive/<stamp>/reconciled/`` -- this is a MOVE that records a
  staged deletion, never an outright delete.

Against the current (and the declared mutant) ``tools.brief_reaper`` -- which
moves files with ``shutil.move`` but never stages the deletion -- the staged-``D``
assertions FAIL (RED). They turn GREEN only once the implementation stages the
moved-from deletion.
"""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
import tools.brief_reaper as reaper
STAMP = '20260619T101010Z'

def _require_git() -> None:
    """Skip cleanly on hosts without a ``git`` binary."""
    if shutil.which('git') is None:
        pytest.skip('git binary is unavailable; skipping git-convergence oracle')

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive git in ``repo`` via ``git -C <repo> ...``."""
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True)

def _init_repo(repo: Path) -> None:
    """``git init`` + a committer identity so commits succeed in bare CI."""
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 'oracle@example.com')
    _git(repo, 'config', 'user.name', 'Reaper Oracle')
    _git(repo, 'config', 'commit.gpgsign', 'false')

def _seed(repo: Path, slug: str, task_ids) -> None:
    """Write a non-epic ``brief_hooks_<slug>.md`` + ``plan_hooks_<slug>.json`` pair."""
    (repo / f'brief_hooks_{slug}.md').write_text('# Hooks brief\n\nConverge the working tree on integrate.\n', encoding='utf-8')
    plan = {'plan_id': f'hooks_{slug}', 'plan_kind': 'build', 'tasks': [{'task_id': t} for t in task_ids]}
    (repo / f'plan_hooks_{slug}.json').write_text(json.dumps(plan), encoding='utf-8')

def _accepted(task_id: str) -> dict:
    """An integration-ledger row that counts ``task_id`` as integrated."""
    return {'task_id': task_id, 'phase': 'accepted'}

def _ledger(repo: Path, rows) -> None:
    """Seed ``state/impl_progress.jsonl`` with the given rows."""
    state = repo / 'state'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'impl_progress.jsonl').open('w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row) + '\n')

def _dest(repo: Path, stamp: str) -> Path:
    """The archive destination directory the reaper moves paperwork into."""
    return repo / '_autowork_archive' / stamp / 'reconciled'

def _status_entries(repo: Path):
    """Parse ``git status --porcelain`` into ``(index, worktree, path)`` triples.

    For an XY status line, column 0 is the INDEX column and column 1 is the
    WORKTREE column; ``"D "`` is a staged deletion, ``" D"`` an unstaged one.
    """
    out = _git(repo, 'status', '--porcelain').stdout
    entries = []
    for line in out.splitlines():
        if not line:
            continue
        index_col, worktree_col = (line[0], line[1])
        path = line[3:]
        entries.append((index_col, worktree_col, path))
    return entries

@pytest.fixture
def reaped(tmp_path):
    _require_git()
    repo = tmp_path / 'repo'
    repo.mkdir()
    _init_repo(repo)
    slug = 'converge'
    task_id = 'converge-t1'
    _seed(repo, slug, [task_id])
    (repo / '.gitignore').write_text('_autowork_archive/\n', encoding='utf-8')
    _git(repo, 'add', f'brief_hooks_{slug}.md', f'plan_hooks_{slug}.json', '.gitignore')
    _git(repo, 'commit', '-q', '-m', 'seed brief+plan+gitignore')
    _ledger(repo, [_accepted(task_id)])
    result = reaper.reap_for_task(repo, task_id, stamp=STAMP)
    return SimpleNamespace(repo=repo, slug=slug, task_id=task_id, stamp=STAMP, result=result)

def test_moved_from_brief_deletion_is_staged_in_index(reaped):
    """The moved-from brief deletion is staged ('D '), not unstaged (' D')."""
    brief = f'brief_hooks_{reaped.slug}.md'
    hits = [(idx, wt, path) for idx, wt, path in _status_entries(reaped.repo) if Path(path).name == brief]
    assert hits, f'{brief} not reported by git status --porcelain'
    idx, wt, path = hits[0]
    assert idx == 'D', f"expected staged deletion (index column 'D', i.e. 'D ') for {path}, got index={idx!r} worktree={wt!r}"

def test_moved_from_plan_deletion_is_staged_in_index(reaped):
    """The moved-from plan deletion is staged ('D '), not unstaged (' D')."""
    plan = f'plan_hooks_{reaped.slug}.json'
    hits = [(idx, wt, path) for idx, wt, path in _status_entries(reaped.repo) if Path(path).name == plan]
    assert hits, f'{plan} not reported by git status --porcelain'
    idx, wt, path = hits[0]
    assert idx == 'D', f"expected staged deletion (index column 'D', i.e. 'D ') for {path}, got index={idx!r} worktree={wt!r}"

def test_no_untracked_autowork_archive_entry_in_porcelain(reaped):
    """The gitignored archive destination must not appear as untracked noise."""
    offending = [f'{idx}{wt} {path}' for idx, wt, path in _status_entries(reaped.repo) if '_autowork_archive' in path]
    assert not offending, f"_autowork_archive must be gitignored (no '?? _autowork_archive'), but porcelain reported: {offending}"

def test_archive_copies_still_present_under_archive_dir(reaped):
    """MOVE, not delete: the archived copies must exist under the archive dir."""
    assert reaped.result == [reaped.slug]
    dest = _dest(reaped.repo, reaped.stamp)
    assert (dest / f'brief_hooks_{reaped.slug}.md').is_file(), 'archived brief copy missing -- a MOVE must preserve the bytes'
    assert (dest / f'plan_hooks_{reaped.slug}.json').is_file(), 'archived plan copy missing -- a MOVE must preserve the bytes'

def test_skips_cleanly_when_git_unavailable(monkeypatch):
    """When the git binary is absent, the oracle skips rather than errors."""
    monkeypatch.setattr(shutil, 'which', lambda *_a, **_k: None)
    with pytest.raises(pytest.skip.Exception):
        _require_git()

def test_working_tree_converges_after_reap_for_single_task_plan(reaped):
    """End-to-end convergence: staged-D brief+plan, no archive noise, moved-from gone."""
    assert reaped.result == [reaped.slug]
    by_name = {Path(path).name: (idx, wt) for idx, wt, path in _status_entries(reaped.repo)}
    brief = f'brief_hooks_{reaped.slug}.md'
    plan = f'plan_hooks_{reaped.slug}.json'
    assert brief in by_name, f'{brief} not in porcelain status'
    assert plan in by_name, f'{plan} not in porcelain status'
    assert by_name[brief][0] == 'D', f'brief deletion not staged: {by_name[brief]!r}'
    assert by_name[plan][0] == 'D', f'plan deletion not staged: {by_name[plan]!r}'
    assert not any(('_autowork_archive' in path for _i, _w, path in _status_entries(reaped.repo))), 'archive destination must stay gitignored'
    assert not (reaped.repo / brief).exists()
    assert not (reaped.repo / plan).exists()

def test_non_git_tmp_path_behaviour_unchanged_is_not_disturbed(tmp_path):
    """Regression control: non-git move behaviour is preserved by this new file."""
    repo = tmp_path / 'plain'
    repo.mkdir()
    slug = 'plain'
    task_id = 'plain-t1'
    stamp = '20260619T020202Z'
    _seed(repo, slug, [task_id])
    _ledger(repo, [_accepted(task_id)])
    result = reaper.reap_for_task(repo, task_id, stamp=stamp)
    assert result == [slug]
    dest = _dest(repo, stamp)
    assert (dest / f'brief_hooks_{slug}.md').is_file()
    assert (dest / f'plan_hooks_{slug}.json').is_file()
    assert not (repo / f'brief_hooks_{slug}.md').exists()
    assert not (repo / f'plan_hooks_{slug}.json').exists()
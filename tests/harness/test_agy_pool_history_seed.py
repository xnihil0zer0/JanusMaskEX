"""RED oracle tests for the antigravity ``history.db`` seed path.

These tests pin the expected contract of ``harness.agy_pool`` once the
Antigravity CLI history database is added to the worker-pool seed set:

* ``.gemini/antigravity-cli/history.db`` MUST be present in ``_SEED_RELS``.
* The original 7 auth/config seed entries MUST remain, in their original
  relative order (as an ordered subsequence -- new entries may be inserted
  but must not reorder the originals).
* ``agy_seed_plan`` MUST emit the correct ``(abs_src, rel_dst)`` pair for the
  history database, resolved against the operator home.

They are deliberately RED against the current implementation (which omits
``history.db``) and exercise the *real* observable behaviour of the module --
no behaviour is stubbed -- so they fail on a broken/mutant build.
"""
from __future__ import annotations
import os
import pytest
from harness import agy_pool
ORIGINAL_SEED_RELS = ('.gemini/oauth_creds.json', '.gemini/google_accounts.json', '.gemini/settings.json', '.gemini/trustedFolders.json', '.gemini/state.json', '.gemini/projects.json', '.config/gcloud/application_default_credentials.json')
HISTORY_DB_REL = '.gemini/antigravity-cli/history.db'

def test_history_db_is_in_seed_rels() -> None:
    """history.db must be one of the seeded relative paths."""
    assert HISTORY_DB_REL in agy_pool._SEED_RELS

def test_original_entries_preserved() -> None:
    """All 7 original entries remain, in their original relative order."""
    rels = list(agy_pool._SEED_RELS)
    for original in ORIGINAL_SEED_RELS:
        assert original in rels, f'missing original seed entry: {original}'
    positions = [rels.index(original) for original in ORIGINAL_SEED_RELS]
    assert positions == sorted(positions), f'original seed entries reordered: positions={positions}'
    assert len(set(positions)) == len(ORIGINAL_SEED_RELS)

def test_agy_seed_plan_fake_home() -> None:
    """agy_seed_plan yields the correct (abs_src, rel_dst) pair for history.db."""
    home = '/fake/home'
    plan = agy_pool.agy_seed_plan(home)
    expected = (os.path.join(home, HISTORY_DB_REL), HISTORY_DB_REL)
    assert expected in plan, f'history.db pair {expected!r} not produced by agy_seed_plan; got {plan!r}'

def test_seed_rels_contains_all_original_entries() -> None:
    """The seed set must be a superset of the original 7 entries."""
    assert set(ORIGINAL_SEED_RELS).issubset(set(agy_pool._SEED_RELS))

def test_seed_rels_has_no_duplicates() -> None:
    """No relative path may appear twice in the seed set."""
    rels = list(agy_pool._SEED_RELS)
    assert len(rels) == len(set(rels)), f'duplicate seed entries in {rels!r}'

def test_agy_seed_plan_covers_all_seed_rels() -> None:
    """The plan emits exactly one pair per _SEED_RELS entry, in order."""
    home = '/fake/home'
    plan = agy_pool.agy_seed_plan(home)
    assert len(plan) == len(agy_pool._SEED_RELS)
    assert [rel for _src, rel in plan] == list(agy_pool._SEED_RELS)

def test_agy_seed_plan_pairs_are_home_relative() -> None:
    """Each pair is (home-joined abs src, home-relative dst); dst stays relative."""
    home = '/fake/home'
    plan = agy_pool.agy_seed_plan(home)
    for src, rel in plan:
        assert not os.path.isabs(rel), f'rel dst leaked an absolute path: {rel!r}'
        assert src == os.path.join(home, rel)
        assert src.startswith(home)

def test_ensure_seeded_copies_existing_sources_only() -> None:
    """Only sources that exist (and whose dst is absent) are copied."""
    repo_root = '/repo'
    home = '/op/home'
    slot = 0
    present_rels = [HISTORY_DB_REL, '.gemini/settings.json']
    existing_srcs = {os.path.join(home, rel) for rel in present_rels}
    copies: list = []
    made_dirs: list = []

    def fake_exists(path: str) -> bool:
        return path in existing_srcs

    def fake_copy(src: str, dst: str) -> None:
        copies.append((src, dst))

    def fake_makedirs(path: str) -> None:
        made_dirs.append(path)
    copied = agy_pool.ensure_seeded(repo_root, slot, home=home, copy=fake_copy, exists=fake_exists, makedirs=fake_makedirs)
    expected_order = [rel for rel in agy_pool._SEED_RELS if rel in present_rels]
    assert copied == expected_order
    assert '.gemini/oauth_creds.json' not in copied
    assert len(copies) == len(expected_order)

def test_ensure_seeded_is_idempotent() -> None:
    """When every destination already exists, nothing is copied."""
    repo_root = '/repo'
    home = '/op/home'
    slot = 1
    copies: list = []

    def fake_exists(_path: str) -> bool:
        return True

    def fake_copy(src: str, dst: str) -> None:
        copies.append((src, dst))

    def fake_makedirs(_path: str) -> None:
        pass
    copied = agy_pool.ensure_seeded(repo_root, slot, home=home, copy=fake_copy, exists=fake_exists, makedirs=fake_makedirs)
    assert copied == []
    assert copies == []

def test_ensure_seeded_creates_parent_dirs() -> None:
    """Each copied destination has its parent directory created first."""
    repo_root = '/repo'
    home = '/op/home'
    slot = 2
    existing_srcs = {os.path.join(home, rel) for rel in agy_pool._SEED_RELS}
    made_dirs: list = []
    copies: list = []

    def fake_exists(path: str) -> bool:
        return path in existing_srcs

    def fake_copy(src: str, dst: str) -> None:
        copies.append((src, dst))

    def fake_makedirs(path: str) -> None:
        made_dirs.append(path)
    copied = agy_pool.ensure_seeded(repo_root, slot, home=home, copy=fake_copy, exists=fake_exists, makedirs=fake_makedirs)
    assert copied == list(agy_pool._SEED_RELS)
    for _src, dst in copies:
        assert os.path.dirname(dst) in made_dirs

def test_ensure_seeded_seeds_history_db() -> None:
    """When the operator's history.db exists, it is among the copied seeds."""
    repo_root = '/repo'
    home = '/op/home'
    slot = 3
    existing_srcs = {os.path.join(home, HISTORY_DB_REL)}

    def fake_exists(path: str) -> bool:
        return path in existing_srcs

    def fake_copy(src: str, dst: str) -> None:
        pass

    def fake_makedirs(path: str) -> None:
        pass
    copied = agy_pool.ensure_seeded(repo_root, slot, home=home, copy=fake_copy, exists=fake_exists, makedirs=fake_makedirs)
    assert HISTORY_DB_REL in copied
if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
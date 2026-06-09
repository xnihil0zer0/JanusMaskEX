"""Oracle: the project-local agy worker pool (parallelism-of-N isolation).

``harness.agy_pool`` lets up to N JanusMask *worker* agy processes run
concurrently without corrupting each other's Antigravity registry. The isolation
knob (proven empirically: 4 concurrent agy in seeded private HOMEs, zero
conflict) is a private ``$HOME`` per slot, seeded with ONLY the small
auth/config set -- NEVER the multi-GB ``~/.gemini`` cache. The contract:

  * ``pool_root(repo_root)`` -> ``<repo>/.agents/agy-pool`` (project-local),
  * ``worker_home(repo_root, slot)`` -> a private home per slot,
  * ``agy_seed_plan(home)`` -> the (src, dst-relative) auth/config files to copy
    (``~/.gemini`` oauth/account/settings/trust/state/projects + the gcloud
    ADC), each placed home-relative in the slot,
  * ``ensure_seeded(...)`` -> idempotently copy only existing, not-yet-present
    seed files (via injected copy/exists/makedirs seams),
  * ``allocate_slot(busy, size)`` -> the lowest free slot, or None when full,
  * ``worker_env(repo_root, slot, base_env)`` -> base env + private HOME +
    ``GOOGLE_GENAI_USE_GCA``.

Hermetic: injected fs seams; no real copy, no agy spawn, no network.
"""
from __future__ import annotations

import os
from pathlib import Path

from harness import agy_pool


# --- pool layout ------------------------------------------------------------

def test_pool_root_is_project_local():
    root = Path(agy_pool.pool_root("/repo"))
    assert str(root).replace("\\", "/") == "/repo/.agents/agy-pool"


def test_worker_homes_are_distinct_per_slot():
    h0 = str(agy_pool.worker_home("/repo", 0))
    h1 = str(agy_pool.worker_home("/repo", 1))
    assert h0 != h1
    assert str(agy_pool.pool_root("/repo")) in h0


# --- seed plan: small auth set, never the cache -----------------------------

def test_seed_plan_covers_auth_and_adc_not_cache():
    plan = agy_pool.agy_seed_plan("/home/u")
    srcs = [src for src, _dst in plan]
    dsts = [dst for _src, dst in plan]
    # the credential-bearing files proven necessary
    assert any(s.endswith(".gemini/oauth_creds.json") for s in srcs)
    assert any(s.endswith(".gemini/google_accounts.json") for s in srcs)
    assert any("application_default_credentials.json" in s for s in srcs)
    # destinations are home-relative (no absolute paths leaking the operator home)
    assert all(not os.path.isabs(d) for d in dsts)
    # the multi-GB cache subtrees are NOT seeded
    assert not any("/cache/" in s or s.rstrip("/").endswith(".gemini") for s in srcs)


class _FakeFS:
    def __init__(self, present):
        self.present = set(str(p) for p in present)
        self.copies = []
        self.made_dirs = []

    def exists(self, p):
        return str(p) in self.present

    def copy(self, src, dst):
        self.copies.append((str(src), str(dst)))
        self.present.add(str(dst))

    def makedirs(self, p):
        self.made_dirs.append(str(p))
        self.present.add(str(p))


def test_ensure_seeded_copies_existing_sources_only():
    home = "/home/u"
    plan = agy_pool.agy_seed_plan(home)
    present = {plan[0][0]}  # only the first source exists
    fs = _FakeFS(present)
    copied = agy_pool.ensure_seeded("/repo", 2, home=home,
                                    copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert len(fs.copies) == 1
    assert len(copied) == 1
    # the copy destination is inside slot 2's private home
    wh = str(agy_pool.worker_home("/repo", 2))
    assert all(dst.startswith(wh) for _src, dst in fs.copies)


def test_ensure_seeded_is_idempotent():
    home = "/home/u"
    plan = agy_pool.agy_seed_plan(home)
    wh = str(agy_pool.worker_home("/repo", 0))
    all_src = {src for src, _ in plan}
    all_dst = {os.path.join(wh, dst) for _src, dst in plan}
    fs = _FakeFS(all_src | all_dst)  # everything already present
    agy_pool.ensure_seeded("/repo", 0, home=home,
                           copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert fs.copies == []


# --- slot allocation --------------------------------------------------------

def test_allocate_slot_returns_lowest_free():
    assert agy_pool.allocate_slot(set(), size=4) == 0
    assert agy_pool.allocate_slot({0, 1}, size=4) == 2


def test_allocate_slot_returns_none_when_full():
    assert agy_pool.allocate_slot({0, 1, 2, 3}, size=4) is None


# --- worker env -------------------------------------------------------------

def test_worker_env_sets_private_home_and_gca():
    env = agy_pool.worker_env("/repo", 1, {"PATH": "/usr/bin"})
    assert env["HOME"] == str(agy_pool.worker_home("/repo", 1))
    assert env["GOOGLE_GENAI_USE_GCA"] == "1"
    assert env["PATH"] == "/usr/bin"          # base env preserved


def test_worker_env_does_not_mutate_base():
    base = {"PATH": "/usr/bin"}
    agy_pool.worker_env("/repo", 0, base)
    assert "HOME" not in base                  # base dict untouched

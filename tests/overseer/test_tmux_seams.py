"""Oracle: real seam construction for the claude-tmux backend.

``overseer.tmux_seams`` builds the REAL injected seams that ``run_tmux_turn``
consumes, and the per-conversation ``CLAUDE_CONFIG_DIR`` isolation that makes
parallel claude-tmux agents safe (the knob proven in a live drive: the session
transcript lands under the seeded config dir). The contract pinned here:

  * ``overseer_config_dir(repo_root, cid)`` -- a per-cid config dir OUTSIDE the
    repo (sibling of the agent work dir), so each agent's ~/.claude tree is
    private,
  * ``config_seed_plan(home)`` -- the small (src -> dst-name) auth/config set a
    fresh config dir needs (``.credentials.json``, ``settings.json`` from
    ``~/.claude``; the big ``~/.claude.json``). NOT the whole tree,
  * ``seed_config_dir(...)`` -- idempotently copy only the existing, not-yet-
    present seed files via injected ``copy``/``exists`` seams,
  * ``build_interactive_argv(...)`` -- the INTERACTIVE claude argv (``env
    CLAUDE_CONFIG_DIR=<dir> <bin> ...``): it carries --model/--tools/
    --append-system-prompt/--resume when given and NEVER the headless
    ``-p`` / ``--output-format`` flags,
  * ``make_tmux_seams(...)`` -- the bundle of real callables + derived
    ``config_dir`` / ``session`` consumed by the dispatch layer.

Hermetic: injected copy/exists fakes; the real subprocess seam is only checked
for callability, never invoked.
"""
from __future__ import annotations

import os
from pathlib import Path

from overseer import tmux_seams as tsm


# --- per-cid config dir -----------------------------------------------------

def test_config_dir_is_per_cid_and_outside_repo():
    repo = Path("/home/u/JanusMaskEX")
    cfg = Path(tsm.overseer_config_dir(repo, "conv-1"))
    # outside the repo, namespaced by cid
    assert repo not in cfg.parents
    assert "conv-1" in str(cfg)
    # two cids get distinct dirs (parallel isolation)
    assert str(tsm.overseer_config_dir(repo, "conv-1")) != str(tsm.overseer_config_dir(repo, "conv-2"))


def test_config_dir_sanitises_unsafe_cid():
    cfg = str(tsm.overseer_config_dir("/repo", "a/b c..d"))
    leaf = os.path.basename(cfg.rstrip("/"))
    assert "/" not in leaf and " " not in leaf and ".." not in leaf


# --- seed plan + seeding ----------------------------------------------------

def test_seed_plan_is_the_small_auth_set_not_the_whole_tree():
    plan = tsm.config_seed_plan("/home/u")
    dsts = {dst for _src, dst in plan}
    # the auth/config files a fresh CLAUDE_CONFIG_DIR needs
    assert ".credentials.json" in dsts
    assert ".claude.json" in dsts
    # sources are under the operator home; nothing like the 'projects' cache
    assert all("projects" not in str(src) for src, _ in plan)


class _FakeFS:
    def __init__(self, present):
        self.present = set(present)
        self.copies = []
        self.made_dirs = []

    def exists(self, p):
        return str(p) in self.present

    def copy(self, src, dst):
        self.copies.append((str(src), str(dst)))
        self.present.add(str(dst))

    def makedirs(self, p):
        # the config dir is created via this seam, never guarded on pre-existence
        self.made_dirs.append(str(p))
        self.present.add(str(p))


def test_seed_copies_existing_sources_only():
    home = "/home/u"
    plan = tsm.config_seed_plan(home)
    present = {src for src, _ in plan[:1]}  # only the first source exists
    fs = _FakeFS(present)  # note: '/cfg' is NOT present -> impl must makedirs it, not bail
    tsm.seed_config_dir("/cfg", home=home, copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert len(fs.copies) == 1  # only the existing source was copied


def test_seed_is_idempotent_skips_already_present_dst():
    home = "/home/u"
    plan = tsm.config_seed_plan(home)
    all_src = {src for src, _ in plan}
    # all sources exist AND all destinations already exist -> nothing copied
    dsts = {os.path.join("/cfg", dst) for _s, dst in plan}
    fs = _FakeFS(all_src | dsts)
    tsm.seed_config_dir("/cfg", home=home, copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert fs.copies == []


# --- interactive argv (NO headless flags) -----------------------------------

def test_interactive_argv_sets_config_dir_and_omits_headless_flags():
    argv = tsm.build_interactive_argv("/bin/claude", "/cfg")
    assert argv[0] == "env"
    assert "CLAUDE_CONFIG_DIR=/cfg" in argv
    assert "/bin/claude" in argv
    # the cost-billed headless flags must NEVER appear on the interactive path
    assert "-p" not in argv
    assert "--output-format" not in argv
    assert "--print" not in argv


def test_interactive_argv_threads_model_tools_prompt_resume():
    argv = tsm.build_interactive_argv(
        "/bin/claude", "/cfg", model="opus", tools=["Read", "Grep"],
        system_prompt="PHASE: SCOPE", session_id="sess-9")
    assert "--model" in argv and "opus" in argv
    i = argv.index("--tools")
    assert argv[i + 1] == "Read,Grep"
    j = argv.index("--append-system-prompt")
    assert argv[j + 1] == "PHASE: SCOPE"
    k = argv.index("--resume")
    assert argv[k + 1] == "sess-9"


# --- the seam bundle --------------------------------------------------------

def test_make_tmux_seams_bundle_shape():
    bundle = tsm.make_tmux_seams(
        config={"agents": {"claude": {}}}, repo_root="/repo", cid="conv-1",
        work_dir="/wd", state_dir="/st")
    for key in ("tmux_exec", "sleep", "read_text", "list_dir", "config_dir", "session"):
        assert key in bundle, f"missing seam: {key}"
    assert callable(bundle["tmux_exec"])
    assert callable(bundle["read_text"])
    assert callable(bundle["list_dir"])
    assert "conv-1" in str(bundle["config_dir"])
    assert "conv-1" in str(bundle["session"])


def test_make_tmux_seams_read_text_and_list_dir_are_real_fs(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    bundle = tsm.make_tmux_seams(
        config={}, repo_root=str(tmp_path), cid="c", work_dir=str(tmp_path), state_dir=str(tmp_path))
    assert bundle["read_text"](str(f)) == "hello"
    assert "x.txt" in bundle["list_dir"](str(tmp_path))

#!/usr/bin/env python3
"""Analytic repro for the agy_pool config-dir fix adversarial review.

Demonstrates:
  (A) RED: current ensure_seeded leaves <home>/.gemini/config ABSENT (or, when a
      0-byte ro file pre-exists from the jail's /dev/null materialization, leaves
      it a NON-DIR) on a temp home.
  (B) GREEN: the PROPOSED post-loop logic produces real config/ + config/projects/
      directories, idempotently repairs a pre-existing non-dir 0444 file, and is a
      no-op on a second run.
  (C) Regression probe: what the EXISTING hermetic tests assume (no real-disk I/O
      when HOME is empty) vs. what the fix forces.

Run:  PYTHONPATH=. python3 _autowork_scratch/agy_pool_fix_repro.py
Pure stdlib; touches only temp dirs it creates.
"""
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from harness import agy_pool  # noqa: E402


def _mk_temp_repo_and_home():
    repo = tempfile.mkdtemp(prefix="agyrepo_")
    home = tempfile.mkdtemp(prefix="agyhome_")
    return repo, home


# ---------------------------------------------------------------------------
# Reference implementation of the PROPOSED post-loop logic (mirrors the spec).
# Mounted onto a COPY of ensure_seeded so we never touch production code.
# ---------------------------------------------------------------------------
def proposed_ensure_config_dirs(wh, *, isdir, remove, makedirs):
    """Ensure <wh>/.gemini/config and .../config/projects are real dirs.

    Idempotently repairs a pre-existing NON-DIR `config` (remove 0-byte ro file,
    then mkdir the tree). Mirrors the spec's defaulted-seam contract.
    """
    config = os.path.join(wh, ".gemini", "config")
    projects = os.path.join(config, "projects")
    # repair: if `config` exists but is NOT a dir, remove it first
    if os.path.lexists(config) and not isdir(config):
        remove(config)
    makedirs(projects)  # exist_ok semantics expected at the call site


def current_state_of_config(wh):
    config = os.path.join(wh, ".gemini", "config")
    projects = os.path.join(config, "projects")
    if not os.path.lexists(config):
        return "ABSENT"
    if os.path.islink(config):
        return "SYMLINK"
    if not os.path.isdir(config):
        return f"NON-DIR (mode={stat.filemode(os.lstat(config).st_mode)}, size={os.path.getsize(config)})"
    proj = "with projects/" if os.path.isdir(projects) else "NO projects/"
    return f"DIR {proj}"


def real_makedirs(d):
    os.makedirs(d, exist_ok=True)


def main():
    print("=" * 70)
    print("PART A — RED: current ensure_seeded leaves config absent/non-dir")
    print("=" * 70)
    repo, home = _mk_temp_repo_and_home()
    try:
        slot = 0
        wh = str(agy_pool.worker_home(repo, slot))
        # Run the REAL current ensure_seeded with real seams, empty home (no srcs).
        copied = agy_pool.ensure_seeded(
            repo, slot, home=home,
            copy=shutil.copy2, exists=os.path.exists,
            makedirs=real_makedirs,
        )
        print(f"  copied={copied}")
        print(f"  config state after current ensure_seeded: {current_state_of_config(wh)}")
        assert current_state_of_config(wh) == "ABSENT", "expected config ABSENT"
        print("  RED-A1 confirmed: config dir is NOT created -> jail /dev/null materializes a non-dir")

        # Now simulate the JAIL having materialized a 0-byte 0444 file (the live w0/w1 state),
        # then re-run current ensure_seeded: it STILL does not repair it.
        gem = os.path.join(wh, ".gemini")
        os.makedirs(gem, exist_ok=True)
        cfg = os.path.join(gem, "config")
        with open(cfg, "w"):
            pass
        os.chmod(cfg, 0o444)
        print(f"  injected broken state: {current_state_of_config(wh)}")
        agy_pool.ensure_seeded(
            repo, slot, home=home,
            copy=shutil.copy2, exists=os.path.exists, makedirs=real_makedirs,
        )
        print(f"  config state after current ensure_seeded (broken pre-existing): {current_state_of_config(wh)}")
        assert "NON-DIR" in current_state_of_config(wh), "current code should NOT repair"
        print("  RED-A2 confirmed: current ensure_seeded does NOT repair a 0-byte ro config file")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)

    print()
    print("=" * 70)
    print("PART B — GREEN: proposed post-loop logic creates + repairs + idempotent")
    print("=" * 70)
    repo, home = _mk_temp_repo_and_home()
    try:
        slot = 0
        wh = str(agy_pool.worker_home(repo, slot))
        os.makedirs(os.path.join(wh, ".gemini"), exist_ok=True)

        # B1: fresh — no config at all
        proposed_ensure_config_dirs(wh, isdir=os.path.isdir, remove=os.remove, makedirs=real_makedirs)
        st = current_state_of_config(wh)
        print(f"  B1 fresh -> {st}")
        assert st == "DIR with projects/", st

        # B2: idempotent — second run is a no-op, no raise
        proposed_ensure_config_dirs(wh, isdir=os.path.isdir, remove=os.remove, makedirs=real_makedirs)
        st = current_state_of_config(wh)
        print(f"  B2 idempotent re-run -> {st}")
        assert st == "DIR with projects/", st

        # B3: repair a pre-existing 0-byte 0444 file (the live w0/w1 state)
        shutil.rmtree(os.path.join(wh, ".gemini", "config"))
        cfg = os.path.join(wh, ".gemini", "config")
        with open(cfg, "w"):
            pass
        os.chmod(cfg, 0o444)
        print(f"  B3 pre-repair injected -> {current_state_of_config(wh)}")
        proposed_ensure_config_dirs(wh, isdir=os.path.isdir, remove=os.remove, makedirs=real_makedirs)
        st = current_state_of_config(wh)
        print(f"  B3 post-repair -> {st}")
        assert st == "DIR with projects/", st
        print("  GREEN-B confirmed: creates, idempotent, repairs 0-byte 0444 non-dir")

        # B4: SAFETY — never deletes a real dir with data. Put data in config/, re-run.
        with open(os.path.join(wh, ".gemini", "config", "projects", "trust.json"), "w") as fh:
            fh.write('{"x":1}')
        proposed_ensure_config_dirs(wh, isdir=os.path.isdir, remove=os.remove, makedirs=real_makedirs)
        kept = os.path.exists(os.path.join(wh, ".gemini", "config", "projects", "trust.json"))
        print(f"  B4 real-dir-with-data preserved across re-run: {kept}")
        assert kept, "fix must NOT wipe a real config dir"
        print("  GREEN-B4 confirmed: a real config dir + its data are preserved")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)

    print()
    print("=" * 70)
    print("PART C — Regression probe: does unconditional dir-creation touch real disk")
    print("           even when HOME is empty (what the hermetic tests assume)?")
    print("=" * 70)
    repo, home = _mk_temp_repo_and_home()
    try:
        slot = 2
        wh = str(agy_pool.worker_home(repo, slot))
        before = os.path.exists(os.path.join(wh, ".gemini", "config"))
        # Simulate the orchestrator call site: injected real makedirs, empty home.
        # If the fix uses the INJECTED makedirs (real os.makedirs) for config dirs,
        # it WILL create them even though no src was copied.
        proposed_ensure_config_dirs(wh, isdir=os.path.isdir, remove=os.remove, makedirs=real_makedirs)
        after = os.path.exists(os.path.join(wh, ".gemini", "config"))
        print(f"  config existed before={before}  after={after}")
        print("  -> The fix creates config/ UNCONDITIONALLY (not gated on a copied src).")
        print("     The hermetic tests (test_orchestrator_agy_pool, test_agy_pool) assume")
        print("     ensure_seeded 'creates nothing on disk' with an empty HOME -> they will")
        print("     now see real-disk side effects unless the fix routes config-dir creation")
        print("     through the SAME injected seams the existing FakeFS/real-makedirs supply.")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)

    print()
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()

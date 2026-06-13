"""RED oracle for leaf `drive-backup-installer`.

Pins `tools/drive_backup/install_hooks.py`:
SENTINEL ('# >>> janusmask-drive-backup >>>'), DEFAULT_REPOS
(['/home/xnihil0zer0/JanusMaskJR', '/home/xnihil0zer0/NobleGreedv2']),
render_shim(janusmask_root, *, chained_hook=None) -> str,
InstallResult{repo, hook_path, action, ok},
install(repo_roots=DEFAULT_REPOS, *, fs, janusmask_root=JANUSMASK_ROOT,
dry_run=False) -> list[InstallResult], main(argv=None, *, fs=None) -> int.

Hermetic: the `fs` seam is a fake in-memory filesystem; NO real
.git/hooks writes, no git/push/hook execution. Tests assert shim text
shape, the created/updated/chained/dry branches, idempotency, foreign-
hook preservation, and the executable-bit set.
"""
import pytest

from tools.drive_backup import install_hooks
from tools.drive_backup.install_hooks import (
    DEFAULT_REPOS,
    SENTINEL,
    InstallResult,
    install,
    render_shim,
)


JM_ROOT = "/home/xnihil0zer0/JanusMaskJR"


class FakeFS:
    """In-memory filesystem seam: exists/read/write/move/chmod."""

    def __init__(self):
        self.files = {}        # path -> text
        self.modes = {}        # path -> int
        self.dirs = set()

    def exists(self, path):
        return path in self.files

    def read_text(self, path):
        return self.files[path]

    def write_text(self, path, text):
        self.files[path] = text

    def move(self, src, dst):
        self.files[dst] = self.files.pop(src)
        if src in self.modes:
            self.modes[dst] = self.modes.pop(src)

    def chmod(self, path, mode):
        self.modes[path] = mode

    def makedirs(self, path, exist_ok=True):
        self.dirs.add(path)


# ---- constants & shim text ----------------------------------------------

def test_default_repos_and_sentinel():
    assert DEFAULT_REPOS == [
        "/home/xnihil0zer0/JanusMaskJR",
        "/home/xnihil0zer0/NobleGreedv2",
    ]
    assert SENTINEL == "# >>> janusmask-drive-backup >>>"


def test_render_shim_shape():
    shim = render_shim(JM_ROOT)
    assert shim.startswith("#!/usr/bin/env bash")
    assert SENTINEL in shim
    # Absolute JanusMask root embedded so NobleGreedv2's hook finds the module.
    assert JM_ROOT in shim
    assert "python -m tools.drive_backup.hook_runner" in shim
    # The backup step must always exit 0 (never blocks a push).
    assert "exit 0" in shim


def test_render_shim_chains_to_original_when_given():
    chained = "/home/xnihil0zer0/JanusMaskJR/.git/hooks/pre-push.pre-janusmask"
    shim = render_shim(JM_ROOT, chained_hook=chained)
    assert chained in shim
    # Still exits 0 for the backup step and references the module.
    assert "exit 0" in shim
    assert "python -m tools.drive_backup.hook_runner" in shim


# ---- install branches ----------------------------------------------------

def test_install_creates_when_no_hook_exists():
    fs = FakeFS()
    results = install([JM_ROOT], fs=fs, janusmask_root=JM_ROOT)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, InstallResult)
    assert r.repo == JM_ROOT
    assert r.hook_path.endswith("/.git/hooks/pre-push")
    assert r.action == "created"
    assert r.ok is True
    # Shim written with sentinel and made executable (0o755).
    assert SENTINEL in fs.read_text(r.hook_path)
    assert fs.modes.get(r.hook_path) == 0o755


def test_install_updates_managed_shim_idempotently():
    fs = FakeFS()
    hook = f"{JM_ROOT}/.git/hooks/pre-push"
    # Pre-seed an EXISTING managed shim (contains the sentinel).
    fs.write_text(hook, render_shim(JM_ROOT))
    results = install([JM_ROOT], fs=fs, janusmask_root=JM_ROOT)
    r = results[0]
    assert r.action == "updated"
    assert r.ok is True
    # Idempotent: sentinel appears exactly once (not duplicated/stacked).
    assert fs.read_text(hook).count(SENTINEL) == 1


def test_install_chains_foreign_hook_and_preserves_it():
    fs = FakeFS()
    hook = f"{JM_ROOT}/.git/hooks/pre-push"
    foreign = "#!/bin/sh\necho legacy-lint-gate\nexit 1\n"
    fs.write_text(hook, foreign)
    results = install([JM_ROOT], fs=fs, janusmask_root=JM_ROOT)
    r = results[0]
    assert r.action == "chained"
    assert r.ok is True
    # Original foreign hook preserved at the .pre-janusmask sidecar.
    saved = f"{hook}.pre-janusmask"
    assert fs.exists(saved)
    assert fs.read_text(saved) == foreign
    # New managed shim chains to the saved original.
    new_shim = fs.read_text(hook)
    assert SENTINEL in new_shim
    assert saved in new_shim


def test_install_dry_run_does_not_write():
    fs = FakeFS()
    results = install([JM_ROOT], fs=fs, janusmask_root=JM_ROOT, dry_run=True)
    r = results[0]
    assert r.action.endswith(":dry")
    # No real write occurred under dry_run.
    assert not fs.exists(r.hook_path)
    assert fs.modes == {}


def test_install_targets_both_default_repos():
    fs = FakeFS()
    results = install(DEFAULT_REPOS, fs=fs, janusmask_root=JM_ROOT)
    repos = {r.repo for r in results}
    assert repos == set(DEFAULT_REPOS)
    for r in results:
        assert r.hook_path == f"{r.repo}/.git/hooks/pre-push"
        assert SENTINEL in fs.read_text(r.hook_path)

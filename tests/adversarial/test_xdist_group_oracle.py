"""Oracle for the xdist_group extension of tests/adversarial/conftest.py.

Brief 2 extends the conftest's ``pytest_collection_modifyitems`` hook so that
test modules which mutate shared on-disk state (config.yaml, state/ dirs,
sidecars) are pinned to a single ``xdist_group("shared_disk_state")``. That
forces them onto one ``-n auto`` worker so parallel runs stop racing -- without
editing the (class-method) tests themselves.

RED on HEAD: the conftest only adds the ``slow`` marker; shared-state modules
carry NO ``xdist_group`` marker.
GREEN after the fix: items in the shared-state modules carry both ``slow`` and
``xdist_group("shared_disk_state")``; ordinary adversarial items keep ``slow``
only.

The hook is loaded directly via importlib and driven with fake items -- fast,
deterministic, no subprocess.
"""
import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
CONFTEST = REPO / "tests" / "adversarial" / "conftest.py"

# A module on the shared-state list, and an ordinary adversarial module.
SHARED_STATE_PATH = "tests/adversarial/test_P2_mutation_kill.py"
ORDINARY_PATH = "tests/adversarial/test_slow_autotag_oracle.py"


class _FakeItem:
    def __init__(self, path: str):
        self.fspath = path
        self.own_markers = []

    def add_marker(self, marker):
        self.own_markers.append(marker)

    def has_marker(self, name: str) -> bool:
        return any(getattr(m, "name", None) == name for m in self.own_markers)

    def group_args(self):
        vals = []
        for m in self.own_markers:
            if getattr(m, "name", None) == "xdist_group":
                vals.extend(list(getattr(m, "args", ())))
                vals.extend(list(getattr(m, "kwargs", {}).values()))
        return vals


def _run_hook(paths):
    spec = importlib.util.spec_from_file_location("_adversarial_conftest_probe", CONFTEST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    items = [_FakeItem(p) for p in paths]
    mod.pytest_collection_modifyitems(config=None, items=items)
    return items


def test_shared_state_module_pinned_to_xdist_group():
    """PRIMARY (RED on HEAD): a shared-state module item is pinned to the
    `shared_disk_state` xdist group."""
    (item,) = _run_hook([SHARED_STATE_PATH])
    assert item.has_marker("xdist_group"), (
        f"{SHARED_STATE_PATH} item was not assigned an xdist_group marker"
    )
    assert "shared_disk_state" in item.group_args(), (
        f"xdist_group name should be 'shared_disk_state', got {item.group_args()!r}"
    )


def test_shared_state_module_still_slow():
    """REGRESSION GUARD: shared-state adversarial items keep the `slow` marker."""
    (item,) = _run_hook([SHARED_STATE_PATH])
    assert item.has_marker("slow"), f"{SHARED_STATE_PATH} item lost its `slow` marker"


def test_ordinary_adversarial_not_grouped():
    """NARROWNESS GUARD: an ordinary adversarial item is `slow` but NOT grouped."""
    (item,) = _run_hook([ORDINARY_PATH])
    assert item.has_marker("slow"), f"{ORDINARY_PATH} item should be `slow`"
    assert not item.has_marker("xdist_group"), (
        f"{ORDINARY_PATH} item must NOT be pinned to an xdist group"
    )

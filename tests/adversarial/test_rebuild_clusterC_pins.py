"""Operator per-unit pins for the 4 cluster-C units the autonomous test-author
could not gate (C9.17c frontier, session #47).

15/19 cluster-C units rebuilt autonomously (4 on the structured-input fuzz alone,
11 via the gen_testless test-author role). These 4 remained because the live
author degraded to an empty / wrong oracle:
  - config_loader.{get_hooks_config, get_batch_execution_config, HooksConfig.__post_init__}
    (dict -> dataclass + ConfigError validation; author produced an empty oracle)
  - sandbox_smoke.smoke_import (impure subprocess; author tested only the sibling
    _discover_project_root, whose assertion was tmp-path-flaky)

Each pin is BLACK-BOX probed against the real JanusMask original and named
``test_<unit>_*`` / ``test_<clstoken>_<method>_*`` so ``pytest -k <unit>`` scopes
it to its own unit (task._k_expr).
"""
import pytest

from harness.config_loader import (
    BatchExecutionConfig,
    ConfigError,
    HooksConfig,
    get_batch_execution_config,
    get_hooks_config,
)
from harness.sandbox_smoke import smoke_import


# --- config_loader.get_hooks_config(cfg) -> HooksConfig --------------------------
def test_get_hooks_config_defaults_when_empty():
    assert get_hooks_config({}) == HooksConfig(
        mode="off", enforce_verbs=[], shadow_dir="state/hooks/shadow/",
        shadow_min_clean_runs=3,
    )


def test_get_hooks_config_reads_valid_block():
    got = get_hooks_config({"hooks": {"mode": "shadow"}})
    assert got.mode == "shadow"


def test_get_hooks_config_rejects_bad_mode():
    with pytest.raises(ConfigError):
        get_hooks_config({"hooks": {"mode": "bogus"}})


def test_get_hooks_config_rejects_unknown_key():
    with pytest.raises(ConfigError):
        get_hooks_config({"hooks": {"nope": 1}})


def test_get_hooks_config_rejects_bad_verb():
    with pytest.raises(ConfigError):
        get_hooks_config({"hooks": {"enforce_verbs": ["add"]}})


# --- config_loader.get_batch_execution_config(cfg) -> BatchExecutionConfig -------
def test_get_batch_execution_config_defaults_when_empty():
    assert get_batch_execution_config({}) == BatchExecutionConfig(
        enabled=True, seccomp=True, rlimit_nproc=None,
        wall_timeout_per_input_sec=5.0, worker_pool_size=1, batch_size_per_worker=2000,
    )


def test_get_batch_execution_config_applies_overrides():
    got = get_batch_execution_config({"batch_execution": {"enabled": False, "worker_pool_size": 4}})
    assert got.enabled is False
    assert got.worker_pool_size == 4


# --- config_loader.HooksConfig.__post_init__ (validation) ------------------------
def test_hooksconfig_post_init_accepts_valid():
    cfg = HooksConfig(mode="shadow")
    assert cfg.mode == "shadow"
    assert cfg.enforce_verbs == []


def test_hooksconfig_post_init_rejects_bad_mode():
    with pytest.raises(ConfigError):
        HooksConfig(mode="bogus")


def test_hooksconfig_post_init_rejects_bad_verb():
    with pytest.raises(ConfigError):
        HooksConfig(enforce_verbs=["add"])


# --- sandbox_smoke.smoke_import(module_name, module_src, *, timeout) -------------
def test_smoke_import_returns_none_on_success():
    assert smoke_import("mymod_ok", "x = 1\ndef f():\n    return 2\n") is None


def test_smoke_import_reports_missing_module():
    err = smoke_import("mymod_bad", "import nonexistent_pkg_zzz\n")
    assert err is not None
    assert "ModuleNotFoundError" in err


def test_smoke_import_reports_syntax_error():
    err = smoke_import("mymod_syn", "def f(:\n")
    assert err is not None
    assert "SyntaxError" in err

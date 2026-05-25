import pytest
import yaml
import logging
from hypothesis import given, strategies as st
from harness.config_loader import get_batch_execution_config, ConfigError, BatchExecutionConfig

def test_default_config_section_missing():
    cfg = get_batch_execution_config({})
    assert cfg.enabled is True
    assert cfg.seccomp is True
    assert cfg.worker_pool_size == 1

def test_explicit_config_overrides_defaults():
    raw_cfg = {
        "batch_execution": {
            "enabled": False,
            "worker_pool_size": 4
        }
    }
    cfg = get_batch_execution_config(raw_cfg)
    assert cfg.enabled is False
    assert cfg.worker_pool_size == 4

def test_unknown_key_raises_config_error():
    raw_cfg = {
        "batch_execution": {
            "enabed": True
        }
    }
    with pytest.raises(ConfigError) as exc_info:
        get_batch_execution_config(raw_cfg)
    assert "enabed" in str(exc_info.value)

def test_wrong_type_raises_config_error():
    raw_cfg = {
        "batch_execution": {
            "enabled": "yes"
        }
    }
    with pytest.raises(ConfigError) as exc_info:
        get_batch_execution_config(raw_cfg)
    assert "enabled" in str(exc_info.value)

def test_rlimit_nproc_null_default():
    cfg = get_batch_execution_config({})
    assert cfg.rlimit_nproc is None

def test_rlimit_nproc_low_value_emits_warning(caplog):
    raw_cfg = {
        "batch_execution": {
            "rlimit_nproc": 1
        }
    }
    with caplog.at_level(logging.WARNING):
        cfg = get_batch_execution_config(raw_cfg)
    assert "test_nproc.py" in caplog.text
    assert cfg.rlimit_nproc == 1

def test_harness_config_yaml_parses_with_defaults():
    with open("harness/config.yaml", "r") as f:
        raw_cfg = yaml.safe_load(f)
    cfg = get_batch_execution_config(raw_cfg)
    assert isinstance(cfg, BatchExecutionConfig)
    assert cfg.enabled is True

@given(
    enabled=st.booleans(),
    seccomp=st.booleans(),
    rlimit_nproc=st.one_of(st.none(), st.integers(min_value=2, max_value=1000)),
    wall_timeout_per_input_sec=st.floats(min_value=0.1, max_value=60.0),
    worker_pool_size=st.integers(min_value=1, max_value=100),
    batch_size_per_worker=st.integers(min_value=1, max_value=10000)
)
def test_valid_config_combinations(enabled, seccomp, rlimit_nproc, wall_timeout_per_input_sec, worker_pool_size, batch_size_per_worker):
    raw_cfg = {
        "batch_execution": {
            "enabled": enabled,
            "seccomp": seccomp,
            "rlimit_nproc": rlimit_nproc,
            "wall_timeout_per_input_sec": wall_timeout_per_input_sec,
            "worker_pool_size": worker_pool_size,
            "batch_size_per_worker": batch_size_per_worker
        }
    }
    cfg = get_batch_execution_config(raw_cfg)
    assert cfg.enabled == enabled
    assert cfg.seccomp == seccomp
    assert cfg.rlimit_nproc == rlimit_nproc
    assert cfg.worker_pool_size == worker_pool_size
    assert cfg.batch_size_per_worker == batch_size_per_worker

def test_worker_pool_size_zero_rejected():
    raw_cfg = {
        "batch_execution": {
            "worker_pool_size": 0
        }
    }
    with pytest.raises(ConfigError):
        get_batch_execution_config(raw_cfg)

def test_negative_nproc_limit_rejected():
    raw_cfg = {
        "batch_execution": {
            "rlimit_nproc": -1
        }
    }
    with pytest.raises(ConfigError):
        get_batch_execution_config(raw_cfg)

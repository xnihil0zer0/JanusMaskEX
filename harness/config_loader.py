import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

class ConfigError(Exception):
    pass


# -- Hooks config (HOOK-13) -------------------------------------------------
# The hooks: block drives the Claude/Gemini hook-migration rollout flag.
# See hooks-implementation-plan.md §Phase 1 + sub-plan-02 §3.2.

HOOKS_VALID_MODES = frozenset({"off", "shadow", "enforce"})

# Verbs the hook path may authoritatively handle (sub-plan 02 §5.3 order is
# request_clarification → report_error → submit_reconciliation_response →
# submit_plan_draft → submit_code). Enforce subsets are gated on the P5
# equivalence report.
HOOKS_ALLOWED_VERBS = frozenset({
    "submit_code",
    "submit_plan_draft",
    "submit_reconciliation_response",
    "request_clarification",
    "report_error",
})

HOOKS_DEFAULT_SHADOW_DIR = "state/hooks/shadow/"

# HOOK-52: consecutive-clean-runs floor for the P5 shadow→enforce diff gate.
# Sub-plan 06 §1 mandates this as a configurable key; callers read it via
# harness.hooks_equivalence.check_diff_gate.
HOOKS_DEFAULT_MIN_CLEAN_RUNS = 3


@dataclass
class HooksConfig:
    mode: str = "off"
    enforce_verbs: List[str] = field(default_factory=list)
    shadow_dir: str = HOOKS_DEFAULT_SHADOW_DIR
    shadow_min_clean_runs: int = HOOKS_DEFAULT_MIN_CLEAN_RUNS

    def __post_init__(self):
        if not isinstance(self.mode, str) or isinstance(self.mode, bool):
            raise ConfigError(
                f"hooks.mode must be one of {sorted(HOOKS_VALID_MODES)}, "
                f"got {type(self.mode).__name__}"
            )
        if self.mode not in HOOKS_VALID_MODES:
            raise ConfigError(
                f"hooks.mode={self.mode!r} is invalid; "
                f"allowed: {sorted(HOOKS_VALID_MODES)}"
            )
        if not isinstance(self.enforce_verbs, list):
            raise ConfigError(
                f"hooks.enforce_verbs must be a list, got "
                f"{type(self.enforce_verbs).__name__}"
            )
        for v in self.enforce_verbs:
            if not isinstance(v, str):
                raise ConfigError(
                    f"hooks.enforce_verbs entries must be strings; "
                    f"got {type(v).__name__}"
                )
            if v not in HOOKS_ALLOWED_VERBS:
                raise ConfigError(
                    f"hooks.enforce_verbs entry {v!r} is not a recognised verb; "
                    f"allowed: {sorted(HOOKS_ALLOWED_VERBS)}"
                )
        if not isinstance(self.shadow_dir, str):
            raise ConfigError(
                f"hooks.shadow_dir must be a string path, got "
                f"{type(self.shadow_dir).__name__}"
            )
        if isinstance(self.shadow_min_clean_runs, bool) or not isinstance(
            self.shadow_min_clean_runs, int
        ):
            raise ConfigError(
                f"hooks.shadow_min_clean_runs must be a positive int, got "
                f"{type(self.shadow_min_clean_runs).__name__}"
            )
        if self.shadow_min_clean_runs < 1:
            raise ConfigError(
                "hooks.shadow_min_clean_runs must be >= 1; "
                "a zero floor defeats the shadow phase."
            )


def get_hooks_config(cfg: dict) -> HooksConfig:
    """Read the hooks block out of the top-level config dict.

    Missing or empty ``hooks:`` blocks return safe defaults (``mode: off``).
    The reader is strict about unknown keys so a typo doesn't silently roll
    the flag forward.
    """
    hooks_cfg = cfg.get("hooks", None)
    if hooks_cfg is None or hooks_cfg == {}:
        return HooksConfig()
    if not isinstance(hooks_cfg, dict):
        raise ConfigError("hooks section must be a dict")

    allowed_keys = {"mode", "enforce_verbs", "shadow_dir", "shadow_min_clean_runs"}
    for key in hooks_cfg.keys():
        if key not in allowed_keys:
            raise ConfigError(f"Unknown key in hooks config: '{key}'")

    try:
        return HooksConfig(**hooks_cfg)
    except TypeError as exc:
        raise ConfigError(str(exc))

@dataclass
class BatchExecutionConfig:
    enabled: bool = True
    seccomp: bool = True
    rlimit_nproc: Optional[int] = None
    wall_timeout_per_input_sec: float = 5.0
    worker_pool_size: int = 1
    batch_size_per_worker: int = 2000

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ConfigError(f"Invalid type for 'enabled': expected bool, got {type(self.enabled).__name__}")
        if not isinstance(self.seccomp, bool):
            raise ConfigError(f"Invalid type for 'seccomp': expected bool, got {type(self.seccomp).__name__}")
        if self.rlimit_nproc is not None and not isinstance(self.rlimit_nproc, int):
            raise ConfigError(f"Invalid type for 'rlimit_nproc': expected int or None, got {type(self.rlimit_nproc).__name__}")
        if isinstance(self.rlimit_nproc, bool): # bool is subclass of int in python!
            raise ConfigError(f"Invalid type for 'rlimit_nproc': expected int or None, got {type(self.rlimit_nproc).__name__}")
            
        if not isinstance(self.wall_timeout_per_input_sec, (float, int)) or isinstance(self.wall_timeout_per_input_sec, bool):
            raise ConfigError(f"Invalid type for 'wall_timeout_per_input_sec': expected float, got {type(self.wall_timeout_per_input_sec).__name__}")
        self.wall_timeout_per_input_sec = float(self.wall_timeout_per_input_sec)

        if not isinstance(self.worker_pool_size, int) or isinstance(self.worker_pool_size, bool):
            raise ConfigError(f"Invalid type for 'worker_pool_size': expected int, got {type(self.worker_pool_size).__name__}")
        if not isinstance(self.batch_size_per_worker, int) or isinstance(self.batch_size_per_worker, bool):
            raise ConfigError(f"Invalid type for 'batch_size_per_worker': expected int, got {type(self.batch_size_per_worker).__name__}")
            
        if self.worker_pool_size < 1:
            raise ConfigError("worker_pool_size must be >= 1")
        if self.rlimit_nproc is not None:
            if self.rlimit_nproc < 0:
                raise ConfigError("rlimit_nproc cannot be negative")
            if self.rlimit_nproc in (0, 1):
                logger.warning("rlimit_nproc set to %d, which is documented as unsafe (see test_nproc.py)", self.rlimit_nproc)

def get_batch_execution_config(cfg: dict) -> BatchExecutionConfig:
    if 'batch_execution' not in cfg:
        return BatchExecutionConfig()
    
    batch_cfg = cfg['batch_execution']
    if not isinstance(batch_cfg, dict):
        raise ConfigError("batch_execution section must be a dict")
        
    allowed_keys = {
        'enabled', 'seccomp', 'rlimit_nproc', 
        'wall_timeout_per_input_sec', 'worker_pool_size', 
        'batch_size_per_worker'
    }
    
    for key in batch_cfg.keys():
        if key not in allowed_keys:
            raise ConfigError(f"Unknown key in batch_execution config: '{key}'")
            
    try:
        return BatchExecutionConfig(**batch_cfg)
    except TypeError as e:
        raise ConfigError(str(e))

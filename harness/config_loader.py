import logging
from dataclasses import dataclass, field
from typing import List, Optional
logger = logging.getLogger(__name__)

class ConfigError(Exception):
    pass
HOOKS_VALID_MODES = frozenset({'off', 'shadow', 'enforce'})
HOOKS_ALLOWED_VERBS = frozenset({'submit_code', 'submit_plan_draft', 'submit_reconciliation_response', 'request_clarification', 'report_error'})
HOOKS_DEFAULT_SHADOW_DIR = 'state/hooks/shadow/'
HOOKS_DEFAULT_MIN_CLEAN_RUNS = 3

@dataclass
class HooksConfig:
    mode: str = 'off'
    enforce_verbs: List[str] = field(default_factory=list)
    shadow_dir: str = HOOKS_DEFAULT_SHADOW_DIR
    shadow_min_clean_runs: int = HOOKS_DEFAULT_MIN_CLEAN_RUNS

    def __post_init__(self):
        raise NotImplementedError

def get_hooks_config(cfg: dict) -> HooksConfig:
    """Read the hooks block out of the top-level config dict.

    Missing or empty ``hooks:`` blocks return safe defaults (``mode: off``).
    The reader is strict about unknown keys so a typo doesn't silently roll
    the flag forward.
    """
    raise NotImplementedError

@dataclass
class BatchExecutionConfig:
    enabled: bool = True
    seccomp: bool = True
    rlimit_nproc: Optional[int] = None
    wall_timeout_per_input_sec: float = 5.0
    worker_pool_size: int = 1
    batch_size_per_worker: int = 2000

    def __post_init__(self):
        raise NotImplementedError

def get_batch_execution_config(cfg: dict) -> BatchExecutionConfig:
    raise NotImplementedError
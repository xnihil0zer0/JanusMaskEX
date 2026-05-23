import logging
from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Optional
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
        """Validate per-field values right after dataclass construction.

        Each numeric knob gates a real resource (worker processes, the
        per-input wall clock, the per-worker batch slice, the optional
        ``RLIMIT_NPROC`` cap), so an out-of-range or wrong-typed value is
        rejected up front with :class:`ConfigError` rather than being allowed
        to fail deep inside the sandbox runner.

        Following the module's validation idiom, integer "count" fields are
        type-checked by excluding ``bool`` and requiring ``int``, then floored
        at ``>= 1``; ``wall_timeout_per_input_sec`` must be a strictly positive
        number; and ``rlimit_nproc`` is ``Optional[int]`` -- when set it must be
        a positive int.
        """
        for name in ('worker_pool_size', 'batch_size_per_worker'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f'batch_execution.{name} must be a positive int, got {type(value).__name__}')
            if value < 1:
                raise ConfigError(f'batch_execution.{name} must be >= 1, got {value!r}')
        wall = self.wall_timeout_per_input_sec
        if isinstance(wall, bool) or not isinstance(wall, (int, float)):
            raise ConfigError(f'batch_execution.wall_timeout_per_input_sec must be a positive number, got {type(wall).__name__}')
        if wall <= 0:
            raise ConfigError(f'batch_execution.wall_timeout_per_input_sec must be > 0, got {wall!r}')
        rlimit = self.rlimit_nproc
        if rlimit is not None:
            if isinstance(rlimit, bool) or not isinstance(rlimit, int):
                raise ConfigError(f'batch_execution.rlimit_nproc must be a positive int or None, got {type(rlimit).__name__}')
            if rlimit < 1:
                raise ConfigError(f'batch_execution.rlimit_nproc must be >= 1, got {rlimit!r}')

def get_batch_execution_config(cfg: dict) -> BatchExecutionConfig:
    raise NotImplementedError
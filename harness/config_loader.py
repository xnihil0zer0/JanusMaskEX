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
        """Validate per-field values right after dataclass construction.

        The hooks flag gates real enforcement behaviour, so a malformed
        ``mode`` or an unrecognised verb is rejected up front with
        :class:`ConfigError` rather than being allowed to silently roll the
        flag forward. ``mode`` must be one of :data:`HOOKS_VALID_MODES`;
        ``enforce_verbs`` must be a list whose entries are all drawn from
        :data:`HOOKS_ALLOWED_VERBS`; ``shadow_dir`` must be a string; and,
        following the module's count idiom, ``shadow_min_clean_runs`` is
        type-checked by excluding ``bool`` and requiring ``int``, then floored
        at ``>= 0``.
        """
        if self.mode not in HOOKS_VALID_MODES:
            raise ConfigError(f'hooks.mode must be one of {sorted(HOOKS_VALID_MODES)}, got {self.mode!r}')
        if not isinstance(self.enforce_verbs, list):
            raise ConfigError(f'hooks.enforce_verbs must be a list, got {type(self.enforce_verbs).__name__}')
        for verb in self.enforce_verbs:
            if verb not in HOOKS_ALLOWED_VERBS:
                raise ConfigError(f'hooks.enforce_verbs contains unknown verb {verb!r}; allowed: {sorted(HOOKS_ALLOWED_VERBS)}')
        if not isinstance(self.shadow_dir, str):
            raise ConfigError(f'hooks.shadow_dir must be a string, got {type(self.shadow_dir).__name__}')
        runs = self.shadow_min_clean_runs
        if isinstance(runs, bool) or not isinstance(runs, int):
            raise ConfigError(f'hooks.shadow_min_clean_runs must be a non-negative int, got {type(runs).__name__}')
        if runs < 0:
            raise ConfigError(f'hooks.shadow_min_clean_runs must be >= 0, got {runs!r}')
from harness.config_loader import HooksConfig

def get_hooks_config(cfg: dict) -> HooksConfig:
    """Read the hooks block out of the top-level config dict.

    Missing or empty ``hooks:`` blocks return safe defaults (``mode: off``).
    The reader is strict about unknown keys so a typo doesn't silently roll
    the flag forward.
    """
    block = cfg.get('hooks') or {}
    if not isinstance(block, dict):
        raise ConfigError(f'hooks: must be a mapping, got {type(block).__name__}')
    allowed = {f.name for f in fields(HooksConfig)}
    unknown = set(block) - allowed
    if unknown:
        raise ConfigError(f'hooks: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}')
    return HooksConfig(**block)

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
from harness.config_loader import BatchExecutionConfig

def get_batch_execution_config(cfg: dict) -> BatchExecutionConfig:
    """Read the batch_execution block out of the top-level config dict.

    Missing or empty ``batch_execution:`` blocks return safe defaults. The
    reader is strict about unknown keys so a typo doesn't silently change a
    resource knob. Per-field range/type validation is handled by
    :meth:`BatchExecutionConfig.__post_init__`.
    """
    block = cfg.get('batch_execution') or {}
    if not isinstance(block, dict):
        raise ConfigError(f'batch_execution: must be a mapping, got {type(block).__name__}')
    allowed = {f.name for f in fields(BatchExecutionConfig)}
    unknown = set(block) - allowed
    if unknown:
        raise ConfigError(f'batch_execution: unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}')
    return BatchExecutionConfig(**block)
from dataclasses import fields
from harness.config_loader import ConfigError
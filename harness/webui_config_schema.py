"""harness/webui_config_schema.py — declarative, typed config schema driving
server-side validation of WebUI config submissions.

Mirrors the typed-dataclass + explicit-validator precedent in
``harness/config_loader.py`` (HooksConfig / get_hooks_config raising a
ConfigError, with ``isinstance(x, bool)``-before-``int`` guards). This module
provides:

* ``ConfigField`` / ``RoleSpec`` / ``ProviderSpec`` declarative records,
* the ``CONFIG_FIELDS`` / ``ROLES`` / ``PROVIDERS`` tables,
* ``validate_config`` — coerces + validates each submitted field into a
  per-field error map and enforces the dual-agent-distinct and
  provider-locked-unless-keyed cross-field rules, and
* ``atomic_save_config`` — merges validated values into existing YAML and
  writes via a temp file + ``os.replace`` so the write is never partial.

This module deliberately owns its own ``PROVIDERS`` table and does NOT import
``harness/model_backends*`` — it only reads the passed-in ``secrets`` dict to
gate provider locks. Stdlib + PyYAML only.
"""
from __future__ import annotations
import os
import tempfile
from dataclasses import dataclass, field as _dc_field
from typing import Any, Optional
import yaml
_VALID_DTYPES = frozenset({'int', 'float', 'str', 'bool', 'path-file', 'path-dir', 'enum'})

class ConfigField:
    """A single typed, declarative config tunable.

    Signature is frozen: ``ConfigField(name, dtype, default, *, choices=None,
    min=None, max=None, role=None)`` with ``dtype`` in
    {int, float, str, bool, path-file, path-dir, enum}.
    """
    __slots__ = ('name', 'dtype', 'default', 'choices', 'min', 'max', 'role')

    def __init__(self, name: str, dtype: str, default: Any, *, choices: Optional[list]=None, min: Optional[float]=None, max: Optional[float]=None, role: Optional[str]=None) -> None:
        self.name = name
        self.dtype = dtype
        self.default = default
        self.choices = choices
        self.min = min
        self.max = max
        self.role = role

    def __repr__(self) -> str:
        return f'ConfigField(name={self.name!r}, dtype={self.dtype!r}, default={self.default!r})'

@dataclass(frozen=True)
class RoleSpec:
    """A configurable role slot (single-select or dual-select)."""
    name: str
    config_key: str
    dual: bool

@dataclass(frozen=True)
class ProviderSpec:
    """A model provider — either a CLI agent (api_backed=False) or an
    api-backed endpoint (api_backed=True) gated on an env var."""
    provider_id: str
    label: str
    api_key_env: Optional[str]
    api_backed: bool

@dataclass
class ValidatedConfig:
    """Result of a successful ``validate_config`` call.

    ``values`` stays SHORT-keyed (e.g. ``parallel_cap``); the short->dotted
    translation only happens at save time in ``atomic_save_config``.
    """
    values: dict

class ConfigValidationError(Exception):
    """Raised by ``validate_config`` with the accumulated per-field errors."""

    def __init__(self, field_errors: dict) -> None:
        self.field_errors = dict(field_errors)
        super().__init__(f'config validation failed: {self.field_errors}')
CONFIG_FIELDS: list = [ConfigField('parallel_cap', 'int', 4, min=1, max=16), ConfigField('min_ram_mb', 'int', 0, min=0), ConfigField('cooldown_tier_1', 'float', 0.0, min=0), ConfigField('cooldown_tier_2', 'float', 0.0, min=0), ConfigField('cooldown_tier_3', 'float', 0.0, min=0), ConfigField('antigravity_mode', 'bool', False), ConfigField('sandbox.filesystem_root', 'path-dir', '.'), ConfigField('overseer.store_path', 'path-file', 'state/overseer.json')]
ROLES: list = [RoleSpec('synthesis', 'synthesis.active_agents', True), RoleSpec('overseer', 'overseer.default_backend', False), RoleSpec('autobrief', 'control.autobrief_default_agent', False)]
PROVIDERS: dict = {'claude': ProviderSpec('claude', 'Claude CLI', None, False), 'gemini': ProviderSpec('gemini', 'Gemini CLI', None, False), 'antigravity': ProviderSpec('antigravity', 'Antigravity CLI', None, False), 'codex': ProviderSpec('codex', 'Codex CLI', None, False), 'openai': ProviderSpec('openai', 'OpenAI', 'OPENAI_API_KEY', True), 'gemini_api': ProviderSpec('gemini_api', 'Gemini API', 'GEMINI_API_KEY', True), 'anthropic': ProviderSpec('anthropic', 'Anthropic API', 'ANTHROPIC_API_KEY', True), 'deepseek': ProviderSpec('deepseek', 'DeepSeek', 'DEEPSEEK_API_KEY', True), 'moonshot': ProviderSpec('moonshot', 'Moonshot', 'MOONSHOT_API_KEY', True), 'zhipu': ProviderSpec('zhipu', 'Zhipu GLM', 'ZHIPU_API_KEY', True), 'qwen': ProviderSpec('qwen', 'Qwen', 'DASHSCOPE_API_KEY', True), 'minimax': ProviderSpec('minimax', 'MiniMax', 'MINIMAX_API_KEY', True)}

def _check_bounds(field: ConfigField, value):
    """Apply min/max bounds; return ``(value, None)`` or ``(None, error)``."""
    if field.min is not None and value < field.min:
        return (None, f'must be >= {field.min}')
    if field.max is not None and value > field.max:
        return (None, f'must be <= {field.max}')
    return (value, None)

def _coerce_field(field: ConfigField, raw):
    """Coerce ``raw`` to ``field.dtype``.

    Returns ``(coerced_value, None)`` on success or ``(None, error_message)``
    on a non-coercible / out-of-bounds / bad-choice value. The bool branch
    guards ``isinstance(raw, bool)`` BEFORE any int handling so arbitrary
    truthy ints are rejected (mirrors HooksConfig in config_loader.py).
    """
    dtype = field.dtype
    if dtype == 'bool':
        if isinstance(raw, bool):
            return (raw, None)
        if isinstance(raw, str) and raw.strip().lower() in ('true', 'false'):
            return (raw.strip().lower() == 'true', None)
        return (None, 'expected bool')
    if dtype == 'int':
        if isinstance(raw, bool):
            return (None, 'expected int, got bool')
        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str):
            try:
                value = int(raw.strip())
            except (ValueError, TypeError):
                return (None, 'expected int')
        else:
            return (None, 'expected int')
        return _check_bounds(field, value)
    if dtype == 'float':
        if isinstance(raw, bool):
            return (None, 'expected float, got bool')
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip())
            except (ValueError, TypeError):
                return (None, 'expected float')
        else:
            return (None, 'expected float')
        return _check_bounds(field, value)
    if dtype in ('str', 'path-file', 'path-dir'):
        if isinstance(raw, str):
            return (raw, None)
        if isinstance(raw, (int, float)) and (not isinstance(raw, bool)):
            return (str(raw), None)
        return (None, f'expected {dtype}')
    if dtype == 'enum':
        if field.choices is not None and raw in field.choices:
            return (raw, None)
        return (None, 'invalid choice')
    return (None, f'unknown dtype {dtype!r}')

def _provider_lock_error(provider_id, secrets) -> Optional[str]:
    """Return a lock error if ``provider_id`` is api-backed but its env var is
    missing/empty in ``secrets``; otherwise None."""
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        return f'unknown provider: {provider_id}'
    if spec.api_backed:
        env = spec.api_key_env
        if not (secrets or {}).get(env):
            return f'provider locked: set {env} first'
    return None

def _validate_dual(assignment, secrets) -> Optional[str]:
    """Validate a dual-role assignment: two agents, both present, DIFFERENT,
    and each unlocked. Returns an error string or None."""
    if not isinstance(assignment, (list, tuple)) or len(assignment) < 2:
        return 'dual role requires two distinct agents'
    agent0, agent1 = (assignment[0], assignment[1])
    if not agent0 or not agent1:
        return 'dual role requires two distinct agents'
    if agent0 == agent1:
        return 'dual role agents must be different'
    for agent in (agent0, agent1):
        lock = _provider_lock_error(agent, secrets)
        if lock is not None:
            return lock
    return None

def validate_config(submitted: dict, *, secrets: dict) -> ValidatedConfig:
    """Coerce + validate ``submitted`` into a ``ValidatedConfig``.

    Each submitted field is coerced by dtype and bounds/choice-checked;
    non-coercible / out-of-bounds / bad-choice values are recorded into
    ``field_errors[name]`` WITHOUT raising mid-loop. Both cross-field rules
    are then applied per role:

    * dual roles require two present, different, unlocked agents, and
    * any role assigned an api-backed provider whose ``secrets[api_key_env]``
      is empty is rejected with ``'provider locked: set <ENV> first'``.

    Errors accumulate across the whole loop; if any remain a
    ``ConfigValidationError(field_errors)`` is raised, else a
    ``ValidatedConfig(values)`` is returned. On the per-role accept path the
    accepted assignment is propagated into ``values[role.config_key]``
    (single-select = provider-id string, dual = ``[agent0, agent1]``).
    """
    secrets = secrets or {}
    field_errors: dict = {}
    values: dict = {}
    for field in CONFIG_FIELDS:
        if field.name not in submitted:
            continue
        coerced, error = _coerce_field(field, submitted[field.name])
        if error is not None:
            field_errors[field.name] = error
        else:
            values[field.name] = coerced
    for role in ROLES:
        if role.config_key not in submitted:
            continue
        assignment = submitted[role.config_key]
        if role.dual:
            error = _validate_dual(assignment, secrets)
            if error is not None:
                field_errors[role.config_key] = error
            else:
                values[role.config_key] = [assignment[0], assignment[1]]
        else:
            error = _provider_lock_error(assignment, secrets)
            if error is not None:
                field_errors[role.config_key] = error
            else:
                values[role.config_key] = assignment
    if field_errors:
        raise ConfigValidationError(field_errors)
    return ValidatedConfig(values)
_SHORT_TO_DOTTED: dict = {'parallel_cap': 'autowork.parallel_cap', 'min_ram_mb': 'autowork.min_ram_mb', 'cooldown_tier_1': 'autowork.cooldown_tier_1', 'cooldown_tier_2': 'autowork.cooldown_tier_2', 'cooldown_tier_3': 'autowork.cooldown_tier_3', 'antigravity_mode': 'synthesis.antigravity_mode'}

def _set_nested(root: dict, dotted: str, value) -> None:
    """Set ``value`` at the dotted path inside ``root``, creating intermediate
    dicts as needed and preserving unrelated siblings."""
    parts = dotted.split('.')
    node = root
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value

def atomic_save_config(validated: ValidatedConfig, config_path) -> None:
    """Merge ``validated.values`` into the existing YAML at ``config_path`` and
    write atomically.

    Short keys are translated to dotted save paths via ``_SHORT_TO_DOTTED``
    BEFORE the nested merge; already-dotted fields and role keys are saved
    unchanged. The merge is a deep set per key so unrelated blocks (e.g.
    ``autowork.poll_interval_sec``, ``overseer.enabled``) are preserved. The
    write goes through a temp file in the SAME directory followed by
    ``os.replace`` so the file is never partially written.
    """
    path = config_path if hasattr(config_path, '__fspath__') else str(config_path)
    existing: dict = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            existing = loaded
    for short, value in validated.values.items():
        dotted = _SHORT_TO_DOTTED.get(short, short)
        _set_nested(existing, dotted, value)
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            yaml.safe_dump(existing, handle, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
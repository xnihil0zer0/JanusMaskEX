"""harness/webui_config_schema.py — declarative, typed config schema that
drives server-side validation for the WebUI Config panel.

This module mirrors ``harness/config_loader.py``'s precedent of typed
dataclasses paired with an explicit validator and a dedicated exception.
It is deliberately self-contained: it knows nothing about Flask, network
backends, or secret persistence. It only:

  * declares the typed field list (:data:`CONFIG_FIELDS`),
  * declares the agent/provider catalogue (:data:`PROVIDERS`) and the
    role slots (:data:`ROLES`),
  * coerces + validates a submitted config dict into a
    :class:`ValidatedConfig` (or raises :class:`ConfigValidationError`
    carrying a per-field message map), and
  * atomically merges a validated config back onto disk
    (:func:`atomic_save_config`) without clobbering unrelated blocks.

Stdlib + PyYAML only.
"""
from __future__ import annotations
import os
import tempfile
from dataclasses import dataclass, field as _dc_field
from pathlib import Path
from typing import Any, Optional
import yaml
_VALID_DTYPES = {'int', 'float', 'str', 'bool', 'path-file', 'path-dir', 'enum'}

@dataclass
class ConfigField:
    """A single typed, validatable tunable.

    ``dtype`` is one of ``int|float|str|bool|path-file|path-dir|enum``.
    ``min``/``max`` apply to numeric dtypes; ``choices`` applies to ``enum``
    (and may constrain any dtype). ``role`` optionally ties the field to a
    :class:`RoleSpec`.
    """
    name: str
    dtype: str
    default: Any
    choices: Optional[list] = None
    min: Optional[float] = None
    max: Optional[float] = None
    role: Optional[str] = None

    def __init__(self, name: str, dtype: str, default: Any, *, choices: Optional[list]=None, min: Optional[float]=None, max: Optional[float]=None, role: Optional[str]=None) -> None:
        self.name = name
        self.dtype = dtype
        self.default = default
        self.choices = choices
        self.min = min
        self.max = max
        self.role = role

@dataclass(frozen=True)
class RoleSpec:
    """An agent-assignment slot in the config (e.g. synthesis/overseer)."""
    name: str
    config_key: str
    dual: bool

@dataclass(frozen=True)
class ProviderSpec:
    """A selectable agent/provider.

    ``api_backed`` providers gate on a non-empty secret stored under
    ``api_key_env``; CLI agents (``api_backed=False``) are never locked.
    """
    provider_id: str
    label: str
    api_key_env: str
    api_backed: bool

@dataclass
class ValidatedConfig:
    """The coerced, validated config values ready for persistence."""
    values: dict

class ConfigValidationError(Exception):
    """Raised when one or more submitted fields fail coercion/validation.

    Carries a ``field_errors`` map of ``field-name -> human message`` so the
    caller (the WebUI) can surface each problem next to its widget.
    """

    def __init__(self, field_errors: dict) -> None:
        self.field_errors = dict(field_errors)
        super().__init__('config validation failed: ' + ', '.join((f'{k}: {v}' for k, v in self.field_errors.items())))
PROVIDERS: dict[str, ProviderSpec] = {'claude': ProviderSpec('claude', 'Claude (CLI)', '', False), 'gemini': ProviderSpec('gemini', 'Gemini (CLI)', '', False), 'antigravity': ProviderSpec('antigravity', 'Antigravity (CLI)', '', False), 'codex': ProviderSpec('codex', 'Codex (CLI)', '', False), 'openai': ProviderSpec('openai', 'OpenAI', 'OPENAI_API_KEY', True), 'gemini_api': ProviderSpec('gemini_api', 'Gemini API', 'GEMINI_API_KEY', True), 'anthropic': ProviderSpec('anthropic', 'Anthropic API', 'ANTHROPIC_API_KEY', True), 'deepseek': ProviderSpec('deepseek', 'DeepSeek', 'DEEPSEEK_API_KEY', True), 'moonshot': ProviderSpec('moonshot', 'Moonshot (Kimi)', 'MOONSHOT_API_KEY', True), 'zhipu': ProviderSpec('zhipu', 'Zhipu (GLM)', 'ZHIPU_API_KEY', True), 'qwen': ProviderSpec('qwen', 'Qwen (DashScope)', 'DASHSCOPE_API_KEY', True), 'minimax': ProviderSpec('minimax', 'MiniMax', 'MINIMAX_API_KEY', True)}
ROLES: list[RoleSpec] = [RoleSpec('synthesis', 'synthesis.active_agents', True), RoleSpec('overseer', 'overseer.default_backend', False), RoleSpec('autobrief', 'control.autobrief_default_agent', False)]
CONFIG_FIELDS: list[ConfigField] = [ConfigField('parallel_cap', 'int', 4, min=1, max=16), ConfigField('min_ram_mb', 'int', 2048, min=0), ConfigField('cooldown_tier_1', 'float', 1.0, min=0), ConfigField('cooldown_tier_2', 'float', 5.0, min=0), ConfigField('cooldown_tier_3', 'float', 30.0, min=0), ConfigField('antigravity_mode', 'bool', False), ConfigField('sandbox.filesystem_root', 'path-dir', '_sandbox'), ConfigField('overseer.store_path', 'path-file', 'state/overseer.json')]

def _coerce_bool(x: Any) -> tuple[Any, Optional[str]]:
    if isinstance(x, bool):
        return (x, None)
    if isinstance(x, int):
        return (None, f'expected a boolean, got int {x!r}')
    if isinstance(x, str):
        s = x.strip().lower()
        if s == 'true':
            return (True, None)
        if s == 'false':
            return (False, None)
        return (None, f"expected 'true'/'false', got {x!r}")
    return (None, f'expected a boolean, got {type(x).__name__}')

def _coerce_int(x: Any) -> tuple[Any, Optional[str]]:
    if isinstance(x, bool):
        return (None, f'expected an integer, got bool {x!r}')
    try:
        return (int(x), None)
    except (ValueError, TypeError):
        return (None, f'expected an integer, got {x!r}')

def _coerce_float(x: Any) -> tuple[Any, Optional[str]]:
    if isinstance(x, bool):
        return (None, f'expected a number, got bool {x!r}')
    try:
        return (float(x), None)
    except (ValueError, TypeError):
        return (None, f'expected a number, got {x!r}')

def _coerce_str(x: Any) -> tuple[Any, Optional[str]]:
    if x is None:
        return (None, 'expected a string, got None')
    return (str(x), None)

def _coerce_field(fld: ConfigField, value: Any) -> tuple[Any, Optional[str]]:
    if fld.dtype == 'bool':
        return _coerce_bool(value)
    if fld.dtype == 'int':
        return _coerce_int(value)
    if fld.dtype == 'float':
        return _coerce_float(value)
    return _coerce_str(value)

def validate_config(submitted: dict, *, secrets: dict) -> ValidatedConfig:
    """Coerce + validate ``submitted`` against the schema.

    Each :data:`CONFIG_FIELDS` entry is coerced by its dtype; non-coercible
    values record a human-readable message in ``field_errors[name]`` rather
    than raising mid-loop. Bounds (``min``/``max``) and ``choices``/enum
    membership are then checked. Two cross-field rules follow:

      (a) every dual :class:`RoleSpec` requires two *present* and *distinct*
          agents, else ``field_errors[role.config_key]``;
      (b) any role assigned an ``api_backed`` provider whose
          ``secrets[api_key_env]`` is empty/absent records
          ``'provider locked: set <ENV> first'``.

    Raises :class:`ConfigValidationError` if anything failed; otherwise
    returns a :class:`ValidatedConfig` of the coerced field values.
    """
    submitted = submitted or {}
    secrets = secrets or {}
    field_errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    for fld in CONFIG_FIELDS:
        if fld.name not in submitted:
            values[fld.name] = fld.default
            continue
        coerced, err = _coerce_field(fld, submitted[fld.name])
        if err is not None:
            field_errors[fld.name] = err
            continue
        if fld.dtype in ('int', 'float'):
            if fld.min is not None and coerced < fld.min:
                field_errors[fld.name] = f'{coerced} is below minimum {fld.min}'
                continue
            if fld.max is not None and coerced > fld.max:
                field_errors[fld.name] = f'{coerced} is above maximum {fld.max}'
                continue
        if fld.choices is not None and coerced not in fld.choices:
            field_errors[fld.name] = f'{coerced!r} is not one of {fld.choices}'
            continue
        values[fld.name] = coerced
    for role in ROLES:
        assigned = submitted.get(role.config_key)
        if role.dual:
            agents = list(assigned) if isinstance(assigned, (list, tuple)) else []
            present = [a for a in agents if a]
            if len(present) < 2:
                field_errors[role.config_key] = 'dual role requires two agents'
                continue
            if present[0] == present[1]:
                field_errors[role.config_key] = 'dual role requires two different agents'
                continue
            to_check = present[:2]
        else:
            if not assigned:
                continue
            to_check = [assigned]
        locked_msg = None
        for pid in to_check:
            spec = PROVIDERS.get(pid)
            if spec is not None and spec.api_backed and (not secrets.get(spec.api_key_env)):
                locked_msg = f'provider locked: set {spec.api_key_env} first'
                break
        if locked_msg is not None:
            field_errors[role.config_key] = locked_msg
    if field_errors:
        raise ConfigValidationError(field_errors)
    return ValidatedConfig(values)

def _set_nested(target: dict, dotted_key: str, value: Any) -> None:
    """Set ``value`` at a (possibly dotted) key, creating sub-dicts."""
    parts = dotted_key.split('.')
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value

def atomic_save_config(validated: ValidatedConfig, config_path) -> None:
    """Merge ``validated.values`` onto the YAML at ``config_path`` atomically.

    The existing config is loaded and unrelated blocks are preserved; the
    validated values (dotted names expand into nested mappings) are merged
    in, then written to a temp file in the SAME directory, flushed/fsynced,
    and ``os.replace``-d over the target so the file is never partially
    written.
    """
    config_path = Path(config_path)
    existing: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as fh:
            loaded = yaml.safe_load(fh)
            if isinstance(loaded, dict):
                existing = loaded
    for key, value in validated.values.items():
        _set_nested(existing, key, value)
    target_dir = config_path.parent if str(config_path.parent) else Path('.')
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(target_dir), prefix='.cfg-', suffix='.tmp', delete=False)
    try:
        yaml.safe_dump(existing, tmp, default_flow_style=False, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, config_path)
    except BaseException:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
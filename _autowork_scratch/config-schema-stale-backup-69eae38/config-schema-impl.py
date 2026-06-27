__JANUSMASK_MANIFEST__ = {
    'harness/webui_config_schema.py': r'''"""harness/webui_config_schema.py — declarative, typed config schema driving
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


# --------------------------------------------------------------------------
# Declarative records
# --------------------------------------------------------------------------

# Allowed dtypes for a ConfigField. ``path-file`` / ``path-dir`` are coerced
# as plain path strings (no filesystem existence check at this layer).
_VALID_DTYPES = frozenset(
    {"int", "float", "str", "bool", "path-file", "path-dir", "enum"}
)


class ConfigField:
    """A single typed, declarative config tunable.

    Signature is frozen: ``ConfigField(name, dtype, default, *, choices=None,
    min=None, max=None, role=None)`` with ``dtype`` in
    {int, float, str, bool, path-file, path-dir, enum}.
    """

    __slots__ = ("name", "dtype", "default", "choices", "min", "max", "role")

    def __init__(
        self,
        name: str,
        dtype: str,
        default: Any,
        *,
        choices: Optional[list] = None,
        min: Optional[float] = None,
        max: Optional[float] = None,
        role: Optional[str] = None,
    ) -> None:
        self.name = name
        self.dtype = dtype
        self.default = default
        self.choices = choices
        self.min = min
        self.max = max
        self.role = role

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"ConfigField(name={self.name!r}, dtype={self.dtype!r}, "
            f"default={self.default!r})"
        )


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
        super().__init__(f"config validation failed: {self.field_errors}")


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

CONFIG_FIELDS: list = [
    ConfigField("parallel_cap", "int", 4, min=1, max=16),
    ConfigField("min_ram_mb", "int", 0, min=0),
    ConfigField("cooldown_tier_1", "float", 0.0, min=0),
    ConfigField("cooldown_tier_2", "float", 0.0, min=0),
    ConfigField("cooldown_tier_3", "float", 0.0, min=0),
    ConfigField("antigravity_mode", "bool", False),
    ConfigField("sandbox.filesystem_root", "path-dir", "."),
    ConfigField("overseer.store_path", "path-file", "state/overseer.json"),
]

ROLES: list = [
    RoleSpec("synthesis", "synthesis.active_agents", True),
    RoleSpec("overseer", "overseer.default_backend", False),
    RoleSpec("autobrief", "control.autobrief_default_agent", False),
]

# PROVIDERS owns its own table — no import of harness/model_backends*. CLI
# agents are not api-backed (no env gate); api-backed endpoints carry the env
# var that must be present in ``secrets`` for the provider to be unlocked.
# env vars mirror _autowork_scratch/CHINESE_API_RESEARCH.md; gemini_api is the
# OpenAI-compatible Gemini endpoint keyed on GEMINI_API_KEY.
PROVIDERS: dict = {
    # CLI agents (no API key needed).
    "claude": ProviderSpec("claude", "Claude CLI", None, False),
    "gemini": ProviderSpec("gemini", "Gemini CLI", None, False),
    "antigravity": ProviderSpec("antigravity", "Antigravity CLI", None, False),
    "codex": ProviderSpec("codex", "Codex CLI", None, False),
    # api-backed endpoints (env-gated).
    "openai": ProviderSpec("openai", "OpenAI", "OPENAI_API_KEY", True),
    "gemini_api": ProviderSpec("gemini_api", "Gemini API", "GEMINI_API_KEY", True),
    "anthropic": ProviderSpec("anthropic", "Anthropic API", "ANTHROPIC_API_KEY", True),
    "deepseek": ProviderSpec("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", True),
    "moonshot": ProviderSpec("moonshot", "Moonshot", "MOONSHOT_API_KEY", True),
    "zhipu": ProviderSpec("zhipu", "Zhipu GLM", "ZHIPU_API_KEY", True),
    "qwen": ProviderSpec("qwen", "Qwen", "DASHSCOPE_API_KEY", True),
    "minimax": ProviderSpec("minimax", "MiniMax", "MINIMAX_API_KEY", True),
}


# --------------------------------------------------------------------------
# Coercion helpers
# --------------------------------------------------------------------------

def _check_bounds(field: ConfigField, value):
    """Apply min/max bounds; return ``(value, None)`` or ``(None, error)``."""
    if field.min is not None and value < field.min:
        return None, f"must be >= {field.min}"
    if field.max is not None and value > field.max:
        return None, f"must be <= {field.max}"
    return value, None


def _coerce_field(field: ConfigField, raw):
    """Coerce ``raw`` to ``field.dtype``.

    Returns ``(coerced_value, None)`` on success or ``(None, error_message)``
    on a non-coercible / out-of-bounds / bad-choice value. The bool branch
    guards ``isinstance(raw, bool)`` BEFORE any int handling so arbitrary
    truthy ints are rejected (mirrors HooksConfig in config_loader.py).
    """
    dtype = field.dtype

    if dtype == "bool":
        if isinstance(raw, bool):
            return raw, None
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true", None
        return None, "expected bool"

    if dtype == "int":
        # isinstance(bool)-before-int: True/False must not pass as 1/0.
        if isinstance(raw, bool):
            return None, "expected int, got bool"
        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str):
            try:
                value = int(raw.strip())
            except (ValueError, TypeError):
                return None, "expected int"
        else:
            return None, "expected int"
        return _check_bounds(field, value)

    if dtype == "float":
        if isinstance(raw, bool):
            return None, "expected float, got bool"
        if isinstance(raw, (int, float)):
            value = float(raw)
        elif isinstance(raw, str):
            try:
                value = float(raw.strip())
            except (ValueError, TypeError):
                return None, "expected float"
        else:
            return None, "expected float"
        return _check_bounds(field, value)

    if dtype in ("str", "path-file", "path-dir"):
        if isinstance(raw, str):
            return raw, None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return str(raw), None
        return None, f"expected {dtype}"

    if dtype == "enum":
        if field.choices is not None and raw in field.choices:
            return raw, None
        return None, "invalid choice"

    return None, f"unknown dtype {dtype!r}"


# --------------------------------------------------------------------------
# Cross-field rules
# --------------------------------------------------------------------------

def _provider_lock_error(provider_id, secrets) -> Optional[str]:
    """Return a lock error if ``provider_id`` is api-backed but its env var is
    missing/empty in ``secrets``; otherwise None."""
    spec = PROVIDERS.get(provider_id)
    if spec is None:
        return f"unknown provider: {provider_id}"
    if spec.api_backed:
        env = spec.api_key_env
        if not (secrets or {}).get(env):
            return f"provider locked: set {env} first"
    return None


def _validate_dual(assignment, secrets) -> Optional[str]:
    """Validate a dual-role assignment: two agents, both present, DIFFERENT,
    and each unlocked. Returns an error string or None."""
    if not isinstance(assignment, (list, tuple)) or len(assignment) < 2:
        return "dual role requires two distinct agents"
    agent0, agent1 = assignment[0], assignment[1]
    if not agent0 or not agent1:
        return "dual role requires two distinct agents"
    if agent0 == agent1:
        return "dual role agents must be different"
    for agent in (agent0, agent1):
        lock = _provider_lock_error(agent, secrets)
        if lock is not None:
            return lock
    return None


# --------------------------------------------------------------------------
# Public validator
# --------------------------------------------------------------------------

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
                # Accept path: propagate the [agent0, agent1] pair.
                values[role.config_key] = [assignment[0], assignment[1]]
        else:
            error = _provider_lock_error(assignment, secrets)
            if error is not None:
                field_errors[role.config_key] = error
            else:
                # Accept path: propagate the provider-id string.
                values[role.config_key] = assignment

    if field_errors:
        raise ConfigValidationError(field_errors)
    return ValidatedConfig(values)


# --------------------------------------------------------------------------
# Atomic save
# --------------------------------------------------------------------------

# Short -> dotted save-path map (KNOWN-BUG-FIX #2). ``values`` stays
# short-keyed; only the on-disk save path is dotted. Already-dotted fields and
# role keys save unchanged.
_SHORT_TO_DOTTED: dict = {
    "parallel_cap": "autowork.parallel_cap",
    "min_ram_mb": "autowork.min_ram_mb",
    "cooldown_tier_1": "autowork.cooldown_tier_1",
    "cooldown_tier_2": "autowork.cooldown_tier_2",
    "cooldown_tier_3": "autowork.cooldown_tier_3",
    "antigravity_mode": "synthesis.antigravity_mode",
}


def _set_nested(root: dict, dotted: str, value) -> None:
    """Set ``value`` at the dotted path inside ``root``, creating intermediate
    dicts as needed and preserving unrelated siblings."""
    parts = dotted.split(".")
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
    path = config_path if hasattr(config_path, "__fspath__") else str(config_path)

    existing: dict = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if isinstance(loaded, dict):
            existing = loaded

    for short, value in validated.values.items():
        dotted = _SHORT_TO_DOTTED.get(short, short)
        _set_nested(existing, dotted, value)

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(existing, handle, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
''',
    'harness/control_gate.py': r'''"""harness/control_gate.py — pause-flag + HITL decision helpers consumed by
the orchestrator's run_pipeline loop.

All helpers degrade gracefully on missing/corrupt control state — the
default behavior is "no gate" so a fresh checkout with no
``state/control/`` directory is bit-identical to pre-E4 orchestrator
behavior. Critique #13 (pause-flag IO errors must not crash the loop) is
honored: ``check_pause`` swallows EISDIR/EACCES/FileNotFoundError with a
single rate-limited WARNING and returns False.

Stdlib only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional, Callable

logger = logging.getLogger("janusmask.control_gate")

DEFAULT_PAUSE_FLAG = "state/control/orchestrator.flag"
DEFAULT_DECISIONS_DIR = "state/control/decisions"
DEFAULT_APPROVAL_TIMEOUT = 1800.0  # 30 min

# Single source of truth for the phases an operator may gate via
# control.require_approval. Consumed by tools/webui_control.put_config_control
# (validation) and surfaced to the WebUI via GET /api/control/phases so the
# Config <select> populates from one list instead of a drifting literal
# (WUI-PHASES).
KNOWN_PHASES: tuple[str, ...] = (
    "synthesis",
    "fuzzing",
    "cross_examination",
    "ast_validation",
    "accepted",
    "rejected",
    "decomposition",
)
_DECISION_POLL_INTERVAL = 1.0
_PAUSE_LOG_RATE_LIMIT = 60.0
_last_pause_warning: dict[str, float] = {}


def _control_section(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("control", {}) if isinstance(config, dict) else {}


def pause_flag_path(state_dir: Path, config: dict[str, Any]) -> Path:
    rel = _control_section(config).get("pause_flag_path") or DEFAULT_PAUSE_FLAG
    p = Path(rel)
    if not p.is_absolute():
        p = Path(state_dir).parent / rel
    return p


def decisions_dir(state_dir: Path, config: dict[str, Any]) -> Path:
    rel = _control_section(config).get("decisions_dir") or DEFAULT_DECISIONS_DIR
    p = Path(rel)
    if not p.is_absolute():
        p = Path(state_dir).parent / rel
    return p


def check_pause(state_dir: Path, config: dict[str, Any]) -> bool:
    """Return True iff the pause flag is set to ``paused``.

    Critique #13: tolerates EISDIR/EACCES/FileNotFoundError without
    crashing — degrades to False with a rate-limited WARNING.
    """
    path = pause_flag_path(state_dir, config)
    try:
        contents = path.read_text(errors="replace").strip().lower()
    except FileNotFoundError:
        return False
    except (IsADirectoryError, PermissionError, OSError) as e:
        key = f"{path}:{type(e).__name__}"
        now = time.time()
        if now - _last_pause_warning.get(key, 0) > _PAUSE_LOG_RATE_LIMIT:
            logger.warning(
                "pause flag at %s unreadable (%s); treating as not-paused",
                path, e,
            )
            _last_pause_warning[key] = now
        return False
    return contents == "paused"


def require_approval_for(phase: str, config: dict[str, Any]) -> bool:
    requires = _control_section(config).get("require_approval", []) or []
    return phase in requires


def _read_decision(path: Path) -> Optional[dict]:
    """Return decision dict if present + parseable; None on absent/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        logger.warning("decision file %s corrupt: %s", path, e)
        return None
    if not isinstance(data, dict) or "decision" not in data:
        return None
    return data


def await_decision(
    state_dir: Path,
    task_id: str,
    phase: str,
    config: dict[str, Any],
    *,
    emit_pending: Optional[Callable] = None,
    emit_timeout: Optional[Callable] = None,
    poll_interval: float = _DECISION_POLL_INTERVAL,
    timeout: Optional[float] = None,
) -> str:
    """Block until ``state/control/decisions/{task_id}.json`` exists.

    Returns the decision string ('approve' / 'reject' / 'retry') or
    ``'timeout'`` after ``timeout`` seconds. Returns ``'auto'`` immediately
    when the task's phase is not in ``config['control']['require_approval']``
    — this is the default no-op path that keeps the orchestrator
    bit-identical when the operator has not opted in.
    """
    if not require_approval_for(phase, config):
        return "auto"
    if timeout is None:
        timeout = float(_control_section(config).get(
            "approval_timeout_sec", DEFAULT_APPROVAL_TIMEOUT))
    decisions = decisions_dir(state_dir, config)
    decisions.mkdir(parents=True, exist_ok=True)
    path = decisions / f"{task_id}.json"
    if emit_pending is not None:
        try:
            emit_pending(task_id, phase)
        except Exception:
            logger.exception("emit_pending callback failed")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = _read_decision(path)
        if rec is not None:
            return str(rec.get("decision", "")).lower() or "auto"
        time.sleep(poll_interval)
    if emit_timeout is not None:
        try:
            emit_timeout(task_id, phase)
        except Exception:
            logger.exception("emit_timeout callback failed")
    return "timeout"


def record_agent_pid(state_dir: Path, agent: str, pid: int) -> None:
    """Best-effort: stamp ``STATE.json`` with ``{agent}_pid``.

    Errors are swallowed — pid recording is observability, not correctness.
    """
    try:
        from harness import state as _state
    except Exception:
        return
    try:
        def _set(s):
            s[f"{agent}_pid"] = pid
            return s
        _state.locked_read_modify_write(_set, state_dir)
    except Exception as e:
        logger.warning("could not record %s_pid=%s: %s", agent, pid, e)


from harness import model_backends


def backend_choices():
    return list(model_backends.BACKEND_REGISTRY)


from harness import webui_config_schema


def typed_config_schema():
    return webui_config_schema.CONFIG_FIELDS
''',
}

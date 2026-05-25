"""Adversarial coverage for the consumer side of the hooks config contract.

F3 has already verified that ``config/claude_worker_hooks.json`` and
``config/claude_worker_planning_hooks.json`` parse and carry the
expected top-level keys. This battery hammers what consumes them:

  * ``harness.orchestrator._build_agent_command``'s table-rewrite from
    the MCP-era worker-config paths to the hook-declaring paths
    (``_HOOK_CONFIG_REWIRE_SYNTHESIS`` / ``_HOOK_CONFIG_REWIRE_PLANNING``)
    keyed on ``JANUSMASK_MODE``.
  * The actual hook subprocess wire format — every registered command
    must produce stdout the Claude CLI can parse: a ``decision``
    payload for the gating events (PreToolUse / PostToolUse / Stop /
    UserPromptSubmit) and a ``continue`` payload for the lifecycle
    events (SessionStart / PreCompact). The decision token, when
    present, must be one of ``allow`` or ``deny``.
  * ``_build_agent_env`` propagation: every JANUSMASK_* the worker
    hooks read must land in the spawned subprocess env.
  * Cross-mode JSON schema integrity that complements F3's checks
    (planning superset of synthesis hooks, no shell metacharacters in
    commands, planning permissions allow ``Agent`` while synthesis
    keeps it denied, round-trip JSON safe).

Constraints honoured (per task brief):
  * Tests only; subprocess invocations carry a 5s timeout; no
    dependency on the Claude or Gemini CLIs being installed.
  * Tests that expose a real schema or runtime regression are
    ``xfail``'d with reason; they are never deleted.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from unittest import mock

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import orchestrator as orch_mod  # noqa: E402

CONFIG_DIR = PROJECT_ROOT / "config"
SYNTH_HOOKS_PATH = CONFIG_DIR / "claude_worker_hooks.json"
PLAN_HOOKS_PATH = CONFIG_DIR / "claude_worker_planning_hooks.json"
LEGACY_WORKER_PATH = str(PROJECT_ROOT / "config" / "claude_worker.json")
LEGACY_GEMINI_POLICY_PATH = str(PROJECT_ROOT / "config" / "gemini_worker_policy.toml")

# Subprocess timeout for every hook spawn — keeps a regressed hook from
# wedging the test session. The brief mandates 5s.
HOOK_SUBPROCESS_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_janusmask_env(monkeypatch):
    """Strip JANUSMASK_* from the parent env so each test starts clean."""
    for key in list(os.environ):
        if key.startswith("JANUSMASK_"):
            monkeypatch.delenv(key, raising=False)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _config_with_legacy_args(extra_args=None):
    """Synthetic config.yaml-equivalent dict whose claude/gemini args still
    name the legacy MCP-era worker config paths so the rewire is exercised.
    """
    extra_args = list(extra_args or [])
    return {
        "agents": {
            "claude": {
                "command": "claude",
                "args": [
                    "-p",
                    "--settings",
                    LEGACY_WORKER_PATH,
                    *extra_args,
                ],
            },
            "gemini": {
                "command": "gemini",
                "args": [
                    "-p",
                    "--admin-policy",
                    LEGACY_GEMINI_POLICY_PATH,
                ],
            },
        }
    }


# ---------------------------------------------------------------------------
# Section 1 — JSON schema integrity (consumer-side specifics)
# ---------------------------------------------------------------------------


REGISTERED_EVENT_NAMES = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "PreCompact",
)


@pytest.mark.parametrize("hooks_path", [SYNTH_HOOKS_PATH, PLAN_HOOKS_PATH])
def test_hook_commands_point_to_real_python_modules(hooks_path):
    """Every ``python3 -m <module>`` referenced in a hook command must
    resolve to an importable module on the project's PYTHONPATH; a typo
    would silently make Claude CLI fail open after the timeout."""
    cfg = _load(hooks_path)
    targets: list[str] = []
    for event_name in REGISTERED_EVENT_NAMES:
        for matcher_block in cfg.get("hooks", {}).get(event_name, []):
            for hook_entry in matcher_block.get("hooks", []):
                cmd = hook_entry.get("command", "")
                if "python3 -m " in cmd:
                    module = cmd.split("python3 -m ", 1)[1].split()[0]
                    targets.append(module)
    assert targets, f"no python3 -m hook commands found in {hooks_path}"
    failed: list[str] = []
    for module in targets:
        try:
            __import__(module)
        except Exception as exc:  # pragma: no cover - failure is the report
            failed.append(f"{module}: {exc!r}")
    assert not failed, (
        f"hook command modules failed to import for {hooks_path.name}: "
        + "; ".join(failed)
    )


@pytest.mark.parametrize("hooks_path", [SYNTH_HOOKS_PATH, PLAN_HOOKS_PATH])
def test_hook_timeouts_are_strictly_positive_integers(hooks_path):
    """Every registered hook timeout must be a positive int; a negative
    or zero value would expire instantly under Claude Code's hook
    runner, and a string would crash the runner's int coercion."""
    cfg = _load(hooks_path)
    bad: list[str] = []
    for event_name in REGISTERED_EVENT_NAMES:
        for matcher_block in cfg.get("hooks", {}).get(event_name, []):
            for hook_entry in matcher_block.get("hooks", []):
                t = hook_entry.get("timeout")
                if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
                    bad.append(f"{event_name}: timeout={t!r}")
    assert not bad, f"invalid timeouts in {hooks_path.name}: {bad}"


@pytest.mark.parametrize("hooks_path", [SYNTH_HOOKS_PATH, PLAN_HOOKS_PATH])
def test_hook_commands_have_no_shell_metacharacters(hooks_path):
    """Hook commands must not contain shell control sequences. Claude's
    runner spawns these via ``shell=False``; injecting ``;`` or ``|``
    would land as literal argv tokens and the hook would never run."""
    cfg = _load(hooks_path)
    forbidden = (";", "&&", "||", "$(", "`", "\n")
    bad: list[str] = []
    for event_name in REGISTERED_EVENT_NAMES:
        for matcher_block in cfg.get("hooks", {}).get(event_name, []):
            for hook_entry in matcher_block.get("hooks", []):
                cmd = hook_entry.get("command", "")
                for token in forbidden:
                    if token in cmd:
                        bad.append(f"{event_name}: {token!r} in {cmd!r}")
    assert not bad, f"shell-meta in commands ({hooks_path.name}): {bad}"


@pytest.mark.parametrize("hooks_path", [SYNTH_HOOKS_PATH, PLAN_HOOKS_PATH])
def test_no_duplicate_event_registrations(hooks_path):
    """Each event name should appear once at the top of the ``hooks``
    block. Duplicate keys would be silently coalesced by ``json.loads``,
    masking a contract bug — but the FILE itself must not contain them
    twice (a future hand-edit might add a second entry)."""
    raw = hooks_path.read_text(encoding="utf-8")
    for event_name in REGISTERED_EVENT_NAMES:
        # Match the ``"<EventName>": [`` pattern at the start of an
        # indented line (within the hooks block). One occurrence only.
        needle = f'"{event_name}":'
        assert raw.count(needle) <= 1, (
            f"{hooks_path.name}: '{event_name}' appears {raw.count(needle)} "
            "times; duplicate registrations would be silently coalesced."
        )


def test_hooks_json_round_trips_losslessly():
    """``json.loads(json.dumps(x)) == x`` must hold for both files —
    detects any non-JSON-safe value snuck in (NaN, +Infinity, bytes)."""
    for hooks_path in (SYNTH_HOOKS_PATH, PLAN_HOOKS_PATH):
        original = _load(hooks_path)
        round_tripped = json.loads(json.dumps(original, allow_nan=False))
        assert original == round_tripped, (
            f"{hooks_path.name} contains non-JSON-safe values "
            "(NaN/Infinity/bytes) that survive an initial parse but "
            "fail a strict re-emit."
        )


# ---------------------------------------------------------------------------
# Section 2 — Rewire correctness (mode-keyed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["", "synthesis"])
def test_build_command_rewires_to_synthesis_for_synth_or_unset_mode(
    mode, monkeypatch
):
    """Empty mode env defaults to ``synthesis`` per ``_paths.mode`` and
    the orchestrator's own ``os.environ.get('JANUSMASK_MODE', 'synthesis')``
    fallback. Both must select the synthesis rewire dict."""
    if mode:
        monkeypatch.setenv("JANUSMASK_MODE", mode)
    cfg = _config_with_legacy_args()
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert str(SYNTH_HOOKS_PATH) in cmd, (
        f"mode={mode!r} should select synthesis hooks config; got cmd={cmd}"
    )
    assert str(PLAN_HOOKS_PATH) not in cmd


@pytest.mark.parametrize(
    "mode", ["planning", "reconciliation", "anything-else", "PLANNING"]
)
def test_build_command_rewires_to_planning_for_non_synthesis_modes(
    mode, monkeypatch
):
    """The orchestrator's branch is ``synthesis`` vs. *anything-else* —
    so reconciliation and even an unknown mode end up on the planning
    rewire dict. ``PLANNING`` (uppercase) is a real adversary because
    it's *not* equal to ``synthesis`` — must route to planning even
    though it's not a recognised mode."""
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    cfg = _config_with_legacy_args()
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert str(PLAN_HOOKS_PATH) in cmd, (
        f"mode={mode!r} should fall through to planning rewire; got cmd={cmd}"
    )
    assert str(SYNTH_HOOKS_PATH) not in cmd


@pytest.mark.parametrize("mode", ["synthesis ", "synthesis\n"])
def test_build_command_treats_whitespace_padded_synthesis_as_non_synthesis(
    mode, monkeypatch
):
    """``_build_agent_command`` performs a literal ``mode == 'synthesis'``
    comparison — trailing whitespace breaks equality and falls through
    to planning. This pins the (mildly surprising) current behaviour so
    a future edit that strips whitespace silently flips the contract."""
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    cfg = _config_with_legacy_args()
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert str(PLAN_HOOKS_PATH) in cmd, (
        f"mode={mode!r} (whitespace-padded) routes to planning under "
        "current strict-equality rewire logic"
    )


def test_rewire_constants_keyed_on_legacy_path_string_identity():
    """The rewire dict is keyed on the absolute legacy path string. If
    a future maintainer relativised the paths in config.yaml without
    also updating these constants, the rewire would silently no-op and
    the worker would spawn against the MCP-era config (no hooks)."""
    assert LEGACY_WORKER_PATH in orch_mod._HOOK_CONFIG_REWIRE_SYNTHESIS
    assert LEGACY_WORKER_PATH in orch_mod._HOOK_CONFIG_REWIRE_PLANNING
    assert (
        orch_mod._HOOK_CONFIG_REWIRE_SYNTHESIS[LEGACY_WORKER_PATH]
        == str(SYNTH_HOOKS_PATH)
    )
    assert (
        orch_mod._HOOK_CONFIG_REWIRE_PLANNING[LEGACY_WORKER_PATH]
        == str(PLAN_HOOKS_PATH)
    )


def test_rewire_no_op_when_args_already_use_post_migration_paths(monkeypatch):
    """If config.yaml is migrated to point directly at the hooks JSON,
    the rewire becomes an identity transform — verify the post-rewire
    arg list is unchanged (no double-rewriting, no path corruption)."""
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cfg = {
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["-p", "--settings", str(SYNTH_HOOKS_PATH)],
            }
        }
    }
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert cmd.count(str(SYNTH_HOOKS_PATH)) == 1, (
        f"rewire must be idempotent on already-migrated paths; got {cmd}"
    )


def test_rewire_planning_also_swaps_gemini_policy(monkeypatch):
    """Planning rewire is wider than synthesis — it also swaps the
    Gemini admin policy. Synthesis rewire must NOT swap gemini policy
    (asymmetry is intentional per HOOK-41 docstring)."""
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cfg = _config_with_legacy_args()
    cmd = orch_mod._build_agent_command("gemini", "PROMPT", cfg)
    # Planning swaps gemini policy too.
    assert any("gemini_worker_policy_planning.toml" in a for a in cmd), (
        f"planning mode must rewire gemini policy too; got {cmd}"
    )

    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cmd = orch_mod._build_agent_command("gemini", "PROMPT", cfg)
    # Synthesis leaves gemini policy alone.
    assert any(a == LEGACY_GEMINI_POLICY_PATH for a in cmd), (
        f"synthesis must NOT rewire gemini policy; got {cmd}"
    )


# ---------------------------------------------------------------------------
# Section 3 — Cross-mode permissions integrity
# ---------------------------------------------------------------------------


def test_synthesis_permissions_deny_agent_tool():
    """Synthesis must NOT carry ``Agent`` in its allow list — sub-agents
    are a planning-only escape hatch."""
    cfg = _load(SYNTH_HOOKS_PATH)
    allow = set(cfg["permissions"]["allow"])
    deny = set(cfg["permissions"]["deny"])
    assert "Agent" in deny
    assert "Agent" not in allow


def test_planning_permissions_allow_agent_tool():
    """Planning must carry ``Agent`` in its allow list — this is the
    documented superset-of-synthesis property."""
    cfg = _load(PLAN_HOOKS_PATH)
    allow = set(cfg["permissions"]["allow"])
    assert "Agent" in allow, (
        "planning hooks JSON must allow Agent (sub-agent) tool extension; "
        "missing this kills planner sub-agent decomposition"
    )


def test_synthesis_denies_bash_so_pre_tool_gate_is_reachable():
    """If Bash were ever moved out of the deny list, the PreToolUse
    hook would still gate it (Bash not in ALLOWED_TOOLS) — but the
    layered defence is the contract: deny at admin policy first,
    hook-gate second. Pin both halves."""
    cfg = _load(SYNTH_HOOKS_PATH)
    deny = set(cfg["permissions"]["deny"])
    assert "Bash" in deny
    # Defence-in-depth: same key never present in allow.
    assert "Bash" not in set(cfg["permissions"]["allow"])


def test_event_set_planning_is_superset_of_synthesis():
    """Every event the synthesis worker registers must also appear in
    the planning worker's hooks block. A planning-only registration
    (e.g. extra Stop matcher) is fine; a synthesis-only one would be a
    bug — planning would lose the gate that fires for it."""
    synth_events = set(_load(SYNTH_HOOKS_PATH).get("hooks", {}).keys())
    plan_events = set(_load(PLAN_HOOKS_PATH).get("hooks", {}).keys())
    missing = synth_events - plan_events
    assert not missing, (
        f"planning hooks JSON missing events present in synthesis: {missing}"
    )


def test_synthesis_and_planning_register_same_module_per_event():
    """For each event registered in BOTH configs, the underlying hook
    module command should match. Drift here means planning gets a
    different gate than synthesis for the same lifecycle event."""
    synth_hooks = _load(SYNTH_HOOKS_PATH)["hooks"]
    plan_hooks = _load(PLAN_HOOKS_PATH)["hooks"]
    common = set(synth_hooks.keys()) & set(plan_hooks.keys())
    assert common, "no overlapping events — schema integrity failed earlier"
    drift: list[str] = []
    for event in common:
        s_cmds = sorted(
            h["command"]
            for block in synth_hooks[event]
            for h in block.get("hooks", [])
        )
        p_cmds = sorted(
            h["command"]
            for block in plan_hooks[event]
            for h in block.get("hooks", [])
        )
        if s_cmds != p_cmds:
            drift.append(f"{event}: synth={s_cmds} plan={p_cmds}")
    assert not drift, f"command drift across configs: {drift}"


# ---------------------------------------------------------------------------
# Section 4 — Hook subprocess wire format
# ---------------------------------------------------------------------------

# Per-event expected wire-format keys. PreToolUse / PostToolUse / Stop
# emit a ``decision`` token in {allow, deny}. UserPromptSubmit emits
# ``decision`` *and* ``hookSpecificOutput``. SessionStart / PreCompact
# emit ``continue`` (no ``decision``).
DECISION_EVENTS = {
    "PreToolUse": {"hook_event_name": "PreToolUse", "tool_name": "Read",
                   "tool_input": {"file_path": "/tmp/x"},
                   "session_id": "wireformat-sess"},
    "PostToolUse": {"hook_event_name": "PostToolUse", "tool_name": "Write",
                    "tool_input": {"file_path": "/tmp/x"},
                    "tool_response": {"success": True, "filePath": "/tmp/x"},
                    "session_id": "wireformat-sess"},
    "Stop": {"hook_event_name": "Stop", "stop_hook_active": True,
             "session_id": "wireformat-sess"},
    "UserPromptSubmit": {"hook_event_name": "UserPromptSubmit",
                         "session_id": "wireformat-sess",
                         "prompt": "hello"},
}

CONTINUE_EVENTS = {
    "PreCompact": {"hook_event_name": "PreCompact", "trigger": "auto",
                   "session_id": "wireformat-sess"},
}


def _spawn_hook(module: str, payload: dict, env_extra: dict | None = None):
    """Spawn ``python3 -m <module>`` with ``payload`` on stdin and return
    a (stdout_text, stderr_text, returncode) triple. Always carries a
    5s timeout — a wedged hook fails the test rather than blocking."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env.setdefault("JANUSMASK_AGENT", "claude")
    env.setdefault("JANUSMASK_MODE", "synthesis")
    if env_extra:
        env.update(env_extra)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", module],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=HOOK_SUBPROCESS_TIMEOUT,
            env=env,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"hook {module} did not respond within {HOOK_SUBPROCESS_TIMEOUT}s"
        )
    return completed.stdout, completed.stderr, completed.returncode


@pytest.mark.parametrize("event,module", [
    ("PreToolUse", "harness.hooks.claude.pre_tool"),
    ("PostToolUse", "harness.hooks.claude.post_tool"),
    ("Stop", "harness.hooks.claude.stop"),
    ("UserPromptSubmit", "harness.hooks.claude.user_prompt_submit"),
])
def test_decision_hook_emits_valid_decision_payload(event, module, tmp_path):
    """Every decision-emitting hook must produce a JSON object on
    stdout with a ``decision`` key whose value is one of ``allow`` or
    ``deny``. Emitting anything else would crash Claude CLI's JSON
    parser at the hook boundary, silently failing open."""
    payload = DECISION_EVENTS[event]
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    work_dir = state_dir / "workdirs" / "claude" / "wireformat-sess"
    (work_dir / "outbox").mkdir(parents=True)
    (work_dir / "ledger").mkdir(parents=True)
    env_extra = {
        "JANUSMASK_STATE_DIR": str(state_dir),
        "JANUSMASK_WORK_DIR": str(work_dir),
        "JANUSMASK_AGENT": "claude",
        "JANUSMASK_MODE": "synthesis",
        "JANUSMASK_ROUND": "1",
    }
    stdout, stderr, rc = _spawn_hook(module, payload, env_extra=env_extra)
    assert rc == 0, f"{module} exited {rc}; stderr={stderr!r}"
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{module} stdout not valid JSON: {exc}; raw={stdout!r}"
        )
    assert isinstance(parsed, dict), f"{module} stdout must be a JSON object"
    assert "decision" in parsed, (
        f"{module} stdout missing 'decision' key; got {parsed}"
    )
    assert parsed["decision"] in {"allow", "deny"}, (
        f"{module} emitted decision={parsed['decision']!r} which is "
        "outside the allow/deny vocabulary the runner accepts"
    )


@pytest.mark.parametrize("event,module", [
    ("PreCompact", "harness.hooks.claude.pre_compact"),
])
def test_lifecycle_hook_emits_continue_payload(event, module, tmp_path):
    """Lifecycle hooks (PreCompact) emit ``{continue: bool, ...}`` —
    they are advisory, not gating. Stdout must still be valid JSON."""
    payload = CONTINUE_EVENTS[event]
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    work_dir = state_dir / "workdirs" / "claude" / "wireformat-sess"
    (work_dir / "outbox").mkdir(parents=True)
    (work_dir / "ledger").mkdir(parents=True)
    env_extra = {
        "JANUSMASK_STATE_DIR": str(state_dir),
        "JANUSMASK_WORK_DIR": str(work_dir),
        "JANUSMASK_AGENT": "claude",
        "JANUSMASK_MODE": "synthesis",
        "JANUSMASK_ROUND": "1",
    }
    stdout, stderr, rc = _spawn_hook(module, payload, env_extra=env_extra)
    assert rc == 0, f"{module} exited {rc}; stderr={stderr!r}"
    parsed = json.loads(stdout)
    assert isinstance(parsed, dict)
    assert "continue" in parsed, (
        f"{module} stdout missing 'continue' key; got {parsed}"
    )
    assert isinstance(parsed["continue"], bool)


def test_session_start_with_inbox_staged_emits_continue_true(tmp_path):
    """SessionStart returns ``continue: True`` only when the inbox is
    pre-staged. With a staged ``task.json`` we should see continue=True
    plus ``hookSpecificOutput``. Without staging, this hook returns
    ``continue: False`` with a stopReason — a separate adversarial
    case below."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    work_dir = state_dir / "workdirs" / "claude" / "wireformat-sess"
    (work_dir / "inbox").mkdir(parents=True)
    (work_dir / "outbox").mkdir(parents=True)
    (work_dir / "ledger").mkdir(parents=True)
    (work_dir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T1", "constraints": {"deterministic": True}})
    )
    env_extra = {
        "JANUSMASK_STATE_DIR": str(state_dir),
        "JANUSMASK_WORK_DIR": str(work_dir),
        "JANUSMASK_AGENT": "claude",
        "JANUSMASK_MODE": "synthesis",
        "JANUSMASK_ROUND": "1",
    }
    payload = {
        "hook_event_name": "SessionStart",
        "session_id": "wireformat-sess",
        "source": "startup",
    }
    stdout, stderr, rc = _spawn_hook(
        "harness.hooks.claude.session_start", payload, env_extra=env_extra,
    )
    assert rc == 0, f"session_start exited {rc}; stderr={stderr!r}"
    parsed = json.loads(stdout)
    assert isinstance(parsed, dict)
    assert "continue" in parsed
    assert parsed["continue"] is True
    assert "hookSpecificOutput" in parsed


def test_session_start_without_inbox_emits_continue_false(tmp_path):
    """Mirror coverage: when inbox is missing, ``continue: False`` plus
    a ``stopReason`` is the contract. Pins the loud-fail-on-missing-
    staging behaviour from the hook docstring."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    work_dir = state_dir / "workdirs" / "claude" / "wireformat-sess-bad"
    (work_dir / "outbox").mkdir(parents=True)
    (work_dir / "ledger").mkdir(parents=True)
    # No inbox/task.json; expect continue=False
    env_extra = {
        "JANUSMASK_STATE_DIR": str(state_dir),
        "JANUSMASK_WORK_DIR": str(work_dir),
        "JANUSMASK_AGENT": "claude",
        "JANUSMASK_MODE": "synthesis",
        "JANUSMASK_ROUND": "1",
    }
    payload = {
        "hook_event_name": "SessionStart",
        "session_id": "wireformat-sess-bad",
        "source": "startup",
    }
    stdout, _stderr, rc = _spawn_hook(
        "harness.hooks.claude.session_start", payload, env_extra=env_extra,
    )
    assert rc == 0
    parsed = json.loads(stdout)
    assert parsed.get("continue") is False, parsed
    assert "stopReason" in parsed


# ---------------------------------------------------------------------------
# Section 5 — Env propagation contract through _build_agent_env
# ---------------------------------------------------------------------------


REQUIRED_HOOK_ENV = {
    "PYTHONHASHSEED",
    "JANUSMASK_AGENT",
    "JANUSMASK_STATE_DIR",
    "JANUSMASK_ROUND",
    "JANUSMASK_MODE",
    "JANUSMASK_TASK_ID",
    "JANUSMASK_WORK_DIR",
}


def test_build_env_contains_every_janusmask_key_a_hook_reads(tmp_path):
    """Every JANUSMASK_* the worker hooks consult on stdin/disk MUST
    appear in the env dict ``_build_agent_env`` produces — otherwise
    the hook would fall through to its default and we'd silently lose
    the gate."""
    env = orch_mod._build_agent_env("claude", str(tmp_path), round_number=2)
    missing = REQUIRED_HOOK_ENV - env.keys()
    assert not missing, f"_build_agent_env dropped keys: {missing}"


def test_build_env_pythonhashseed_is_pinned_to_zero(tmp_path):
    """PYTHONHASHSEED=0 makes per-process dict ordering deterministic.
    This is load-bearing for the equiv comparator (HOOK-51) — hashing
    drift across spawns would re-order ledger keys and false-positive
    the diff."""
    env = orch_mod._build_agent_env("claude", str(tmp_path), round_number=1)
    assert env["PYTHONHASHSEED"] == "0"


def test_build_env_gemini_settings_only_for_gemini(tmp_path):
    """JANUSMASK_GEMINI_SETTINGS must be set ONLY for the gemini agent
    — leaking it onto the claude env would have the gemini hook
    confuse the two settings sources during cross-agent debugging."""
    claude_env = orch_mod._build_agent_env("claude", str(tmp_path))
    assert "JANUSMASK_GEMINI_SETTINGS" not in claude_env
    gemini_env = orch_mod._build_agent_env("gemini", str(tmp_path))
    assert "JANUSMASK_GEMINI_SETTINGS" in gemini_env


def test_build_env_round_is_string_not_int(tmp_path):
    """Subprocess env values must be strings; an ``int`` would crash
    Popen with a TypeError. This test pins the str() coercion."""
    env = orch_mod._build_agent_env("claude", str(tmp_path), round_number=7)
    assert env["JANUSMASK_ROUND"] == "7"
    assert isinstance(env["JANUSMASK_ROUND"], str)


def test_build_env_inherits_task_id_from_parent(tmp_path, monkeypatch):
    """The orchestrator sets JANUSMASK_TASK_ID before spawning so the
    hook ledger row carries the right task. Pin pass-through."""
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-adversary")
    env = orch_mod._build_agent_env("claude", str(tmp_path), round_number=1)
    assert env["JANUSMASK_TASK_ID"] == "T-adversary"


# ---------------------------------------------------------------------------
# Section 6 — Rewire dict immutability under monkeypatched config paths
# ---------------------------------------------------------------------------


def test_rewire_is_keyed_on_string_not_module_global(monkeypatch):
    """Mutating ``_HOOK_CONFIG_REWIRE_SYNTHESIS`` at runtime to drop
    its only entry should leave the rewire as identity — proving the
    rewire is purely table-driven, not magic. This guards against a
    well-meaning refactor that turns the dict into a property or
    function that hides the lookup."""
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cfg = _config_with_legacy_args()
    monkeypatch.setattr(orch_mod, "_HOOK_CONFIG_REWIRE_SYNTHESIS", {})
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    # Identity rewire: legacy path stays, hooks path absent.
    assert LEGACY_WORKER_PATH in cmd
    assert str(SYNTH_HOOKS_PATH) not in cmd


def test_rewire_swap_two_entries_routes_per_dict_lookup(monkeypatch):
    """A monkeypatched rewire dict that maps one path to a third
    location must be honoured exactly. Proves no caching of the old
    table inside the function body."""
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cfg = _config_with_legacy_args()
    fake_target = "/tmp/fake_hooks_target.json"
    monkeypatch.setattr(
        orch_mod,
        "_HOOK_CONFIG_REWIRE_SYNTHESIS",
        {LEGACY_WORKER_PATH: fake_target},
    )
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert fake_target in cmd
    assert LEGACY_WORKER_PATH not in cmd


# ---------------------------------------------------------------------------
# Section 7 — Prompt placement is preserved through the rewire
# ---------------------------------------------------------------------------


def test_build_command_inserts_prompt_immediately_after_p_flag(monkeypatch):
    """``-p`` is the prompt flag; the rewire must not displace it.
    Pin the contract: the command list must contain ``-p PROMPT`` as
    consecutive tokens regardless of which mode rewires which path."""
    for mode in ("synthesis", "planning", "reconciliation"):
        monkeypatch.setenv("JANUSMASK_MODE", mode)
        cfg = _config_with_legacy_args()
        cmd = orch_mod._build_agent_command("claude", "MY_PROMPT", cfg)
        assert "-p" in cmd
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "MY_PROMPT", (
            f"mode={mode}: prompt must directly follow -p; got {cmd[idx:idx+3]}"
        )


def test_build_command_appends_p_when_args_lack_it(monkeypatch):
    """If ``args`` lacks ``-p`` entirely, the function appends ``-p
    PROMPT`` at the end. Mode does not change this fallback."""
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cfg = {
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["--settings", LEGACY_WORKER_PATH],
            }
        }
    }
    cmd = orch_mod._build_agent_command("claude", "P", cfg)
    assert cmd[-2:] == ["-p", "P"]
    # And the rewire still happened.
    assert str(SYNTH_HOOKS_PATH) in cmd

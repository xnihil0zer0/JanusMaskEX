"""Shared helpers for JanusMask meta-hook scripts.

The ledger (state/impl_progress.jsonl) is the single source of truth for
progress state. Required fields per row:
    {ts, phase, task_id, event, detail, files, exit}
Optional fields (present on subsets of rows):
    paths           - glob list scoping a scope_exception / scope_revoke;
                      also on blocker / blocker_resolved / observation rows
                      that reference affected files without changing them.
    approved_by     - human operator marker (e.g. "operator_<label>") on
                      scope_exception rows and on rows consuming one;
                      automated writers use "automated:<script>" to signal
                      the row is a breadcrumb, not operator-approved work.
    consume_on      - trigger that closes a scope_exception; usually
                      "test_pass".

Live event vocabulary (21 kinds):
    start, write, test_pass, test_fail,
    adv_pass, adv_fail, adversarial_complete,
    phase_gate_pass, phase_gate_fail,
    stop_block, stop_allow, rollback,
    blocked, blocker, blocker_discovered, blocker_resolved,
    scope_exception, scope_revoke,
    observation, session_end,
    meta_hook_disabled.

See hooks-augmented-hooks-implementation-plan.md §2-§4 for semantics.
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import os
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness._journal import write_jsonl_row  # noqa: E402


def _project_dir() -> pathlib.Path:
    raw = os.environ.get("JANUSMASK_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        return pathlib.Path(raw).resolve()
    return pathlib.Path(__file__).resolve().parent.parent


PROJECT_DIR = _project_dir()
LEDGER_PATH = PROJECT_DIR / "state" / "impl_progress.jsonl"
PRESERVE_PATH = PROJECT_DIR / "state" / "impl_preserve.md"

EXPECTED_BASE_SHA = "6f8f3f4"
UNIVERSAL_ALLOW = [
    "state/impl_progress.jsonl",
    "state/impl_preserve.md",
    "brief_hooks_*.md",
    "plan_hooks_*.json",
]

# Phase-scope allow-lists (hooks-augmented plan §4). META covers the bootstrap
# install of the meta-hooks themselves.
PHASE_ALLOW = {
    "META": [
        "scripts/impl_*.py",
        "scripts/impl_*.sh",
        "scripts/run_adv.py",
        "tests/adversarial/**",
        ".claude/settings.local.json",
    ],
    "P0": [
        "harness/orchestrator.py",
        "harness/mcp_server.py",
        "harness/cross_examiner.py",
        "harness/depth_validator.py",
        "harness/session_namer.py",
        "tests/**",
        "mock_agent.py",
        "test_runner2.py",
        "archive/**",
        ".gitignore",
    ],
    "P1": [
        "harness/hooks/**",
        "harness/config.yaml",
        "harness/config_loader.py",
        "tests/hooks/**",
        "harness/mcp_server.py",
        "harness/track_record*.py",
    ],
    "P2": [
        "harness/hooks/claude/**",
        "harness/hooks/rpc/**",
        "config/claude_worker_hooks.json",
        "config/claude_worker_planning_hooks.json",
        "harness/hook_pre_tool.py",
        "tests/hooks/**",
    ],
    "P3": [
        "harness/hooks/gemini/**",
        "config/gemini_worker_policy.toml",
        "config/gemini_worker_policy_planning.toml",
        "config/gemini_settings.json",
        "tests/hooks/**",
    ],
    "P4": [
        "harness/orchestrator.py",
        "harness/agent_streamer.py",
        "harness/cross_examiner.py",
        "harness/planner/reconciliation.py",
        "harness/hook_pre_tool.py",
        "tests/hooks/invariants/**",
    ],
    "P5": [
        "harness/config.yaml",
        "harness/hooks_equivalence.py",
        "state/hooks/shadow/**",
        "tests/hooks/**",
        "state/hooks/rollback_signal",
    ],
}

# Task manifests drive DoD gaps. `acceptance_files` paths must exist.
# `adv_required` means one adv_pass row is required before Stop is allowed.
TASK_MANIFESTS = {
    "META-00-install-hooks": {
        "phase": "META",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "scripts/impl_common.py",
            "scripts/impl_session_start.sh",
            "scripts/impl_prompt_context.sh",
            "scripts/impl_pre_write.py",
            "scripts/impl_pre_bash.py",
            "scripts/impl_post_write.py",
            "scripts/impl_stop_gate.py",
            "scripts/impl_pre_compact.py",
            "scripts/impl_phase_gate.py",
            "scripts/run_adv.py",
            "tests/adversarial/test_meta_hooks.py",
        ],
    },
    "P0.4": {
        "phase": "P0",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": ["harness/orchestrator.py", "harness/mcp_server.py"],
    },
    "P0.3": {
        "phase": "P0",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/cross_examiner.py",
            "harness/orchestrator.py",
            "harness/mcp_server.py",
        ],
    },
    "P0.1": {
        "phase": "P0",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": ["harness/orchestrator.py"],
    },
    "P0.2": {
        "phase": "P0",
        "adv_required": True,
        "phase_gate_required": True,
        "acceptance_files": ["harness/orchestrator.py"],
    },
    "HOOK-10-scaffold-common": {
        "phase": "P1",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/__init__.py",
            "harness/hooks/_common.py",
            "harness/hooks/_paths.py",
            "harness/hooks/_ledger.py",
            "harness/hooks/_state_gates.py",
            "tests/hooks/__init__.py",
            "tests/hooks/unit/__init__.py",
            "tests/hooks/unit/test_scaffold_common.py",
            "tests/adversarial/test_P1_scaffold.py",
        ],
    },
    "HOOK-11-extract-rpc": {
        "phase": "P1",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/rpc/__init__.py",
            "harness/hooks/rpc/submit_code.py",
            "harness/hooks/rpc/submit_plan_draft.py",
            "harness/hooks/rpc/submit_reconciliation.py",
            "harness/hooks/rpc/clarification.py",
            "harness/hooks/rpc/error_report.py",
            "harness/mcp_server.py",
            "tests/hooks/unit/test_rpc.py",
            "tests/hooks/unit/test_rpc_adversarial.py",
        ],
    },
    "HOOK-12-extract-console": {
        "phase": "P1",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/console.py",
            "harness/mcp_server.py",
            "tests/hooks/unit/test_console.py",
            "tests/hooks/unit/test_console_adversarial.py",
        ],
    },
    "HOOK-13-config-flag": {
        "phase": "P1",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/config.yaml",
            "harness/config_loader.py",
            "tests/hooks/unit/test_hooks_config.py",
            "tests/hooks/unit/test_hooks_config_adversarial.py",
        ],
    },
    "HOOK-14-track-record-ast-events": {
        "phase": "P1",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/rpc/submit_code.py",
            "harness/mcp_server.py",
            "tests/hooks/unit/test_submit_code_events.py",
            "tests/adversarial/test_P1_track_record_events.py",
        ],
    },
    "HOOK-20-claude-session-start": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/__init__.py",
            "harness/hooks/claude/_env.py",
            "harness/hooks/claude/session_start.py",
            "tests/hooks/unit/test_claude_session_start.py",
            "tests/adversarial/test_P2_session_start.py",
        ],
    },
    "HOOK-21-claude-user-prompt-submit": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/user_prompt_submit.py",
            "tests/hooks/unit/test_claude_user_prompt_submit.py",
            "tests/adversarial/test_P2_user_prompt_submit.py",
        ],
    },
    "HOOK-22-claude-pre-tool": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/pre_tool.py",
            "tests/hooks/unit/test_claude_pre_tool.py",
            "tests/adversarial/test_P2_pre_tool.py",
        ],
    },
    "HOOK-23-claude-post-tool": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/post_tool.py",
            "tests/hooks/unit/test_claude_post_tool.py",
            "tests/adversarial/test_P2_post_tool.py",
        ],
    },
    "HOOK-24-claude-stop": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/stop.py",
            "tests/hooks/unit/test_claude_stop.py",
            "tests/adversarial/test_P2_stop.py",
        ],
    },
    "HOOK-25-claude-pre-compact": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/claude/pre_compact.py",
            "tests/hooks/unit/test_claude_pre_compact.py",
            "tests/adversarial/test_P2_pre_compact.py",
        ],
    },
    "HOOK-26-settings-authoritative": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "config/claude_worker_hooks.json",
            "config/claude_worker_planning_hooks.json",
            "tests/hooks/unit/test_worker_hook_settings.py",
            "tests/hooks/unit/test_claude_worker_settings_adversarial.py",
        ],
    },
    "HOOK-27-hook-pre-tool-shim": {
        "phase": "P2",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hook_pre_tool.py",
            "tests/hooks/unit/test_hook_pre_tool_shim.py",
            "tests/adversarial/test_P2_hook_pre_tool_shim.py",
        ],
    },
    "HOOK-30-gemini-session-entry": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/gemini/__init__.py",
            "harness/hooks/gemini/_env.py",
            "harness/hooks/gemini/session_start.py",
            "tests/hooks/unit/test_gemini_session_start.py",
            "tests/adversarial/test_P3_session_start.py",
        ],
    },
    "HOOK-31-gemini-user-prompt": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/gemini/user_prompt_submit.py",
            "tests/hooks/unit/test_gemini_user_prompt_submit.py",
            "tests/adversarial/test_P3_user_prompt_submit.py",
        ],
    },
    "HOOK-32-gemini-pre-tool": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/gemini/pre_tool.py",
            "tests/hooks/unit/test_gemini_pre_tool.py",
            "tests/adversarial/test_P3_pre_tool.py",
        ],
    },
    "HOOK-33-gemini-post-tool": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/gemini/post_tool.py",
            "tests/hooks/unit/test_gemini_post_tool.py",
            "tests/adversarial/test_P3_post_tool.py",
        ],
    },
    "HOOK-34-gemini-stop": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks/gemini/stop.py",
            "tests/hooks/unit/test_gemini_stop.py",
            "tests/adversarial/test_P3_stop.py",
        ],
    },
    "HOOK-35-gemini-policy-config": {
        "phase": "P3",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "config/gemini_worker_policy.toml",
            "config/gemini_worker_policy_planning.toml",
            "config/gemini_settings.json",
            "tests/hooks/unit/test_gemini_worker_settings.py",
            "tests/hooks/unit/test_gemini_worker_settings_adversarial.py",
        ],
    },
    "HOOK-40-orchestrator-env-flow": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/orchestrator.py",
            "tests/hooks/invariants/test_orchestrator_env_flow.py",
            "tests/adversarial/test_P4_env_flow.py",
        ],
    },
    "HOOK-41-orchestrator-config-pointers": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/orchestrator.py",
            "tests/hooks/invariants/test_orchestrator_config_pointers.py",
            "tests/adversarial/test_P4_config_pointers.py",
        ],
    },
    "HOOK-42-cross-examiner-shim": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/cross_examiner.py",
            "tests/hooks/invariants/test_cross_examiner_shim.py",
            "tests/adversarial/test_P4_cross_examiner_shim.py",
        ],
    },
    "HOOK-43-reconciliation-shim": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/planner/reconciliation.py",
            "tests/hooks/invariants/test_reconciliation_shim.py",
            "tests/adversarial/test_P4_reconciliation_shim.py",
        ],
    },
    "HOOK-44-agent-streamer-passthrough": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/agent_streamer.py",
            "tests/hooks/invariants/test_agent_streamer_passthrough.py",
            "tests/adversarial/test_P4_agent_streamer_passthrough.py",
        ],
    },
    "HOOK-45-hook-pre-tool-retire": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hook_pre_tool.py",
            "tests/hooks/invariants/test_hook_pre_tool_retire.py",
            "tests/adversarial/test_P4_hook_pre_tool_retire.py",
        ],
    },
    "HOOK-46-invariants-battery": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "tests/hooks/invariants/test_nine_invariants.py",
            "tests/adversarial/test_P4_nine_invariants.py",
        ],
    },
    "HOOK-47-ast-retry-prompt-regression": {
        "phase": "P4",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "tests/hooks/invariants/test_ast_retry_prompt_regression.py",
            "tests/adversarial/test_P4_ast_retry_prompt_regression.py",
        ],
    },
    "HOOK-50-shadow-logging": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_equivalence.py",
            "tests/adversarial/test_P5_shadow_logging.py",
        ],
    },
    "HOOK-51-equiv-comparator": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_equivalence_comparator.py",
            "tests/adversarial/test_P5_equiv_comparator.py",
        ],
    },
    "HOOK-52-diff-gate": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_diff_gate.py",
            "tests/hooks/unit/test_hooks_diff_gate_adversarial.py",
        ],
    },
    "HOOK-53-canary-enforce": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_canary.py",
            "tests/adversarial/test_P5_canary_enforce.py",
        ],
    },
    "HOOK-54-rollback-wiring": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_rollback.py",
            "tests/adversarial/test_P5_rollback_wiring.py",
        ],
    },
    "HOOK-55-drain-e2e": {
        "phase": "P5",
        "adv_required": True,
        "phase_gate_required": False,
        "acceptance_files": [
            "harness/hooks_equivalence.py",
            "tests/hooks/unit/test_hooks_drain.py",
            "tests/adversarial/test_P5_drain_e2e.py",
        ],
    },
}


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger(path: pathlib.Path | None = None) -> list[dict]:
    path = path or LEDGER_PATH
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_impl_progress_event(
    event: str,
    task_id: str = "",
    phase: str = "",
    detail: str = "",
    files: list[str] | None = None,
    exit_code: int = 0,
    path: pathlib.Path | None = None,
) -> dict:
    path = path or LEDGER_PATH
    row = {
        "ts": now_iso(),
        "phase": phase,
        "task_id": task_id,
        "event": event,
        "detail": detail,
        "files": files or [],
        "exit": exit_code,
    }
    write_jsonl_row(path, row)
    return row


def task_manifest(task_id: str) -> dict:
    return TASK_MANIFESTS.get(task_id, {})


def _glob_match(path: str, pattern: str) -> bool:
    if "**" in pattern:
        parts = pattern.split("**")
        regex = ".*".join(re.escape(p).replace(r"\*", r"[^/]*") for p in parts)
        return re.match("^" + regex + "$", path) is not None
    return fnmatch.fnmatch(path, pattern)


def path_in_allow(rel_path: str, globs: list[str]) -> bool:
    return any(_glob_match(rel_path, g) for g in globs)


def phase_allow_globs(phase: str) -> list[str]:
    return list(UNIVERSAL_ALLOW) + list(PHASE_ALLOW.get(phase, []))


def derive_state(ledger: list[dict] | None = None) -> dict:
    if ledger is None:
        ledger = load_ledger()
    passes_by_task: dict[str, set[str]] = {}
    for row in ledger:
        ev = row.get("event", "")
        tid = row.get("task_id", "")
        if ev in ("test_pass", "adv_pass") and tid:
            passes_by_task.setdefault(tid, set()).add(ev)
    current_phase = ""
    current_task = ""
    for row in reversed(ledger):
        if row.get("event") != "start":
            continue
        tid = row.get("task_id", "")
        passes = passes_by_task.get(tid, set())
        manifest = task_manifest(tid)
        closed = "test_pass" in passes
        if closed and (not manifest.get("adv_required") or "adv_pass" in passes):
            continue
        current_task = tid
        current_phase = row.get("phase", "")
        break
    tail = ledger[-150:] if ledger else []
    rollback = any(r.get("event") == "rollback" for r in tail)
    return {
        "current_phase": current_phase,
        "current_task_id": current_task,
        "rollback_signal": rollback,
        "last_rows": ledger[-5:] if ledger else [],
    }


def adv_satisfied(ledger: list[dict], task_id: str) -> bool:
    return any(
        r.get("event") == "adv_pass" and r.get("task_id") == task_id for r in ledger
    )


def test_passed(ledger: list[dict], task_id: str) -> bool:
    return any(
        r.get("event") == "test_pass" and r.get("task_id") == task_id for r in ledger
    )


def _ts_to_epoch(ts: str) -> float | None:
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    return None


def compute_dod_gaps(task_id: str, ledger: list[dict] | None = None) -> list[str]:
    if ledger is None:
        ledger = load_ledger()
    manifest = task_manifest(task_id)
    if not manifest:
        return []
    gaps: list[str] = []
    writes = [r for r in ledger if r.get("event") == "write" and r.get("task_id") == task_id]
    tests = [r for r in ledger if r.get("event") == "test_pass" and r.get("task_id") == task_id]
    fails = [r for r in ledger if r.get("event") == "test_fail" and r.get("task_id") == task_id]
    last_write_ts = writes[-1]["ts"] if writes else None
    last_test_ts = tests[-1]["ts"] if tests else None
    last_fail_ts = fails[-1]["ts"] if fails else None
    if writes and (not last_test_ts or last_test_ts < last_write_ts):
        gaps.append(f"No test_pass row after most recent write at {last_write_ts}.")
    elif not tests:
        gaps.append("No test_pass row for this task.")
    if last_fail_ts and (not last_test_ts or last_test_ts < last_fail_ts):
        gaps.append(f"Most recent run failed at {last_fail_ts}; no subsequent test_pass.")
    if manifest.get("adv_required") and not adv_satisfied(ledger, task_id):
        gaps.append("Task requires adversarial tests; no adv_pass row present.")
    for rel in manifest.get("acceptance_files", []):
        if not (PROJECT_DIR / rel).exists():
            gaps.append(f"Acceptance file missing: {rel}")
    if manifest.get("phase_gate_required"):
        phase = manifest.get("phase", "")
        gate_rows = [
            r for r in ledger
            if r.get("event") == "phase_gate_pass" and r.get("phase") == phase
        ]
        if not gate_rows:
            gaps.append(f"Phase gate {phase} not yet passed.")
    return gaps


def recent_start_for_path(ledger: list[dict], window_seconds: int = 600) -> dict | None:
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for row in reversed(ledger):
        if row.get("event") != "start":
            continue
        ts = _ts_to_epoch(row.get("ts", ""))
        if ts is not None and now - ts < window_seconds:
            return row
    return None


def scope_exception_paths(ledger: list[dict]) -> list[str]:
    """Collect RAW scope_exception paths from the last 150 ledger rows.

    Returns every path appearing in a ``scope_exception`` row within the
    window, with no revocation applied. The write-gate in
    ``scripts/impl_pre_write.py`` layers ``scope_revoke`` cancellation on
    top via ``_effective_scope_exception_paths``; callers that need the
    gate-effective view should use that function instead. Non-gate
    consumers (reporting, audit, diagnostics) typically want these raw
    paths.

    Malformed rows (missing ``paths`` key, ``paths`` is None, or ``paths``
    is not a list) are logged to stderr and skipped rather than silently
    authorising nothing. Well-formed rows are appended unchanged.

    Historical context: six early rows (2026-04-17 and 2026-04-20) were
    written with ``paths`` absent/None and then counted as "row present"
    in audit logs while authorising no paths. This defensive read surfaces
    the drift loudly instead of silently. The write-side gate in
    ``scripts/impl_pre_write.py`` prevents new rows of this shape.

    Window history: the trailing window started at 50 rows; it was widened
    to 150 on 2026-04-22 because ``scripts/impl_post_write.py`` auto-emits
    write + (often) test_pass rows per Edit, which compressed manually
    authored scope_exception rows out of the window mid-plan.
    """
    out: list[str] = []
    for row in ledger[-150:]:
        if row.get("event") != "scope_exception":
            continue
        paths = row.get("paths")
        if paths is None:
            sys.stderr.write(
                "WARN: scope_exception row without paths: "
                f"ts={row.get('ts')} task_id={row.get('task_id')}\n"
            )
            continue
        if not isinstance(paths, list):
            sys.stderr.write(
                "WARN: scope_exception row with non-list paths: "
                f"ts={row.get('ts')} type={type(paths).__name__}\n"
            )
            continue
        out.extend(paths)
    return out

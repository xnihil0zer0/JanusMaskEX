"""End-to-end shadow-mode equivalence harness (Phase 3 / N4 method).

Drives the same fixture corpus through BOTH validation paths in turn:

  * legacy: ``harness.mcp_server.JanusMaskServer.cmd_submit_code`` →
    ``harness.hooks.rpc.submit_code.persist`` (and the deny path returns
    ``rejected_payload`` instead of writing).
  * hooks:  ``harness.hooks.claude.post_tool._persist_submission`` driven
    via the same ``rpc.submit_code`` primitives, with the persist-time
    AST gate from HOOK-22 active.

The two paths are run against isolated ``state_dir`` fixtures so their
outputs (``state/sessions/`` files + ``*.ledger.jsonl`` rows) can be
diffed by ``harness.hooks_equivalence.compare`` — exactly what the L2
shadow comparator does in production. Any divergence at the per-task
level here is a real ``shadow_divergence_two_consecutive`` rollback
trigger waiting to happen (brief_hooks_operator_followup.md §4).

The corpus covers:

  A. clean code               (both persist; outcome=allow)
  B. AST error code           (both skip; outcome=deny)
  C. allow_nondet + uuid      (constraints.deterministic=False; both persist)
  D. malformed task.json      (both must not crash; persist outcome diverges
                               only if a path mis-derives allow_nondet)
  E. empty submission         (rpc.submit_code rejects empty 'code' as schema
                               error; both paths surface the same SchemaError)
  F. >1MB submission          (oversize payload — both paths must complete; we
                               assert no size-based asymmetry)
  G. concurrent same task_id  (two persist calls back-to-back — both paths
                               must produce the same set of canonical files)
  H. sessions dir absent      (both paths auto-create state/sessions; no
                               crash on cold-start project state)
  I. forbidden filesystem     (subprocess RPC call ensures the runner's I/O
                               surface matches the in-process call)
  J. planner-style task       (meta_task_type=planner_tooling — bypass logic
                               lives at orchestrator layer, not persist; both
                               paths must persist identically)

The test is META allow-listed; it adds *no* mutation to harness/config.yaml
and never spawns claude/gemini CLIs. The one true subprocess invocation
(scenario I) drives ``python3 -m harness.hooks.claude.post_tool`` against a
synthetic stdin envelope — the same code path the worker runs in production.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from harness import hooks_equivalence as he
from harness.hooks import _ledger
from harness.hooks.rpc import submit_code as rpc_submit_code


REPO = pathlib.Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# fixture corpus — 20+ synthetic submissions parametrised by scenario name
# ---------------------------------------------------------------------------


CLEAN_CODE = "def add(a, b):\n    return a + b\n"
CLEAN_CODE_2 = "def mul(a, b):\n    return a * b\n"
CLEAN_CODE_3 = "def neg(x):\n    return -x\n"
UUID_CODE = "import uuid\n\ndef make_id():\n    return uuid.uuid4().hex\n"
TIME_CODE = "import time\n\ndef now():\n    return time.time()\n"
SYNTAX_BROKEN = "def broken(:\n    pass\n"
WARNINGS_ONLY = (
    "import subprocess\n\n"
    "def run():\n"
    "    subprocess.run(['ls'])\n"
)
LARGE_CODE = "def big():\n    return [\n" + "        0,\n" * 50_000 + "    ]\n"


@dataclass
class Scenario:
    """Single fixture submission + the task fields its inbox carries."""

    name: str
    code: str
    task: dict
    expected_outcome: str  # "allow" or "deny"
    notes: str = ""
    explanation: str = "e2e fixture submission"
    # Test plumbing
    skip_subprocess: bool = False
    extra_assert: Any = field(default=None)


def _task(
    task_id: str = "T-e2e",
    *,
    deterministic: bool | None = True,
    synthesis_target_type: str = "function",
    meta_task_type: str | None = None,
    extras: dict | None = None,
) -> dict:
    t: dict[str, Any] = {
        "task_id": task_id,
        "synthesis_target_type": synthesis_target_type,
    }
    constraints: dict[str, Any] = {}
    if deterministic is not None:
        constraints["deterministic"] = deterministic
    if constraints:
        t["constraints"] = constraints
    if meta_task_type is not None:
        t["meta_task_type"] = meta_task_type
    if extras:
        t.update(extras)
    return t


CORPUS: list[Scenario] = [
    # -- A. happy path --------------------------------------------------------
    Scenario("A1_clean_simple", CLEAN_CODE, _task("A1"), "allow"),
    Scenario("A2_clean_mul", CLEAN_CODE_2, _task("A2"), "allow"),
    Scenario("A3_clean_neg", CLEAN_CODE_3, _task("A3"), "allow"),
    # -- B. AST errors --------------------------------------------------------
    Scenario("B1_syntax_error", SYNTAX_BROKEN, _task("B1"), "deny",
             notes="parser SyntaxError → rule=syntax"),
    Scenario("B2_uuid_under_default", UUID_CODE, _task("B2"), "deny",
             notes="uuid import + deterministic task → nondet error"),
    Scenario("B3_time_under_default", TIME_CODE, _task("B3"), "deny",
             notes="time.time() + deterministic task → nondet error"),
    # -- C. allow_nondet override --------------------------------------------
    Scenario("C1_uuid_with_nondet", UUID_CODE,
             _task("C1", deterministic=False), "allow",
             notes="constraints.deterministic=False; uuid is permitted"),
    Scenario("C2_time_with_nondet", TIME_CODE,
             _task("C2", deterministic=False), "allow"),
    # -- D. malformed task.json ----------------------------------------------
    # The hooks path reads task.json from the inbox; mcp reads via env-shadowed
    # state/tasks. We test the hooks side here (mcp parity comes from the
    # config-loader rather than payload shape). A malformed inbox should
    # default-fall-through to allow_nondet=False which means the AST gate
    # behaves as if the code were deterministic — clean code persists, uuid
    # rejects.
    Scenario("D1_malformed_task_clean", CLEAN_CODE, _task("D1"), "allow",
             notes="malformed task.json must not crash; clean code persists"),
    Scenario("D2_malformed_task_uuid", UUID_CODE, _task("D2"), "deny",
             notes="malformed task.json defaults to deterministic → uuid denied"),
    # -- E. empty submission --------------------------------------------------
    Scenario("E1_empty_code", "", _task("E1"), "deny",
             notes="schema error: code must be non-empty string"),
    # -- F. oversize payload --------------------------------------------------
    Scenario("F1_large_clean", LARGE_CODE, _task("F1"), "allow",
             notes=">1MB clean code — both paths persist without size cap"),
    # -- G. concurrent same task_id (handled out-of-loop) --------------------
    Scenario("G1_concurrent_a", CLEAN_CODE, _task("G-shared"), "allow",
             notes="ordering pair scenario G"),
    Scenario("G2_concurrent_b", CLEAN_CODE_2, _task("G-shared"), "allow",
             notes="ordering pair scenario G"),
    # -- H. sessions dir absent (handled out-of-loop) ------------------------
    Scenario("H1_cold_start_clean", CLEAN_CODE, _task("H1"), "allow",
             notes="state/sessions does not pre-exist — must auto-create"),
    # -- I. subprocess true E2E ---------------------------------------------
    Scenario("I1_subprocess_clean", CLEAN_CODE, _task("I1"), "allow",
             notes="subprocess invocation of post_tool main()"),
    Scenario("I2_subprocess_uuid", UUID_CODE, _task("I2"), "deny",
             notes="subprocess invocation must also reject uuid"),
    # -- J. planner_tooling / meta tasks -------------------------------------
    Scenario("J1_planner_tooling", CLEAN_CODE,
             _task("J1", meta_task_type="planner_tooling"), "allow",
             notes="planner_tooling bypass is fuzzer-side; persist still runs"),
    Scenario("J2_data_model", CLEAN_CODE,
             _task("J2", meta_task_type="data_model"), "allow"),
    Scenario("J3_orchestration", CLEAN_CODE,
             _task("J3", meta_task_type="orchestration"), "allow"),
    # -- K. warnings-only (clean modulo non-blocking warnings) --------------
    Scenario("K1_warnings_only", WARNINGS_ONLY, _task("K1"), "allow",
             notes="subprocess warning is not error severity → persists"),
    # -- L. unicode payload --------------------------------------------------
    Scenario("L1_unicode_explanation",
             "def f():\n    return 'ⱷ中文'\n",
             _task("L1"), "allow",
             explanation="ⱷ unicode 中文 \U0001f600",
             notes="unicode round-trips through JSON encoding"),
]


assert len(CORPUS) >= 20, f"corpus too small: {len(CORPUS)}"


# ---------------------------------------------------------------------------
# path drivers
# ---------------------------------------------------------------------------


def _seed_state(tmp_path: pathlib.Path, *, with_sessions_dir: bool = True) -> pathlib.Path:
    """Build a state_dir skeleton; mirrors what the orchestrator stages."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    if with_sessions_dir:
        (state / "sessions").mkdir(exist_ok=True)
    (state / "tasks").mkdir(exist_ok=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis", "task_id": "T-e2e"})
    )
    return state


def _write_current_task(state: pathlib.Path, task: dict) -> None:
    # Post-RP7 (26558a5): MCP server fallback resolves to current_task_<task_id>.json
    # via task_paths.current_task_spec_path when the env var path's glob misses.
    # Interpolate the task_id so cmd_get_task/cmd_submit_code finds the spec.
    task_id = task.get("task_id", "default")
    (state / "tasks" / f"current_task_{task_id}.json").write_text(
        json.dumps(task), encoding="utf-8"
    )


def _seed_workdir(state: pathlib.Path, session_id: str, task: dict,
                  *, agent: str = "claude") -> pathlib.Path:
    workdir = state / "workdirs" / agent / session_id
    (workdir / "inbox").mkdir(parents=True, exist_ok=True)
    (workdir / "outbox").mkdir(parents=True, exist_ok=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps(task), encoding="utf-8"
    )
    return workdir


def _drive_legacy(scenario: Scenario, state: pathlib.Path, *,
                  session_id: str, agent: str = "claude",
                  monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run the MCP-server validation+persist path. Returns ledger-row-shaped
    dict so it can be fed straight into ``hooks_equivalence.compare``.

    We DO NOT spawn the JSON-RPC server; we drive ``cmd_submit_code`` in-
    process, which is byte-identical to what the dispatcher invokes.
    """
    # Stub ConsoleStreamer to avoid coloured stderr noise in test logs.
    from harness import mcp_server

    class _SilentConsole:
        def __init__(self, *a, **kw):
            pass

        def __getattr__(self, name):
            return lambda *a, **kw: None

    monkeypatch.setattr(mcp_server, "ConsoleStreamer", _SilentConsole)

    monkeypatch.setenv("JANUSMASK_TASK_ID", scenario.task["task_id"])

    # Write the task.json in the legacy location.
    _write_current_task(state, scenario.task)

    server = mcp_server.JanusMaskServer(agent, state)
    # Force the test session_id so legacy and hooks rows align on key.
    server.session_id = session_id
    server.task_read = True  # bypass the inbox gate (we're not testing it)

    args = {
        "session_id": session_id,
        "agent_identity": agent,
        "round_number": 1,
        "timestamp": "2026-04-19T00:00:00+00:00",
        "code": scenario.code,
        "explanation": scenario.explanation,
    }
    response = server.cmd_submit_code(args)
    outcome = "deny" if response.get("status") == "rejected" or "error" in response else "allow"

    return {
        "verb": "submit_code",
        "outcome": outcome,
        "tool": "submit_code",
        "task_id": scenario.task["task_id"],
        "response": response,
    }


def _drive_hooks(scenario: Scenario, state: pathlib.Path, *,
                 session_id: str, agent: str = "claude",
                 monkeypatch: pytest.MonkeyPatch,
                 corrupt_task_json: bool = False) -> dict:
    """Run the hooks _persist_submission path. Returns ledger-row-shaped
    dict so it can be diffed against the legacy result."""
    from harness.hooks import _paths
    from harness.hooks.claude import _env as claude_env
    from harness.hooks.claude import post_tool as claude_post

    monkeypatch.setattr(_paths, "state_dir", lambda: state)

    workdir = _seed_workdir(state, session_id, scenario.task, agent=agent)
    inbox = workdir / "inbox"

    if corrupt_task_json:
        # Write garbage so json.loads inside _load_task fails.
        (inbox / "task.json").write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

    # Capture the outcome by snapshotting the ledger before/after.
    ledger = state / "sessions" / f"{agent}_{session_id}.ledger.jsonl"

    try:
        claude_post._persist_submission(
            session_id=session_id,
            agent=agent,
            round_number=1,
            phase="synthesis",
            content=scenario.code,
            explanation=scenario.explanation,
            events=[],
        )
    except rpc_submit_code.SchemaError:
        # Empty-code scenario — the hooks path raises SchemaError to the
        # caller (which would be the dispatcher); model that as "deny".
        return {
            "verb": "submit_code",
            "outcome": "deny",
            "tool": "submit_code",
            "task_id": scenario.task["task_id"],
            "response": {"error": "schema_error_empty_code"},
        }

    # Read back any ledger row to determine outcome.
    if ledger.exists():
        rows = [
            json.loads(line)
            for line in ledger.read_text().splitlines()
            if line.strip()
        ]
        if rows:
            last = rows[-1]
            return {
                "verb": last.get("verb", "submit_code"),
                "outcome": last.get("outcome", "allow"),
                "tool": last.get("tool", "Write"),
                "task_id": scenario.task["task_id"],
                "response": last.get("detail") or {},
            }

    # No ledger row written → the hooks path was an early-return. The
    # only known early-return path is "schema error"; map to "deny" so
    # the comparator can flag any silent-skip divergence.
    sessions_files = list((state / "sessions").glob(
        f"*round1_{scenario.task['task_id']}*_submission.json"))
    if sessions_files:
        return {
            "verb": "submit_code",
            "outcome": "allow",
            "tool": "Write",
            "task_id": scenario.task["task_id"],
            "response": {"persisted": True},
        }
    return {
        "verb": "submit_code",
        "outcome": "deny",
        "tool": "submit_code",
        "task_id": scenario.task["task_id"],
        "response": {"silent_skip": True},
    }


# ---------------------------------------------------------------------------
# parametrised differential tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", CORPUS, ids=[s.name for s in CORPUS])
def test_legacy_and_hooks_outcomes_match(
    scenario: Scenario, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Differential equivalence: the same submission must produce the same
    allow/deny outcome on both paths.

    Divergence here would, in production, fire on the SECOND consecutive
    diff and trigger ``shadow_divergence_two_consecutive`` rollback
    (brief_hooks_operator_followup.md §4).
    """
    legacy_state = _seed_state(tmp_path / "legacy")
    hooks_state = _seed_state(tmp_path / "hooks")

    # Two independent monkeypatch contexts would be ideal; pytest's single
    # monkeypatch is fine here because each driver re-stubs the symbols it
    # owns and we only consult the *result* of each driver after it returns.
    legacy = _drive_legacy(
        scenario, legacy_state, session_id="leg-sess",
        monkeypatch=monkeypatch,
    )
    hooks = _drive_hooks(
        scenario, hooks_state, session_id="hk-sess",
        monkeypatch=monkeypatch,
    )

    assert legacy["outcome"] == hooks["outcome"], (
        f"OUTCOME DIVERGENCE in {scenario.name!r}: "
        f"legacy={legacy['outcome']} hooks={hooks['outcome']}\n"
        f"  legacy.response={legacy['response']!r}\n"
        f"  hooks.response={hooks['response']!r}\n"
        f"  notes={scenario.notes!r}\n"
        "PRODUCTION IMPACT: this would fire shadow_divergence_two_consecutive "
        "on the second similar event and trigger rollback."
    )
    assert legacy["outcome"] == scenario.expected_outcome, (
        f"corpus expectation drift for {scenario.name!r}: "
        f"expected={scenario.expected_outcome} got={legacy['outcome']}"
    )


# ---------------------------------------------------------------------------
# system-level comparator: feed both ledgers into hooks_equivalence.compare
# ---------------------------------------------------------------------------


def _ledger_row_for_compare(driver_result: dict, *, args_hash: str) -> dict:
    """Project a driver result into the per-row schema the comparator
    consumes.

    Real production rows always carry ``tool="Write"`` (the CLI tool name),
    not the verb name — see state/sessions/*.ledger.jsonl. We force the
    canonical ``Write`` tool here so ``mcp_diff_key`` produces a key
    aligned with the shadow row's ``tool_name="Write"``. If the test
    instead emitted ``tool="submit_code"`` the keys would never match
    (which is itself a comparator behaviour worth pinning — see
    ``test_tool_name_drift_surfaces_as_divergence`` below)."""
    return {
        "tool": "Write",
        "verb": driver_result["verb"],
        "outcome": driver_result["outcome"],
        "args_hash": args_hash,
        "digest": args_hash,
        "task_id": driver_result["task_id"],
    }


def _shadow_row_for_compare(driver_result: dict, *, args_hash: str) -> dict:
    """Shadow rows use the new schema (tool_name, args_hash, policy_decision)."""
    # The shadow comparator collapses 'rate_limited' / 'invalid' to 'deny';
    # the hooks path only emits allow/deny, so just pass through.
    return {
        "tool_name": driver_result["tool"],
        "args_hash": args_hash,
        "policy_decision": driver_result["outcome"],
        "policy_reason": driver_result["response"].get("reason", ""),
    }


def test_full_corpus_equivalence_report() -> None:
    """Drive the entire corpus through both paths, build an equiv-report,
    assert match_rate == 1.0.

    This is the system-level inversion of ``test_legacy_and_hooks_outcomes_
    match``: instead of one assertion per scenario, we accumulate the full
    20+ submission stream and ask the production comparator whether the two
    feeds are equivalent. A 1.0 match rate is what the production
    diff-gate (``check_diff_gate``) requires for the canary flip to
    proceed.
    """
    legacy_rows: list[dict] = []
    hooks_rows: list[dict] = []
    divergent: list[str] = []

    # The args_hash in production is over tool_input; here we hash the
    # canonical (task_id, code) pair so equivalent submissions on both
    # sides produce the same key.
    for scenario in CORPUS:
        if scenario.skip_subprocess and False:  # placeholder; corpus has no skips
            continue
        ah = he.args_hash({"task_id": scenario.task["task_id"], "code": scenario.code})

        with pytest.MonkeyPatch.context() as mp:
            legacy_state = _seed_state(pathlib.Path(
                str(pathlib.Path(os.getenv("PYTEST_CURRENT_TEST", ".")).parent)
                + f"_legacy_{uuid.uuid4().hex[:8]}"
            ).resolve()) if False else None
            # Use a tmp dir per iteration to keep paths clean.
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                root = pathlib.Path(td)
                legacy_state = _seed_state(root / "leg")
                hooks_state = _seed_state(root / "hk")
                legacy = _drive_legacy(
                    scenario, legacy_state, session_id="L",
                    monkeypatch=mp,
                )
                hooks = _drive_hooks(
                    scenario, hooks_state, session_id="H",
                    monkeypatch=mp,
                )
        legacy_rows.append(_ledger_row_for_compare(legacy, args_hash=ah))
        hooks_rows.append(_shadow_row_for_compare(hooks, args_hash=ah))
        if legacy["outcome"] != hooks["outcome"]:
            divergent.append(
                f"{scenario.name}: legacy={legacy['outcome']} "
                f"hooks={hooks['outcome']}"
            )

    report = he.compare(
        shadow_rows=hooks_rows,
        mcp_rows=legacy_rows,
        session_id="e2e-corpus",
    )

    assert not divergent, (
        "Per-scenario outcome divergences:\n  " + "\n  ".join(divergent)
        + "\nThis would trigger shadow_divergence_two_consecutive in prod."
    )
    assert report.match_rate == 1.0, (
        f"comparator match_rate={report.match_rate} "
        f"divergences={report.divergences}\n"
        "PRODUCTION IMPACT: diff-gate would block the canary flip; "
        "shadow_divergence_two_consecutive fires after a second event."
    )
    assert report.shadow_count == report.mcp_count == len(CORPUS)


# ---------------------------------------------------------------------------
# scenario D: malformed task.json — both paths must remain stable
# ---------------------------------------------------------------------------


def test_malformed_task_json_does_not_crash_hooks_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When inbox/task.json is corrupt, ``_load_task`` returns {} and the
    persist gate behaves as if ``allow_nondet=False`` (deterministic
    default). Document that this is the CURRENT behaviour and that it is
    consistent with mcp_server's exception handler (``except (FileNotFound
    Error, json.JSONDecodeError): pass``)."""
    state = _seed_state(tmp_path)
    scenario = Scenario(
        "D-corrupt-clean", CLEAN_CODE, _task("D-corrupt"), "allow",
    )
    result = _drive_hooks(
        scenario, state, session_id="corr",
        monkeypatch=monkeypatch, corrupt_task_json=True,
    )
    assert result["outcome"] == "allow", (
        "Corrupt task.json must default to allow_nondet=False; "
        "clean code is therefore still persisted."
    )

    # And uuid code under corrupt task → deny (same default).
    state2 = _seed_state(tmp_path / "uuid")
    sc2 = Scenario("D-corrupt-uuid", UUID_CODE, _task("D-corrupt-uuid"), "deny")
    r2 = _drive_hooks(
        sc2, state2, session_id="corr2",
        monkeypatch=monkeypatch, corrupt_task_json=True,
    )
    assert r2["outcome"] == "deny"


# ---------------------------------------------------------------------------
# scenario H: cold-start state dir (sessions/ does not exist)
# ---------------------------------------------------------------------------


def test_cold_start_creates_sessions_dir_consistently(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``state/sessions/`` is auto-created by both paths on first persist.
    Verifies neither path requires orchestrator priming to land a clean
    submission."""
    # Two distinct cold roots, neither containing state/sessions.
    legacy_root = tmp_path / "leg"
    hooks_root = tmp_path / "hk"
    legacy_state = _seed_state(legacy_root, with_sessions_dir=False)
    hooks_state = _seed_state(hooks_root, with_sessions_dir=False)
    assert not (legacy_state / "sessions").exists()
    assert not (hooks_state / "sessions").exists()

    sc = Scenario("H-cold", CLEAN_CODE, _task("H-cold"), "allow")
    _drive_legacy(sc, legacy_state, session_id="L-cold", monkeypatch=monkeypatch)
    _drive_hooks(sc, hooks_state, session_id="H-cold", monkeypatch=monkeypatch)

    legacy_files = list((legacy_state / "sessions").glob("*_submission.json"))
    hooks_files = list((hooks_state / "sessions").glob("*_submission.json"))
    assert len(legacy_files) == 1
    assert len(hooks_files) == 1


# ---------------------------------------------------------------------------
# scenario G: concurrent submissions for same task_id
# ---------------------------------------------------------------------------


def test_concurrent_same_task_id_persists_both_submissions(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Back-to-back persists on the same (agent, round, task_id) — the
    submission filename does not include a uniquifier, so the SECOND write
    overwrites the first on both paths. Asserts both paths have THE SAME
    overwrite semantics (no de-dup divergence)."""
    legacy_state = _seed_state(tmp_path / "leg")
    hooks_state = _seed_state(tmp_path / "hk")

    sc_a = Scenario("G-a", CLEAN_CODE, _task("G-shared"), "allow")
    sc_b = Scenario("G-b", CLEAN_CODE_2, _task("G-shared"), "allow")

    # Hooks side: same session, two writes
    _drive_hooks(sc_a, hooks_state, session_id="cc", monkeypatch=monkeypatch)
    _drive_hooks(sc_b, hooks_state, session_id="cc", monkeypatch=monkeypatch)

    # Legacy side: same agent/round/task → same filename per session_namer
    _drive_legacy(sc_a, legacy_state, session_id="cc", monkeypatch=monkeypatch)
    _drive_legacy(sc_b, legacy_state, session_id="cc", monkeypatch=monkeypatch)

    legacy_files = sorted((legacy_state / "sessions").glob(
        "*_round1_G-shared*_submission.json"))
    hooks_files = sorted((hooks_state / "sessions").glob(
        "*_round1_G-shared*_submission.json"))
    # Both paths must agree on number of files (1 = overwritten, 2 = uniquified)
    assert len(legacy_files) == len(hooks_files), (
        f"de-dup divergence: legacy={len(legacy_files)} hooks={len(hooks_files)}"
    )
    # And the surviving content must be the LAST submission's bytes on both.
    legacy_payload = json.loads(legacy_files[-1].read_text())
    hooks_payload = json.loads(hooks_files[-1].read_text())
    assert legacy_payload["code"] == hooks_payload["code"] == CLEAN_CODE_2


# ---------------------------------------------------------------------------
# scenario I: subprocess invocation — true integration via post_tool main()
# ---------------------------------------------------------------------------


def _run_post_tool_subprocess(
    *, state: pathlib.Path, session_id: str, file_path: str,
    explanation: str, agent: str = "claude",
) -> subprocess.CompletedProcess:
    """Spawn ``python3 -m harness.hooks.claude.post_tool`` and feed the
    canonical PostToolUse stdin envelope. This is exactly what Claude Code
    runs in production."""
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": pathlib.Path(file_path).read_text(),
            "explanation": explanation,
        },
        "tool_response": {"success": True, "filePath": file_path},
    }
    env = os.environ.copy()
    env["JANUSMASK_STATE_DIR"] = str(state)
    env["JANUSMASK_PROJECT_DIR"] = str(state.parent)
    env["JANUSMASK_AGENT"] = agent
    env["JANUSMASK_MODE"] = "synthesis"
    env["JANUSMASK_ROUND"] = "1"
    env["JANUSMASK_WORK_DIR"] = str(
        state / "workdirs" / agent / session_id
    )
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "harness.hooks.claude.post_tool"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO),
    )


@pytest.mark.parametrize(
    "scenario_name,code,expected_outcome",
    [
        ("I1_subprocess_clean", CLEAN_CODE, "allow"),
        ("I2_subprocess_uuid", UUID_CODE, "deny"),
    ],
)
def test_subprocess_post_tool_matches_in_process_persist(
    scenario_name: str, code: str, expected_outcome: str,
    tmp_path: pathlib.Path,
) -> None:
    """End-to-end subprocess: ``python3 -m harness.hooks.claude.post_tool``
    must produce the same persistence outcome as the in-process
    ``_persist_submission`` driver. This is the only test in the file
    that exercises the actual hook entry point — everything else drives
    the function-level Python API."""
    state = _seed_state(tmp_path)
    sid = "sp-sess"
    workdir = _seed_workdir(state, sid, _task(scenario_name.split("_")[0]),
                            agent="claude")
    outbox = workdir / "outbox"
    submission_file = outbox / "submission.py"
    submission_file.write_text(code, encoding="utf-8")

    proc = _run_post_tool_subprocess(
        state=state, session_id=sid, file_path=str(submission_file),
        explanation="subprocess-driven e2e",
    )
    # Hook must always exit 0 (PostToolUse is allow-only).
    assert proc.returncode == 0, (
        f"subprocess crashed (rc={proc.returncode}):\n"
        f"  stdout={proc.stdout!r}\n  stderr={proc.stderr!r}"
    )
    response = json.loads(proc.stdout) if proc.stdout.strip() else {}
    assert response.get("decision") == "allow", response

    # Now check the side-effects.
    submission_files = list((state / "sessions").glob("*_submission.json"))
    if expected_outcome == "allow":
        assert len(submission_files) == 1, (
            f"expected persisted submission; got {submission_files}\n"
            f"stderr: {proc.stderr}"
        )
    else:
        assert submission_files == [], (
            f"AST gate must have skipped persist; got {submission_files}\n"
            f"stderr: {proc.stderr}"
        )
    # Ledger row must exist on either outcome (allow row OR deny row).
    ledger = state / "sessions" / f"claude_{sid}.ledger.jsonl"
    assert ledger.exists(), f"ledger row required; stderr={proc.stderr}"
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    outcomes = [r.get("outcome") for r in rows]
    assert expected_outcome in outcomes, (
        f"expected {expected_outcome} in ledger outcomes={outcomes}"
    )


# ---------------------------------------------------------------------------
# snapshot equivalence: per-row ledger shape parity
# ---------------------------------------------------------------------------


def test_ledger_row_shape_uses_keys_compatible_with_comparator(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hooks-emitted ledger row must carry every key the
    ``mcp_diff_key`` projection needs. If a future hooks-side schema drift
    drops one of these keys silently, the comparator falls back to empty
    strings and EVERYTHING matches by accident — masking real divergence.
    """
    state = _seed_state(tmp_path)
    sc = Scenario("shape", CLEAN_CODE, _task("shape"), "allow")
    _drive_hooks(sc, state, session_id="shape", monkeypatch=monkeypatch)
    ledger = state / "sessions" / "claude_shape.ledger.jsonl"
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert rows, "no ledger rows emitted"
    last = rows[-1]
    # Required by mcp_diff_key:
    assert "tool" in last or "tool_name" in last
    assert "outcome" in last or "decision" in last
    # digest is the args_hash analog on the MCP side
    assert "digest" in last
    # Schema-evolution canary: if these keys vanish silently the comparator
    # keys collapse to ('','','') and a broken hooks path looks "equivalent".
    assert last["tool"] == "Write"
    assert last["verb"] == "submit_code"
    assert last["outcome"] == "allow"


# ---------------------------------------------------------------------------
# rollback-trigger sanity: simulate two consecutive divergences and confirm
# the comparator surfaces them as such (no silent merge)
# ---------------------------------------------------------------------------


def test_tool_name_drift_surfaces_as_divergence() -> None:
    """Schema-drift discovery (documented during this test author's pass):

    The MCP-era audit row carries ``tool="Write"`` (the CLI tool name) AND
    a ``verb="submit_code"`` field. The shadow row only carries
    ``tool_name="Write"``. ``mcp_diff_key`` projects on ``tool`` first,
    falling back to ``tool_name``. If a future hooks-side ledger writer
    accidentally drops the ``tool`` field and only emits ``verb``,
    ``mcp_diff_key`` will key on the empty string and the comparator will
    flag a divergence — which is the desired loud failure (we want
    silent schema drift to be VISIBLE, not silently merged).
    """
    shadow = [{"tool_name": "Write", "args_hash": "h", "policy_decision": "allow"}]
    drifted_mcp = [{"verb": "submit_code", "outcome": "allow", "digest": "h"}]
    rep = he.compare(shadow, drifted_mcp, session_id="drift")
    assert rep.match_rate < 1.0, (
        "schema-drift must NOT silently match — comparator collapsed "
        "tool/'' to a fake key match, masking real divergence."
    )


def test_two_consecutive_divergences_are_visible_to_comparator() -> None:
    """The brief defines ``shadow_divergence_two_consecutive`` as the
    rollback trigger. The comparator's job is to make divergences VISIBLE;
    the trigger logic lives elsewhere. This test pins that the comparator
    counts each divergence individually rather than collapsing duplicates.
    """
    shadow = [
        {"tool_name": "Write", "args_hash": "h1", "policy_decision": "allow"},
        {"tool_name": "Write", "args_hash": "h2", "policy_decision": "allow"},
        {"tool_name": "Write", "args_hash": "h3", "policy_decision": "allow"},
    ]
    mcp = [
        {"tool": "Write", "digest": "h1", "outcome": "deny"},   # divergence 1
        {"tool": "Write", "digest": "h2", "outcome": "deny"},   # divergence 2
        {"tool": "Write", "digest": "h3", "outcome": "allow"},  # match
    ]
    rep = he.compare(shadow, mcp, session_id="two-div")
    # 4 divergences (2 shadow-side surplus + 2 mcp-side surplus from the
    # disagreeing rows). The "two consecutive" detection is the operator's
    # job downstream.
    assert len(rep.divergences) >= 2
    assert rep.match_rate < 1.0

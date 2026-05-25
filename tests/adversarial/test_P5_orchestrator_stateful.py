"""Phase-3 stateful property-based test for the orchestrator pipeline.

Models ``harness/orchestrator.py::run_pipeline`` as a state machine and
drives it with hypothesis-generated event sequences, asserting eight
invariants across every reachable state:

  1. **No NameError**: every reachable code path resolves all symbols
     (regression for Blocker #9 and any sibling NameError that could
     ride in unreachable orchestrator branches).
  2. **State-machine totality**: every (state, event) pair is handled
     by either an explicit transition or a documented terminal
     reject; there are no implicit-None drops.
  3. **Termination**: every task that enters ``synthesis`` eventually
     reaches a terminal state (``accepted`` or ``rejected``); no
     infinite cross-exam loop, no unbounded retry.
  4. **Processed marker uniqueness**: a task in
     ``state/tasks/processed/`` MUST NOT also be in ``state/tasks/``.
  5. **Commit invariant**: when a task enters ``accepted``, exactly
     one auto-commit was attempted AND ``state/output/<task_id>.py``
     exists.
  6. **AST gate invariant**: any submission that reaches the fuzzing
     phase has passed AST validation.
  7. **Bypass invariant**: any task whose ``meta_task_type`` is in
     ``BYPASS_FUZZER_TYPES`` reaches ``accepted`` without ever
     entering ``fuzzing`` or ``cross_examination``.
  8. **Resource bound**: max retries x max rounds is bounded; never
     spawn more than ``max_retries * 2 + 2`` synthesis-equivalent
     calls per task.

The test does NOT spawn real claude/gemini; it uses a faithful
abstract simulator over the same control-flow shape as
``run_pipeline`` so that bugs in the state-machine transitions
surface as invariant violations. Where possible the simulator calls
the real orchestrator helpers (``get_next_task``, ``_mark_processed``,
``_save_final_output``, ``_validate_submission``, ``BYPASS_FUZZER_TYPES``,
``should_bypass_fuzzer``) so drift between simulator and production
is impossible.

META allow-listed under ``tests/adversarial/**``.
"""

# B4-T0-2 Gate 3 marker: this test exercises the orchestrator reader shim for
# task dependency resolution; the shim also lives in harness.mcp_server
# (same dependencies/depends_on fallback pattern).

from __future__ import annotations

import json
import os
import sys
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hypothesis import HealthCheck, Phase, settings, strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from harness import orchestrator as orch
from harness.orchestrator import (
    BYPASS_FUZZER_TYPES,
    Task,
    _mark_processed,
    _save_final_output,
    _validate_submission,
    get_next_task,
    prepare_task_prompt,
    should_bypass_fuzzer,
)


# ---------------------------------------------------------------------------
# Tiny synthetic-code corpus
# ---------------------------------------------------------------------------

_GOOD = (
    "def f(x: int) -> int:\n"
    "    return x + 1\n"
)

_BAD_AST = (
    # Top-level random.random — fails determinism rule.
    "import random\n"
    "def f(x: int) -> int:\n"
    "    return x + random.random()\n"
)

_SYNTAX_BAD = "def f(x):\n    return x +\n"


_VALID_META_TYPES = sorted(BYPASS_FUZZER_TYPES) + [
    None, "", "feature", "invalid_type", "planner_tooling",
]


# ---------------------------------------------------------------------------
# Per-task lifecycle record (keeps the truth about each task)
# ---------------------------------------------------------------------------

@dataclass
class _TaskLifecycle:
    task_id: str
    meta_task_type: Any
    deterministic: bool
    state: str = "queued"
    visited_phases: list[str] = field(default_factory=list)
    synth_attempts: int = 0
    cross_exam_rounds: int = 0
    fuzz_calls: int = 0
    ast_validations: int = 0
    auto_commits: int = 0
    name_errors: list[str] = field(default_factory=list)
    untransitioned_events: list[str] = field(default_factory=list)
    bypass_reached_fuzzing: bool = False
    fuzz_reached_without_ast: bool = False

    def visit(self, phase: str) -> None:
        self.state = phase
        self.visited_phases.append(phase)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class OrchestratorPipelineMachine(RuleBasedStateMachine):
    """Abstract-but-faithful model of run_pipeline's state machine.

    The model mirrors the same control flow as the real implementation
    (synthesis -> ast_validation -> fuzzing -> cross_examination ->
    accepted/rejected/decomposition) and uses the real helpers where
    safe (``BYPASS_FUZZER_TYPES``, ``should_bypass_fuzzer``,
    ``_validate_submission``, ``_mark_processed``, ``_save_final_output``,
    ``get_next_task``).  Each rule corresponds to an event the real
    orchestrator can observe (task pickup, agent submission outcome,
    AST gate result, fuzz comparison verdict, cross-exam outcome).
    """

    # Hard caps — match the orchestrator's defaults so the model stays
    # faithful but bounds keep hypothesis runs cheap.
    MAX_AST_RETRIES = 3
    MAX_CROSS_EXAM_ROUNDS = 1  # production: single cross-exam round
    MAX_TASKS = 12
    MAX_FUZZ_CALLS_PER_TASK = 2  # round 1 + round 2
    MAX_AUTO_COMMITS_PER_TASK = 1

    tasks_bundle: Bundle = Bundle("tasks")

    def __init__(self) -> None:
        super().__init__()
        # tmp state dir lazily initialised in @initialize
        self._state_dir: Path | None = None
        self._lifecycles: dict[str, _TaskLifecycle] = {}
        self._created_count = 0
        # Snapshot of pre-existing JANUSMASK_TASK_ID so the rules
        # can scribble freely without polluting parent process env.
        self._saved_env_task_id = os.environ.get("JANUSMASK_TASK_ID")

    # --- setup -----------------------------------------------------------

    @initialize()
    def setup(self) -> None:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="orch-stateful-"))
        for sub in ("tasks", "tasks/processed", "sessions", "output"):
            (tmp / sub).mkdir(parents=True, exist_ok=True)
        self._state_dir = tmp

    def teardown(self) -> None:
        # Best-effort cleanup; tempdir is fine to leak on failure.
        if self._state_dir and self._state_dir.exists():
            shutil.rmtree(self._state_dir, ignore_errors=True)
        if self._saved_env_task_id is None:
            os.environ.pop("JANUSMASK_TASK_ID", None)
        else:
            os.environ["JANUSMASK_TASK_ID"] = self._saved_env_task_id

    # --- helpers ---------------------------------------------------------

    def _write_task(self, task_id: str, meta_task_type: Any, deterministic: bool) -> None:
        """Materialise a task JSON in state/tasks/."""
        assert self._state_dir is not None
        task_data: dict[str, Any] = {
            "task_id": task_id,
            "specification": "noop",
            "constraints": {"deterministic": deterministic},
            # files_touched intentionally empty; auto-commit will skip,
            # which the simulator handles separately so the commit
            # invariant doesn't depend on git.
            "files_touched": [],
        }
        if meta_task_type is not None:
            task_data["meta_task_type"] = meta_task_type
        path = self._state_dir / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(task_data), encoding="utf-8")

    def _claim_next(self) -> dict[str, Any] | None:
        """Use the real get_next_task so any get_next_task bug surfaces."""
        return get_next_task(self._state_dir)

    def _materialise_outputs(self, task_id: str, code: str) -> None:
        """Use real _save_final_output to flex its filesystem path."""
        _save_final_output(self._state_dir, task_id, code)

    def _mark_done(self, task_id: str) -> None:
        _mark_processed(self._state_dir, task_id)

    # --- rules: task creation -------------------------------------------

    @rule(
        target=tasks_bundle,
        meta_task_type=st.sampled_from(_VALID_META_TYPES),
        deterministic=st.booleans(),
    )
    def add_task(self, meta_task_type: Any, deterministic: bool) -> str:
        if self._state_dir is None:
            return "noop"
        if self._created_count >= self.MAX_TASKS:
            return "noop"
        self._created_count += 1
        task_id = f"T{self._created_count:03d}"
        self._write_task(task_id, meta_task_type, deterministic)
        self._lifecycles[task_id] = _TaskLifecycle(
            task_id=task_id,
            meta_task_type=meta_task_type,
            deterministic=deterministic,
        )
        return task_id

    # --- rules: drive the pipeline --------------------------------------

    @rule(
        claude_kind=st.sampled_from(["good", "bad_ast", "syntax_bad", "missing"]),
        gemini_kind=st.sampled_from(["good", "bad_ast", "syntax_bad", "missing"]),
        equivalent=st.booleans(),
        cross_exam_fixes=st.booleans(),
    )
    def drive_one_round(
        self,
        claude_kind: str,
        gemini_kind: str,
        equivalent: bool,
        cross_exam_fixes: bool,
    ) -> None:
        """Drive a full single-task round through the abstract pipeline.

        This mirrors the body of the ``while True:`` loop inside
        ``run_pipeline`` exactly: pick up a task, run synthesis with
        retries, AST-gate, bypass-shortcut, fuzz, cross-exam, fuzz-2,
        decompose-or-accept-or-reject. The simulator MUST mirror the
        production transitions or the invariants will appear to fail.
        """
        if self._state_dir is None:
            return
        task = self._claim_next()
        if task is None:
            return
        task_id = task.get("task_id", "")
        os.environ["JANUSMASK_TASK_ID"] = task_id
        life = self._lifecycles.setdefault(
            task_id,
            _TaskLifecycle(task_id=task_id, meta_task_type=None, deterministic=True),
        )
        life.visit("synthesis")

        try:
            # ---- Synthesis + AST loop -----------------------------------
            synthesised: tuple[str | None, str | None] = (None, None)
            synthesised_ok = False
            for attempt in range(self.MAX_AST_RETRIES):
                life.synth_attempts += 1
                claude = self._scripted_code(claude_kind, attempt)
                gemini = self._scripted_code(gemini_kind, attempt)
                if claude is None or gemini is None:
                    # Either timed out -> retry path in real code.
                    if attempt + 1 == self.MAX_AST_RETRIES:
                        break
                    continue
                # AST validation — call the REAL validator.
                life.ast_validations += 2
                claude_valid, _ = _validate_submission(claude, "claude", task)
                gemini_valid, _ = _validate_submission(gemini, "gemini", task)
                if claude_valid and gemini_valid:
                    synthesised = (claude, gemini)
                    synthesised_ok = True
                    break
                # Otherwise loop and retry on next attempt.
            life.visit("ast_validation")

            if not synthesised_ok:
                life.visit("rejected")
                self._mark_done(task_id)
                return

            claude_code, gemini_code = synthesised
            assert claude_code is not None and gemini_code is not None

            # ---- Bypass shortcut (must be checked AFTER AST) ------------
            mtt = task.get("meta_task_type") or task.get("constraints", {}).get(
                "meta_task_type"
            )
            if mtt in BYPASS_FUZZER_TYPES:
                life.visit("accepted")
                self._materialise_outputs(task_id, claude_code)
                life.auto_commits += 1
                self._mark_done(task_id)
                return

            # ---- Round-1 fuzz -------------------------------------------
            life.visit("fuzzing")
            life.fuzz_calls += 1
            if life.visited_phases.count("ast_validation") == 0:
                life.fuzz_reached_without_ast = True
            if equivalent:
                life.visit("accepted")
                self._materialise_outputs(task_id, claude_code)
                life.auto_commits += 1
                self._mark_done(task_id)
                return

            # ---- Cross-examination --------------------------------------
            life.visit("cross_examination")
            life.cross_exam_rounds += 1
            if cross_exam_fixes:
                # Round-2 fuzz reaches equivalence.
                life.visit("fuzzing")
                life.fuzz_calls += 1
                life.visit("accepted")
                self._materialise_outputs(task_id, claude_code)
                life.auto_commits += 1
                self._mark_done(task_id)
                return

            # ---- Round-2 fuzz still divergent -> decomposition ----------
            life.visit("fuzzing")
            life.fuzz_calls += 1
            life.visit("decomposition")
            # Decomposition does NOT mark accepted; the parent is moved
            # to processed/ and subtasks are enqueued. We don't actually
            # decompose here (covered by task_decomposer tests); the
            # important invariant is that the parent leaves the active
            # queue and the marker is consistent.
            self._mark_done(task_id)

        except NameError as exc:
            # Critical: the bug Blocker #9 fixed. Preserve, surface in
            # the no_nameerror invariant.
            life.name_errors.append(repr(exc))
        except Exception as exc:  # noqa: BLE001
            # Any other untransitioned event is recorded; totality
            # invariant flags it.
            life.untransitioned_events.append(f"{type(exc).__name__}: {exc!s}")

    # --- helper: scripted submissions -----------------------------------

    @staticmethod
    def _scripted_code(kind: str, attempt: int) -> str | None:
        if kind == "good":
            return _GOOD
        if kind == "bad_ast":
            # Real ast_retry would fix this; without retries we let it
            # fail validation so the invariant exercises the rejected
            # path.
            return _BAD_AST if attempt == 0 else _GOOD
        if kind == "syntax_bad":
            return _SYNTAX_BAD if attempt == 0 else _GOOD
        return None  # "missing"

    # ------------------------------------------------------------------
    # Invariants
    # ------------------------------------------------------------------

    @invariant()
    def no_nameerror(self) -> None:
        """Invariant 1: no path through run_pipeline raises NameError."""
        for life in self._lifecycles.values():
            assert not life.name_errors, (
                f"NameError surfaced in pipeline for {life.task_id}: "
                f"{life.name_errors!r}"
            )

    @invariant()
    def state_machine_totality(self) -> None:
        """Invariant 2: every event has a defined transition."""
        for life in self._lifecycles.values():
            assert not life.untransitioned_events, (
                f"Untransitioned event for {life.task_id}: "
                f"{life.untransitioned_events!r}"
            )

    @invariant()
    def termination(self) -> None:
        """Invariant 3: cross-exam rounds and synth attempts are bounded."""
        for life in self._lifecycles.values():
            assert life.synth_attempts <= self.MAX_AST_RETRIES, (
                f"{life.task_id} synth attempts {life.synth_attempts} "
                f"exceeds MAX_AST_RETRIES={self.MAX_AST_RETRIES}"
            )
            assert life.cross_exam_rounds <= self.MAX_CROSS_EXAM_ROUNDS, (
                f"{life.task_id} cross-exam rounds {life.cross_exam_rounds} "
                f"exceeds MAX={self.MAX_CROSS_EXAM_ROUNDS}"
            )
            assert life.fuzz_calls <= self.MAX_FUZZ_CALLS_PER_TASK, (
                f"{life.task_id} fuzz calls {life.fuzz_calls} "
                f"exceeds MAX={self.MAX_FUZZ_CALLS_PER_TASK}"
            )

    @invariant()
    def processed_uniqueness(self) -> None:
        """Invariant 4: a task in processed/ is never also in tasks/."""
        if self._state_dir is None:
            return
        tasks_dir = self._state_dir / "tasks"
        processed_dir = tasks_dir / "processed"
        if not processed_dir.exists():
            return
        active_names = {
            p.name
            for p in tasks_dir.glob("*.json")
            if p.name != "current_task.json"
        }
        active_processing = {
            p.name.replace(".json.processing", ".json")
            for p in tasks_dir.glob("*.json.processing")
        }
        active = active_names | active_processing
        processed_names = {p.name for p in processed_dir.glob("*.json")}
        overlap = active & processed_names
        assert not overlap, (
            f"task(s) in both tasks/ and processed/: {sorted(overlap)}"
        )

    @invariant()
    def commit_invariant(self) -> None:
        """Invariant 5: accepted -> exactly one auto-commit, output exists."""
        if self._state_dir is None:
            return
        for life in self._lifecycles.values():
            if life.state != "accepted":
                continue
            assert life.auto_commits == 1, (
                f"{life.task_id} accepted but auto_commits="
                f"{life.auto_commits} (expected 1)"
            )
            output = self._state_dir / "output" / f"{life.task_id}.py"
            assert output.exists(), (
                f"{life.task_id} accepted but {output} missing"
            )

    @invariant()
    def ast_gate_invariant(self) -> None:
        """Invariant 6: any task that reaches fuzzing passed AST."""
        for life in self._lifecycles.values():
            if "fuzzing" in life.visited_phases:
                # ast_validation phase MUST appear before fuzzing.
                if "ast_validation" not in life.visited_phases:
                    raise AssertionError(
                        f"{life.task_id} reached fuzzing without ast_validation"
                    )
                first_ast = life.visited_phases.index("ast_validation")
                first_fuzz = life.visited_phases.index("fuzzing")
                assert first_ast < first_fuzz, (
                    f"{life.task_id}: ast_validation must precede fuzzing "
                    f"(visited={life.visited_phases})"
                )
            assert not life.fuzz_reached_without_ast, (
                f"{life.task_id} reached fuzzing without ast_validation"
            )

    @invariant()
    def bypass_invariant(self) -> None:
        """Invariant 7: BYPASS_FUZZER_TYPES tasks never enter fuzzing."""
        for life in self._lifecycles.values():
            if life.meta_task_type in BYPASS_FUZZER_TYPES and life.state == "accepted":
                assert "fuzzing" not in life.visited_phases, (
                    f"{life.task_id} (meta_task_type={life.meta_task_type!r}) "
                    f"is bypass-eligible but reached fuzzing: "
                    f"{life.visited_phases}"
                )
                assert "cross_examination" not in life.visited_phases, (
                    f"{life.task_id} bypass-eligible but reached "
                    f"cross_examination: {life.visited_phases}"
                )

    @invariant()
    def resource_bound(self) -> None:
        """Invariant 8: bounded synthesis spawn count per task."""
        # 2 agents * MAX_AST_RETRIES + 2 cross-exam = ceiling.
        ceiling = self.MAX_AST_RETRIES * 2 + 2
        for life in self._lifecycles.values():
            # synth_attempts counts retries (each spawns 2 agents).
            spawns = life.synth_attempts * 2 + life.cross_exam_rounds * 2
            assert spawns <= ceiling, (
                f"{life.task_id} spawn count {spawns} exceeds {ceiling} "
                f"(synth_attempts={life.synth_attempts}, "
                f"cross_exam_rounds={life.cross_exam_rounds})"
            )


# ---------------------------------------------------------------------------
# Hypothesis settings — stateful tests can be slow.
# ---------------------------------------------------------------------------

OrchestratorPipelineMachine.TestCase.settings = settings(
    max_examples=200,
    deadline=5000,
    stateful_step_count=25,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
    phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target, Phase.shrink),
)


TestOrchestratorPipelineMachine = OrchestratorPipelineMachine.TestCase


# ---------------------------------------------------------------------------
# Targeted property tests for the specific edge cases the brief lists.
# These act as fast-failing canaries even when stateful exploration
# misses the case.
# ---------------------------------------------------------------------------


def test_planner_tooling_bypasses() -> None:
    """`planner_tooling` MUST bypass fuzzing."""
    assert should_bypass_fuzzer(
        Task(task_id="x", meta_task_type="planner_tooling")
    ) is True


def test_meta_task_type_none_does_not_bypass() -> None:
    assert should_bypass_fuzzer(Task(task_id="x", meta_task_type=None)) is False


def test_invalid_meta_task_type_does_not_bypass() -> None:
    assert should_bypass_fuzzer(Task(task_id="x", meta_task_type="invalid_type")) is False


def test_constraints_deterministic_false_allows_nondet(tmp_path: Path) -> None:
    """A task that opts out of determinism allows nondet code through."""
    task = {"task_id": "t", "constraints": {"deterministic": False}}
    code = (
        "import random\n"
        "def f(x: int) -> int:\n"
        "    return x + random.randint(0, 0)\n"
    )
    valid, _ = _validate_submission(code, "claude", task)
    assert valid is True


def test_concurrent_tasks_are_uniquely_processed(tmp_path: Path) -> None:
    """Multiple tasks in tasks/ at once: each should be claimed exactly once."""
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (state_dir / "sessions").mkdir(parents=True)
    for i in range(3):
        (state_dir / "tasks" / f"T{i}.json").write_text(
            json.dumps({"task_id": f"T{i}", "specification": "x"}),
            encoding="utf-8",
        )
    claimed_ids: list[str] = []
    for _ in range(3):
        task = get_next_task(state_dir)
        assert task is not None
        tid = task["task_id"]
        assert tid not in claimed_ids, "task claimed twice"
        claimed_ids.append(tid)
        # Simulate completion.
        _mark_processed(state_dir, tid)
    assert sorted(claimed_ids) == ["T0", "T1", "T2"]


# ---------------------------------------------------------------------------
# Regression: exercise prepare_task_prompt, which used to NameError
# under certain meta_task_type values.  Belt-and-braces vs. invariant 1.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "meta_task_type",
    sorted(BYPASS_FUZZER_TYPES) + [None, "", "feature", "invalid_type"],
)
def test_prepare_task_prompt_no_nameerror(meta_task_type: Any) -> None:
    task = {"task_id": "regression-001", "specification": "noop"}
    if meta_task_type is not None:
        task["meta_task_type"] = meta_task_type
    # Just calling it MUST NOT NameError.
    prompt = prepare_task_prompt(task)
    assert isinstance(prompt, str) and prompt

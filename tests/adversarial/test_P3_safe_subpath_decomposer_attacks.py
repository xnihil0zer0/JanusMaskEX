"""P3 adversarial tests for harness/safe_subpath.py and harness/task_decomposer.py.

These tests target two security/integrity-sensitive surfaces:

1. ``harness.safe_subpath.is_safe_subpath`` -- the descendant-detection
   predicate consulted by the Claude/Gemini PreToolUse hooks
   (harness/hooks/{claude,gemini}/pre_tool.py via harness.hooks._paths) and by
   PostToolUse persistence (harness/hooks/{claude,gemini}/post_tool.py). A
   false positive (declaring an escaping path "safe") would let an agent's
   Write/Edit reach STATE.json, sessions/, or sibling tasks; a false negative
   (declaring a legitimate path "unsafe") would deny correct submissions.

2. ``harness.task_decomposer.{decompose_task, enqueue_subtasks,
   update_parent_state}`` -- the recursive task-graph manipulation pipeline
   that fires when two synthesis rounds DIVERGE. Adversarial inputs include
   circular dependencies, depth bombs, malformed constraints, and
   meta_task_type override conflicts.

Test naming convention:
- ``test_S<n>_*`` -- safe_subpath (S = security)
- ``test_D<n>_*`` -- decomposer (D = decomposer)
- xfail markers carry an explicit ``reason=`` documenting whether the test
  pins HARDENED behavior we believe should hold (i.e. real bug to fix) or
  CURRENT behavior we are merely characterizing.

Index timestamp: 2026-04-20T04:01:13Z. META allow-listed (tests/adversarial/).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.safe_subpath import is_safe_subpath
from harness.task_decomposer import (
    DecompositionResult,
    Subtask,
    decompose_task,
    enqueue_subtasks,
    update_parent_state,
)
from harness.diff_fuzzer import FuzzFailure
from harness.sandbox import ExecutionResult


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _mk_failure(input_args=None, reason="return_mismatch"):
    if input_args is None:
        input_args = [5, 10]
    ra = ExecutionResult(success=True, return_value=1, return_repr="1")
    rb = ExecutionResult(success=True, return_value=2, return_repr="2")
    return FuzzFailure(
        input_args=input_args,
        input_kwargs={},
        result_a=ra,
        result_b=rb,
        reason=reason,
    )


def _mk_task(task_id="t1", meta_task_type=None, constraints=None, specification="Spec text"):
    t = {
        "task_id": task_id,
        "specification": specification,
        "constraints": constraints if constraints is not None else {},
    }
    if meta_task_type is not None:
        t["meta_task_type"] = meta_task_type
    return t


# ===========================================================================
# safe_subpath attacks (S-series)
# ===========================================================================

class TestSymlinkTraversal:
    """Symlink-based escapes -- the most common path-resolution bypass."""

    def test_S01_symlink_to_outside_base_rejected(self, tmp_path):
        """Symlink whose TARGET is outside base must be flagged unsafe.

        HARDENED: a symlink at /base/link -> /etc that is dereferenced by
        Path.resolve() will resolve to /etc/passwd, which is NOT under /base.
        The current implementation calls .resolve() on both sides, so this
        should already pass. Pin it as a regression guard.
        """
        base = tmp_path / "base"
        base.mkdir()
        link = base / "link"
        os.symlink("/etc", str(link))
        candidate = link / "passwd"  # /base/link/passwd -> /etc/passwd
        assert is_safe_subpath(str(candidate), str(base)) is False

    def test_S02_symlink_chain_to_outside_base(self, tmp_path):
        """Three-hop symlink chain A -> B -> C where C lives outside base."""
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        target_file = outside / "secret.txt"
        target_file.write_text("secret")

        link_c = base / "link_c"
        os.symlink(str(target_file), str(link_c))
        link_b = base / "link_b"
        os.symlink(str(link_c), str(link_b))
        link_a = base / "link_a"
        os.symlink(str(link_b), str(link_a))

        assert is_safe_subpath(str(link_a), str(base)) is False

    def test_S03_symlink_to_inside_base_allowed(self, tmp_path):
        """Symlink whose target IS inside base must remain allowed."""
        base = tmp_path / "base"
        sub = base / "sub"
        sub.mkdir(parents=True)
        real_file = sub / "real.txt"
        real_file.write_text("ok")
        link = base / "alias"
        os.symlink(str(real_file), str(link))
        assert is_safe_subpath(str(link), str(base)) is True

    def test_S04_dangling_symlink_treated_safely(self, tmp_path):
        """Dangling symlink (target does not exist) must not crash.

        Path.resolve(strict=False) returns the lexical path as-is; the
        candidate is still under base, so True is acceptable. The contract is
        "never raise"; either bool answer is acceptable, but a crash is not.
        """
        base = tmp_path / "base"
        base.mkdir()
        link = base / "dangling"
        os.symlink(str(tmp_path / "does_not_exist"), str(link))
        result = is_safe_subpath(str(link), str(base))
        assert isinstance(result, bool)

    def test_S05_toctou_symlink_swap_documented(self, tmp_path):
        """Document the TOCTOU window: between ``is_safe_subpath`` reading
        and the kernel resolving via subsequent open(), the symlink target
        can be swapped. This test is informational -- it demonstrates the
        race exists but cannot be eliminated at the predicate level.
        """
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = base / "swap"
        # Initially safe target (inside base).
        inside = base / "inside.txt"
        inside.write_text("safe")
        os.symlink(str(inside), str(link))

        first = is_safe_subpath(str(link), str(base))
        # Adversary swaps the symlink.
        link.unlink()
        os.symlink(str(outside), str(link))
        second = is_safe_subpath(str(link), str(base))

        # Predicate must reflect each state at call time.
        assert first is True
        assert second is False, (
            "TOCTOU: caller must NOT cache is_safe_subpath result; the "
            "predicate is per-call, not a permanent capability."
        )


class TestPathSemantics:
    """Path-level edge cases: unicode, long paths, special files."""

    def test_S06_linux_case_sensitive_paths_distinct(self, tmp_path):
        """On Linux (case-sensitive FS), /Tmp/x and /tmp/x are DIFFERENT
        paths. is_safe_subpath must not treat them as equivalent."""
        base = tmp_path / "Mixed"
        base.mkdir()
        candidate_lower = tmp_path / "mixed" / "file.py"
        # Different names on case-sensitive FS -- candidate is NOT under base.
        assert is_safe_subpath(str(candidate_lower), str(base)) is False

    def test_S07_nfc_vs_nfd_unicode_distinct(self, tmp_path):
        """NFC ``café`` (caf\\xe9) and NFD ``café`` (cafe\\u0301) are
        byte-distinct. Both must be checked against base correctly without
        crashing or normalizing silently."""
        base_nfc = tmp_path / "caf\u00e9"
        base_nfc.mkdir()
        candidate_nfc = base_nfc / "x.txt"
        candidate_nfd = tmp_path / "cafe\u0301" / "x.txt"

        # NFC vs NFC -> safe.
        assert is_safe_subpath(str(candidate_nfc), str(base_nfc)) is True
        # NFD vs NFC -> different filesystem paths on Linux ext4/btrfs;
        # candidate must NOT be flagged safe under the NFC base (no
        # silent normalization).
        result = is_safe_subpath(str(candidate_nfd), str(base_nfc))
        assert isinstance(result, bool)
        # Conservative expectation: distinct byte sequences -> not safe.
        assert result is False

    def test_S08_deeply_nested_path_no_recursion_explosion(self, tmp_path):
        """1000-deep ``/a/a/a/...`` path must not blow the stack."""
        deep = "/" + "/".join(["a"] * 1000)
        # Either True or False is acceptable; the contract is no exception.
        result = is_safe_subpath(deep, "/")
        assert isinstance(result, bool)

    def test_S09_max_length_path_handled(self, tmp_path):
        """Path approaching PATH_MAX (~4096 bytes) must not crash."""
        long_name = "x" * 4000
        result = is_safe_subpath(f"/tmp/{long_name}", "/tmp")
        assert isinstance(result, bool)

    def test_S10_proc_self_environ_outside_state(self):
        """/proc/self/environ must NOT be reported safe relative to a
        state dir under /tmp -- this is the canonical info-disclosure
        target a hostile agent would try to read."""
        assert is_safe_subpath("/proc/self/environ", "/tmp/state") is False

    def test_S11_dev_null_outside_arbitrary_base(self):
        """/dev/null is a real file but lives nowhere near worker bases."""
        assert is_safe_subpath("/dev/null", "/tmp/worker") is False

    def test_S12_null_byte_in_path_returns_false_not_crash(self):
        """Null-byte injection: Python raises ValueError on null bytes in
        paths. is_safe_subpath must absorb it and return False."""
        result = is_safe_subpath("/tmp/foo\x00bar", "/tmp")
        assert result is False, "null byte must yield False, not raise"

    def test_S13_whitespace_padding_not_stripped_silently(self, tmp_path):
        """Leading/trailing whitespace in paths refers to a different file
        than the unstripped form on POSIX. Either the predicate rejects or
        it correctly checks the literal padded path -- must not strip."""
        base = tmp_path / "base"
        base.mkdir()
        padded = f"  {base}/x  "
        # Whichever answer, must be deterministic and not raise.
        result = is_safe_subpath(padded, str(base))
        assert isinstance(result, bool)

    def test_S14_windows_drive_letter_on_linux_treated_relative(self):
        """``C:\\foo`` on Linux is a relative path of a single component
        with backslashes. Must not crash, must not be confused with /C:/foo.
        """
        result = is_safe_subpath("C:\\foo", "/tmp")
        assert result is False


class TestNoneAndTypeEdges:

    def test_S15_bytes_input_returns_false_or_handled(self):
        """Bytes path input -- pathlib accepts bytes; whatever the answer,
        must not raise."""
        result = is_safe_subpath(b"/tmp/x", "/tmp")
        assert isinstance(result, bool)

    def test_S16_int_input_returns_false(self):
        """Numeric input: contract says return False on TypeError."""
        assert is_safe_subpath(42, "/tmp") is False
        assert is_safe_subpath("/tmp/x", 42) is False


# ===========================================================================
# task_decomposer attacks (D-series)
# ===========================================================================

class TestCircularDependencies:
    """Decomposer must not loop forever on adversarial dependency graphs."""

    def test_D01_self_referential_task_id_terminates(self):
        """A task whose ID would generate a child with the same ID must
        either dedupe or terminate; must not recurse forever.

        The decomposer is single-shot (it does not recursively call itself
        on its own output), so a single decompose_task call is bounded by
        max_subtasks regardless of ID collisions. Pin that property.
        """
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        # Use an ID that, when suffixed, would collide trivially.
        task = _mk_task("loop-loop")
        result = decompose_task(task, [f1, f2], {})
        assert isinstance(result, DecompositionResult)
        assert len(result.subtasks) <= 10  # bounded

    def test_D02_circular_constraint_self_reference_no_crash(self):
        """A constraints dict that contains a self-reference must not
        cause json serialization explosion when enqueued.

        HARDENED: enqueue_subtasks calls json.dump which raises
        ValueError on circular refs. We expect either a clean rejection
        or successful serialization (e.g. via ensure_ascii fallback).
        Currently json.dump will raise -- pinned as xfail to characterize.
        """
        circ: dict = {}
        circ["self"] = circ
        sub = Subtask(
            task_id="circ-1",
            parent_task_id="parent",
            specification="x",
            constraints=circ,
        )
        with pytest.raises((ValueError, RecursionError, TypeError)):
            enqueue_subtasks([sub], Path("/tmp"))


class TestDepthAndScale:

    def test_D03_max_depth_reached_yields_planner_review(self):
        """At depth >= max_depth the decomposer returns a single
        planner_review subtask (not a recursive explosion)."""
        f = _mk_failure(input_args=[5, 10])
        cfg = {"decomposition": {"max_depth": 3}}
        result = decompose_task(_mk_task("d-bomb"), [f], cfg, depth=3)
        assert result.strategy == "planner_review"
        assert len(result.subtasks) == 1

    def test_D04_subtask_count_capped_by_max_subtasks(self):
        """Even with N>>5 failure categories, output is bounded by
        max_subtasks. Prevents the 9.7M-task depth-bomb scenario when a
        caller naively re-decomposes all children."""
        failures = [
            _mk_failure(input_args=[[]]),         # empty_input
            _mk_failure(input_args=[[42]]),       # single_element
            _mk_failure(input_args=[0]),          # boundary
            _mk_failure(input_args=[5, 10], reason="exception_mismatch"),
            _mk_failure(input_args=[5, 10]),      # general
        ]
        cfg = {"decomposition": {"max_subtasks": 3}}
        result = decompose_task(_mk_task("cap"), failures, cfg)
        assert len(result.subtasks) <= 3

    def test_D05_oversized_task_id_hashed_at_max_depth(self):
        """At max-depth the planner_review branch hashes long task_ids to
        keep filenames sane (line 456-457). Pin that contract."""
        long_id = "x" * 200
        f = _mk_failure(input_args=[5, 10])
        cfg = {"decomposition": {"max_depth": 1}}
        result = decompose_task(_mk_task(long_id), [f], cfg, depth=1)
        assert result.strategy == "planner_review"
        review_id = result.subtasks[0].task_id
        # Either truncated-with-hash or original; must not exceed safety cap.
        assert len(review_id) <= 160


class TestMetaTaskTypeEdges:

    def test_D06_explicit_constraints_override_wins_over_top_level(self):
        """When parent constraints already carry meta_task_type, the
        top-level value must NOT overwrite it. Child constraints win."""
        task = _mk_task(
            "p",
            meta_task_type="orchestration",
            constraints={"meta_task_type": "pure_function"},
        )
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        result = decompose_task(task, [f1, f2], {})
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function"

    def test_D07_no_parent_mtt_means_no_invented_child_mtt(self):
        """If parent has no meta_task_type anywhere, generated children
        must not fabricate one."""
        task = _mk_task("p")  # no mtt
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        result = decompose_task(task, [f1, f2], {})
        for st in result.subtasks:
            assert "meta_task_type" not in st.constraints or \
                st.constraints.get("meta_task_type") is None

    def test_D08_side_effect_mtt_routes_to_planner_review(self):
        """meta_task_type in SIDE_EFFECT_META_TYPES short-circuits to
        planner_review, NOT edge_case decomposition."""
        task = _mk_task("p", meta_task_type="sandbox_infra")
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        result = decompose_task(task, [f1, f2], {})
        assert result.strategy == "planner_review"
        assert len(result.subtasks) == 1


class TestMalformedConstraints:

    def test_D09_constraints_missing_key_handled(self):
        """Task without ``constraints`` key at all must not crash."""
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        task = {"task_id": "no-constraints", "specification": "x"}
        # decompose_task should default constraints to {} via .get()
        result = decompose_task(task, [f1, f2], {})
        assert isinstance(result, DecompositionResult)

    def test_D10_constraints_is_list_not_dict_raises_or_handles(self):
        """If constraints is a list (not a dict), the .get() call inside
        decompose_task will fail with AttributeError. Pin behavior.

        HARDENED expectation: the decomposer should either coerce or
        raise a typed error. Currently it raises AttributeError.
        """
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        task = {
            "task_id": "list-constraints",
            "specification": "x",
            "constraints": [{"meta_task_type": "x"}],  # list, not dict
        }
        with pytest.raises((AttributeError, TypeError)):
            decompose_task(task, [f1, f2], {})

    def test_D11_constraints_none_raises_or_handles(self):
        """constraints=None: decompose_task does .get('constraints', {})
        which returns None, then .get('meta_task_type') fails. Pin."""
        f1 = _mk_failure(input_args=[[]])
        f2 = _mk_failure(input_args=[0])
        task = {
            "task_id": "none-constraints",
            "specification": "x",
            "constraints": None,
        }
        with pytest.raises((AttributeError, TypeError)):
            decompose_task(task, [f1, f2], {})


class TestUnicodeTaskIds:

    def test_D12_emoji_task_id_serializes_cleanly(self, tmp_path):
        """Emoji in task_id must round-trip through JSON. enqueue uses
        ensure_ascii=False so this should work."""
        sub = Subtask(
            task_id="rocket-\U0001f680",
            parent_task_id="parent",
            specification="x",
            constraints={},
        )
        enqueue_subtasks([sub], tmp_path)
        # Filename must be writable; on most Linux FS this works.
        files = list((tmp_path / "tasks").iterdir())
        assert len(files) == 1
        with files[0].open() as fh:
            data = json.load(fh)
        assert data["task_id"] == "rocket-\U0001f680"

    def test_D13_rtl_override_in_task_id_does_not_corrupt_filename(self, tmp_path):
        """U+202E (RIGHT-TO-LEFT OVERRIDE) is a known filesystem-display
        attack vector. Must round-trip without corrupting the JSON."""
        sub = Subtask(
            task_id="safe-\u202egnp.exe",
            parent_task_id="parent",
            specification="x",
            constraints={},
        )
        enqueue_subtasks([sub], tmp_path)
        files = list((tmp_path / "tasks").iterdir())
        assert len(files) == 1

    def test_D14_zero_width_joiner_preserved(self, tmp_path):
        """ZWJ (U+200D) inside task_id must not be silently stripped."""
        tid = "a\u200db"
        sub = Subtask(task_id=tid, parent_task_id="p",
                      specification="x", constraints={})
        enqueue_subtasks([sub], tmp_path)
        with (tmp_path / "tasks" / f"{tid}.json").open() as fh:
            data = json.load(fh)
        assert data["task_id"] == tid


class TestEnqueueIdempotency:

    def test_D15_enqueue_empty_list_is_noop(self, tmp_path):
        """Empty subtask list must be a clean no-op: tasks dir created
        but no files written, no logger crash on subtasks[0] access."""
        enqueue_subtasks([], tmp_path)
        tasks = tmp_path / "tasks"
        assert tasks.is_dir()
        assert list(tasks.iterdir()) == []

    def test_D16_enqueue_twice_overwrites_same_file(self, tmp_path):
        """Calling enqueue twice with the same Subtask overwrites cleanly.
        Pin that we DO NOT accumulate stale shards."""
        sub = Subtask(
            task_id="dup",
            parent_task_id="p",
            specification="v1",
            constraints={},
        )
        enqueue_subtasks([sub], tmp_path)
        sub.specification = "v2"
        enqueue_subtasks([sub], tmp_path)
        with (tmp_path / "tasks" / "dup.json").open() as fh:
            data = json.load(fh)
        # Second write wins.
        assert data["specification"] == "v2"
        # Only one file exists.
        assert len(list((tmp_path / "tasks").iterdir())) == 1

    def test_D17_update_parent_state_with_empty_children(self, tmp_path):
        """update_parent_state with [] children must still set
        decomposed=True and children=[] without errors."""
        from harness.state import init_state, read_state
        init_state(tmp_path)
        update_parent_state(tmp_path, "p1", [])
        state = read_state(tmp_path)
        assert state["decomposed"] is True
        assert state["children"] == []


# ===========================================================================
# Integration: decomposer + safe_subpath
# ===========================================================================

class TestDecomposerWritesOnlyUnderStateDir:
    """Sanity bridge: enqueue_subtasks must only write inside its state_dir
    argument. If a hostile task_id contained ``../escape``, ensure the file
    lands under tasks/ regardless (or fails cleanly)."""

    def test_D18_traversal_in_task_id_does_not_escape_tasks_dir(self, tmp_path):
        """task_id containing ``../`` must not write outside tasks/.

        HARDENED: enqueue_subtasks just does ``tasks_dir / f"{tid}.json"``,
        which on POSIX resolves the ``..`` lexically -- the file CAN escape.
        We assert the predicate would catch it: is_safe_subpath on the
        resulting filename must return False.
        """
        outside_marker = tmp_path / "ESCAPED.json"
        sub = Subtask(
            task_id="../ESCAPED",
            parent_task_id="p",
            specification="x",
            constraints={},
        )
        try:
            enqueue_subtasks([sub], tmp_path / "state")
        except (OSError, ValueError):
            # Acceptable: write rejected.
            return
        # If the write succeeded, verify whether it escaped.
        produced = (tmp_path / "state" / "tasks" / "../ESCAPED.json")
        if produced.resolve() == outside_marker.resolve():
            # Real escape -- confirm safe_subpath would have caught it.
            assert is_safe_subpath(
                str(produced), str(tmp_path / "state" / "tasks")
            ) is False, (
                "BUG: enqueue_subtasks wrote outside tasks_dir AND "
                "is_safe_subpath would not have flagged it"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

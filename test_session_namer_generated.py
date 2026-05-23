# ----- generate_submission_filename -----
from harness.session_namer import generate_submission_filename


def test_generate_submission_filename_with_timestamp_full_format():
    result = generate_submission_filename("agentX", 3, "task42", "20260522T120000")
    assert result == "agentX_round3_task42_20260522T120000_submission.json"


def test_generate_submission_filename_omits_timestamp_when_none():
    result = generate_submission_filename("agentX", 3, "task42", None)
    assert result == "agentX_round3_task42_submission.json"


def test_generate_submission_filename_omits_timestamp_by_default():
    result = generate_submission_filename("agentX", 3, "task42")
    assert result == "agentX_round3_task42_submission.json"


def test_generate_submission_filename_empty_timestamp_treated_as_omitted():
    # Empty string is falsy, so the timestamp component is omitted.
    result = generate_submission_filename("agentX", 7, "task9", "")
    assert result == "agentX_round7_task9_submission.json"


def test_generate_submission_filename_round_number_interpolated_literally():
    result = generate_submission_filename("alpha", 0, "t", "ts")
    assert result == "alpha_round0_t_ts_submission.json"


def test_generate_submission_filename_negative_round_number():
    result = generate_submission_filename("alpha", -5, "t", None)
    assert result == "alpha_round-5_t_submission.json"


def test_generate_submission_filename_large_round_number():
    result = generate_submission_filename("alpha", 123456, "t", "ts")
    assert result == "alpha_round123456_t_ts_submission.json"


def test_generate_submission_filename_always_ends_with_submission_json():
    with_ts = generate_submission_filename("a", 1, "b", "c")
    without_ts = generate_submission_filename("a", 1, "b")
    assert with_ts.endswith("_submission.json")
    assert without_ts.endswith("_submission.json")


def test_generate_submission_filename_returns_str():
    result = generate_submission_filename("a", 1, "b", "c")
    assert isinstance(result, str)


def test_generate_submission_filename_preserves_special_characters_in_args():
    result = generate_submission_filename("my-agent.v2", 2, "task/sub", "2026-05-22")
    assert result == "my-agent.v2_round2_task/sub_2026-05-22_submission.json"


def test_generate_submission_filename_keyword_timestamp_argument():
    result = generate_submission_filename("a", 1, "b", timestamp_str="ts")
    assert result == "a_round1_b_ts_submission.json"


def test_generate_submission_filename_component_ordering():
    result = generate_submission_filename("AG", 4, "TID", "TS")
    # round component, then task_id, then timestamp, in that order
    assert result.index("AG") < result.index("round4")
    assert result.index("round4") < result.index("TID")
    assert result.index("TID") < result.index("TS")
    assert result.index("TS") < result.index("submission.json")


# ----- generate_feedback_filename -----
from harness.session_namer import generate_feedback_filename


def test_generate_feedback_filename_with_timestamp_includes_all_components():
    result = generate_feedback_filename("alice", 3, "task42", "20260522T120000")
    assert result == "task42_round3_alice_20260522T120000_feedback.json"


def test_generate_feedback_filename_omits_timestamp_when_none():
    result = generate_feedback_filename("alice", 3, "task42", None)
    assert result == "task42_round3_alice_feedback.json"


def test_generate_feedback_filename_timestamp_defaults_to_none():
    # timestamp_str is optional and defaults to None -> omitted form
    result = generate_feedback_filename("bob", 1, "abc")
    assert result == "abc_round1_bob_feedback.json"


def test_generate_feedback_filename_empty_timestamp_treated_as_omitted():
    # An empty string is falsy, so the timestamp component is dropped.
    result = generate_feedback_filename("bob", 1, "abc", "")
    assert result == "abc_round1_bob_feedback.json"


def test_generate_feedback_filename_round_number_rendered_as_int():
    result = generate_feedback_filename("agentX", 0, "t", "ts")
    assert result == "t_round0_agentX_ts_feedback.json"
    assert "round0" in result


def test_generate_feedback_filename_large_round_number():
    result = generate_feedback_filename("agentX", 1234567, "t", None)
    assert result == "t_round1234567_agentX_feedback.json"


def test_generate_feedback_filename_always_ends_with_feedback_json():
    with_ts = generate_feedback_filename("a", 2, "task", "stamp")
    without_ts = generate_feedback_filename("a", 2, "task", None)
    assert with_ts.endswith("_feedback.json")
    assert without_ts.endswith("_feedback.json")


def test_generate_feedback_filename_returns_str():
    result = generate_feedback_filename("a", 5, "task", "stamp")
    assert isinstance(result, str)


def test_generate_feedback_filename_preserves_special_characters_in_inputs():
    # Values are interpolated verbatim, no sanitisation is documented.
    result = generate_feedback_filename("a-b.c", 7, "task/id", "2026-05-22 12:00")
    assert result == "task/id_round7_a-b.c_2026-05-22 12:00_feedback.json"


def test_generate_feedback_filename_component_ordering_with_timestamp():
    # Order: task_id, roundN, agent, timestamp, then literal suffix.
    result = generate_feedback_filename("AGENT", 9, "TASK", "TS")
    assert result == "TASK_round9_AGENT_TS_feedback.json"
    assert result.index("TASK") < result.index("round9") < result.index("AGENT") < result.index("TS")


# ----- get_latest_submission -----
import os
from pathlib import Path

import pytest

from harness.session_namer import get_latest_submission


def _make_submission(directory, agent, round_number, task_id, suffix="", mtime=None):
    """Create a submission file that matches the documented naming scheme."""
    name = f"{agent}_round{round_number}_{task_id}{suffix}_submission.json"
    path = directory / name
    path.write_text("{}")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_get_latest_submission_returns_none_when_directory_empty(tmp_path):
    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")
    assert result is None


def test_get_latest_submission_returns_none_when_no_file_matches(tmp_path):
    # Files present but none match the agent/round/task or the suffix scheme.
    (tmp_path / "agentB_round1_taskY_submission.json").write_text("{}")
    (tmp_path / "agentX_round2_taskY_submission.json").write_text("{}")
    (tmp_path / "agentX_round1_taskZ_submission.json").write_text("{}")
    (tmp_path / "agentX_round1_taskY_feedback.json").write_text("{}")
    (tmp_path / "agentX_round1_taskY_submission.txt").write_text("{}")

    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")
    assert result is None


def test_get_latest_submission_returns_single_match(tmp_path):
    created = _make_submission(tmp_path, "agentX", 1, "taskY")

    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")

    assert result is not None
    assert isinstance(result, Path)
    assert result == created


def test_get_latest_submission_picks_most_recent_by_mtime(tmp_path):
    older = _make_submission(tmp_path, "agentX", 1, "taskY", suffix="_a", mtime=1000)
    newer = _make_submission(tmp_path, "agentX", 1, "taskY", suffix="_b", mtime=5000)
    middle = _make_submission(tmp_path, "agentX", 1, "taskY", suffix="_c", mtime=3000)

    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")

    assert result == newer
    assert result != older
    assert result != middle


def test_get_latest_submission_matches_wildcard_suffix(tmp_path):
    # The '*' in the pattern sits between task_id and '_submission.json',
    # so an extra segment after the task id must still match.
    created = _make_submission(tmp_path, "agentX", 1, "taskY", suffix="_attempt2")

    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")

    assert result == created


def test_get_latest_submission_ignores_non_matching_files(tmp_path):
    # Only this file should be considered despite siblings being present.
    match = _make_submission(tmp_path, "agentX", 1, "taskY", mtime=2000)
    # Wrong agent, but newer mtime: must be ignored.
    _make_submission(tmp_path, "agentZ", 1, "taskY", mtime=9000)
    # Wrong round, newer mtime: must be ignored.
    _make_submission(tmp_path, "agentX", 7, "taskY", mtime=9000)
    # Wrong task, newer mtime: must be ignored.
    _make_submission(tmp_path, "agentX", 1, "taskQ", mtime=9000)

    result = get_latest_submission(tmp_path, "agentX", 1, "taskY")

    assert result == match


def test_get_latest_submission_accepts_string_path(tmp_path):
    created = _make_submission(tmp_path, "agentX", 1, "taskY")

    result = get_latest_submission(str(tmp_path), "agentX", 1, "taskY")

    assert result == created


def test_get_latest_submission_distinguishes_task_id_prefix(tmp_path):
    # task_id 'task1' should not pick up a file whose task segment is 'task2',
    # but the wildcard allows 'task1' followed by more characters.
    wanted = _make_submission(tmp_path, "agentX", 1, "task1", suffix="x")
    _make_submission(tmp_path, "agentX", 1, "task2")

    result = get_latest_submission(tmp_path, "agentX", 1, "task1")

    assert result == wanted


# ----- get_latest_feedback -----
import os
from pathlib import Path

from harness.session_namer import get_latest_feedback


def _make(dir_path, name, mtime=None):
    """Create a JSON file in dir_path, optionally pinning its mtime."""
    p = Path(dir_path) / name
    p.write_text("{}")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_get_latest_feedback_returns_none_when_dir_empty(tmp_path):
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_returns_none_when_no_matching_files(tmp_path):
    _make(tmp_path, "taskX_round1_agentY_submission.json")  # wrong suffix
    _make(tmp_path, "taskX_agentY_feedback.json")           # missing round component
    _make(tmp_path, "other_round1_agentY_feedback.json")    # wrong task id
    _make(tmp_path, "taskX_round1_agentZ_feedback.json")    # wrong agent
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_finds_single_matching_file(tmp_path):
    target = _make(tmp_path, "taskX_round1_agentY_feedback.json")
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert result == target


def test_get_latest_feedback_returns_path_object(tmp_path):
    _make(tmp_path, "taskX_round1_agentY_feedback.json")
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert isinstance(result, Path)
    assert result.name == "taskX_round1_agentY_feedback.json"


def test_get_latest_feedback_returns_most_recently_modified(tmp_path):
    _make(tmp_path, "taskX_round1_agentY_feedback.json", mtime=1000)
    newer = _make(tmp_path, "taskX_round2_agentY_feedback.json", mtime=5000)
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert result == newer


def test_get_latest_feedback_selects_by_mtime_not_name(tmp_path):
    # round2 has the higher round number but an OLDER mtime; round1 is newest.
    _make(tmp_path, "taskX_round2_agentY_feedback.json", mtime=1000)
    newest = _make(tmp_path, "taskX_round1_agentY_feedback.json", mtime=9000)
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert result == newest


def test_get_latest_feedback_ignores_wrong_agent(tmp_path):
    _make(tmp_path, "taskX_round1_agentZ_feedback.json")
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_ignores_wrong_task_id(tmp_path):
    _make(tmp_path, "taskOTHER_round1_agentY_feedback.json")
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_ignores_non_feedback_suffix(tmp_path):
    _make(tmp_path, "taskX_round1_agentY_submission.json")
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_requires_round_component(tmp_path):
    # A file without the literal "_round" segment must not match.
    _make(tmp_path, "taskX_agentY_feedback.json")
    assert get_latest_feedback(tmp_path, "agentY", "taskX") is None


def test_get_latest_feedback_matches_agent_with_timestamp_suffix(tmp_path):
    target = _make(tmp_path, "taskX_round3_agentY_20240101_120000_feedback.json")
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert result == target


def test_get_latest_feedback_picks_only_matching_among_mixed(tmp_path):
    _make(tmp_path, "taskX_round1_agentY_submission.json", mtime=8000)  # newest but wrong
    _make(tmp_path, "other_round1_agentY_feedback.json", mtime=7000)    # wrong task
    target = _make(tmp_path, "taskX_round1_agentY_feedback.json", mtime=1000)
    result = get_latest_feedback(tmp_path, "agentY", "taskX")
    assert result == target


# ----- feedback_glob_pattern -----
import fnmatch
from pathlib import Path

import pytest

from harness.session_namer import feedback_glob_pattern


def test_feedback_glob_pattern_returns_expected_format_with_task_id():
    # With a concrete task_id the pattern embeds it literally and inserts a
    # wildcard only for the round number.
    assert (
        feedback_glob_pattern("reviewer", "task42")
        == "task42_round*_reviewer_feedback.json"
    )


def test_feedback_glob_pattern_none_task_id_uses_wildcard():
    # task_id of None means "any task" -> the task segment becomes "*".
    assert (
        feedback_glob_pattern("critic", None)
        == "*_round*_critic_feedback.json"
    )


def test_feedback_glob_pattern_empty_task_id_uses_wildcard():
    # Empty string is falsy, so `task_id or "*"` substitutes the wildcard.
    assert (
        feedback_glob_pattern("critic", "")
        == "*_round*_critic_feedback.json"
    )


def test_feedback_glob_pattern_embeds_agent_name():
    # The agent name is interpolated verbatim into the pattern.
    pattern = feedback_glob_pattern("my_agent_v2", "abc")
    assert "my_agent_v2" in pattern
    assert pattern == "abc_round*_my_agent_v2_feedback.json"


def test_feedback_glob_pattern_returns_str():
    result = feedback_glob_pattern("agent", "task")
    assert isinstance(result, str)


def test_feedback_glob_pattern_has_feedback_json_suffix():
    # Every produced pattern targets the feedback JSON filename contract.
    assert feedback_glob_pattern("agent", "t1").endswith("_feedback.json")
    assert feedback_glob_pattern("agent", None).endswith("_feedback.json")


def test_feedback_glob_pattern_matches_all_rounds_for_task_and_agent():
    # The returned glob must match every round's feedback file for the
    # specified (task, agent) pair.
    pattern = feedback_glob_pattern("reviewer", "task7")
    for rnd in (1, 2, 10, 99):
        filename = f"task7_round{rnd}_reviewer_feedback.json"
        assert fnmatch.fnmatch(filename, pattern)


def test_feedback_glob_pattern_does_not_match_other_agent():
    # An agent-specific pattern must not match a different agent's file.
    pattern = feedback_glob_pattern("reviewer", "task7")
    assert not fnmatch.fnmatch(
        "task7_round1_critic_feedback.json", pattern
    )


def test_feedback_glob_pattern_does_not_match_submission_files():
    # Feedback pattern must not match non-feedback (e.g. submission) files.
    pattern = feedback_glob_pattern("reviewer", "task7")
    assert not fnmatch.fnmatch(
        "task7_round1_reviewer_submission.json", pattern
    )


def test_feedback_glob_pattern_does_not_match_other_task():
    # With a concrete task_id, files of a different task must not match.
    pattern = feedback_glob_pattern("reviewer", "task7")
    assert not fnmatch.fnmatch(
        "task8_round1_reviewer_feedback.json", pattern
    )


def test_feedback_glob_pattern_wildcard_task_matches_any_task():
    # When task_id is None the pattern matches feedback files regardless of
    # the task component, but still pins the agent.
    pattern = feedback_glob_pattern("reviewer", None)
    assert fnmatch.fnmatch("alpha_round1_reviewer_feedback.json", pattern)
    assert fnmatch.fnmatch("beta_round3_reviewer_feedback.json", pattern)
    assert not fnmatch.fnmatch("alpha_round1_other_feedback.json", pattern)


def test_feedback_glob_pattern_works_with_pathlib_glob(tmp_path):
    # Exercise the pattern through real filesystem globbing.
    matching = [
        tmp_path / "task7_round1_reviewer_feedback.json",
        tmp_path / "task7_round2_reviewer_feedback.json",
    ]
    non_matching = [
        tmp_path / "task7_round1_critic_feedback.json",
        tmp_path / "task7_round1_reviewer_submission.json",
        tmp_path / "task8_round1_reviewer_feedback.json",
    ]
    for f in matching + non_matching:
        f.write_text("{}")

    pattern = feedback_glob_pattern("reviewer", "task7")
    found = sorted(p.name for p in tmp_path.glob(pattern))
    assert found == [
        "task7_round1_reviewer_feedback.json",
        "task7_round2_reviewer_feedback.json",
    ]

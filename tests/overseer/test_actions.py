"""RED oracle for overseer/actions.py — mode-gated action dispatcher.

dispatch_action enforces mode authority FIRST (fail-closed: an out-of-mode
command raises ModeViolation and NO seam fires), then routes the command to the
EXISTING operator action via an INJECTED seam, so the tested surface has zero
side effects. Read-only modes resolve only to read seams.
"""
import pytest

from overseer.mode_gate import ModeViolation
from overseer.actions import dispatch_action, ACTION_ROUTES


class RecordingSeams:
    """A seam bundle that records calls instead of performing real actions."""

    def __init__(self):
        self.calls = []

    def __getitem__(self, key):
        def _seam(args):
            self.calls.append((key, args))
            return {"seam": key, "echo": args}
        return _seam

    def __contains__(self, key):
        return True


def test_action_routes_cover_representative_modes():
    # Each tier has at least one routable command, keyed by mode then command.
    assert "observe" in ACTION_ROUTES
    assert "brief-author" in ACTION_ROUTES
    assert "dispatch" in ACTION_ROUTES
    assert "daemon-supervisor" in ACTION_ROUTES
    # Every routed mode is a real mode.
    from overseer.modes import MODE_REGISTRY
    for mode in ACTION_ROUTES:
        assert mode in MODE_REGISTRY


def test_a_valid_command_invokes_the_seam_and_returns_a_dict():
    seams = RecordingSeams()
    mode = "brief-author"
    command = next(iter(ACTION_ROUTES[mode]))
    out = dispatch_action(mode, command, {"x": 1}, seams=seams)
    assert isinstance(out, dict)
    assert len(seams.calls) == 1  # exactly one seam fired


def test_out_of_mode_command_fails_closed_no_seam_fires():
    seams = RecordingSeams()
    # observe is read-only: an authoring command must be refused BEFORE any seam.
    with pytest.raises(ModeViolation):
        dispatch_action("observe", "author_brief", {"slug": "x"}, seams=seams)
    assert seams.calls == []


def test_unknown_mode_is_rejected_fail_closed():
    seams = RecordingSeams()
    with pytest.raises(ModeViolation):
        dispatch_action("no-such-mode", "anything", {}, seams=seams)
    assert seams.calls == []


def test_read_only_modes_only_route_to_read_seams():
    # No observe/analyze/audit command may map to a write/mutating seam.
    write_seam_keys = {
        "brief_author", "oracle_author", "dispatch", "triage",
        "daemon_lifecycle", "flag_steward", "harness_self_fix",
        "rebuild", "push",
    }
    for mode in ("observe", "analyze", "audit"):
        for command, seam_key in ACTION_ROUTES.get(mode, {}).items():
            assert seam_key not in write_seam_keys


def test_daemon_supervisor_pause_is_routable():
    # pause is the fail-safe direction and must always be available in-mode.
    seams = RecordingSeams()
    assert "pause" in ACTION_ROUTES["daemon-supervisor"]
    out = dispatch_action("daemon-supervisor", "pause", {}, seams=seams)
    assert isinstance(out, dict)
    assert seams.calls and seams.calls[0][0] is not None


# --- procedure phase sequence-lock (enforcement-integration leaf) -------------
# Beside the existing (mode, command) authority check, dispatch_action gains a
# fail-closed (phase, command) check: while a procedure is active, a command not
# sanctioned by the CURRENT phase is refused BEFORE any seam fires. With phase
# unset the behaviour above is unchanged.
from overseer.actions import PHASE_COMMAND_POLICY


def test_default_phase_command_policy_is_a_mapping():
    assert isinstance(PHASE_COMMAND_POLICY, dict)


def test_phase_allows_its_sanctioned_command():
    seams = RecordingSeams()
    out = dispatch_action("brief-author", "author_brief", {"slug": "x"},
                          seams=seams, phase="BRIEF",
                          phase_policy={"BRIEF": {"author_brief"}})
    assert isinstance(out, dict)
    assert len(seams.calls) == 1


def test_phase_blocks_an_out_of_phase_command_fail_closed():
    seams = RecordingSeams()
    # author_oracle is a valid brief-author command, but the BRIEF phase does not
    # sanction it -> refused before any seam fires (zero side effects).
    with pytest.raises(ModeViolation):
        dispatch_action("brief-author", "author_oracle", {"slug": "x"},
                        seams=seams, phase="BRIEF",
                        phase_policy={"BRIEF": {"author_brief"}})
    assert seams.calls == []


def test_phase_none_preserves_existing_behaviour():
    seams = RecordingSeams()
    out = dispatch_action("brief-author", "author_brief", {"slug": "x"}, seams=seams)
    assert isinstance(out, dict) and len(seams.calls) == 1


def test_mode_authority_is_still_checked_before_phase():
    seams = RecordingSeams()
    with pytest.raises(ModeViolation):
        dispatch_action("observe", "author_brief", {}, seams=seams,
                        phase="BRIEF", phase_policy={"BRIEF": {"author_brief"}})
    assert seams.calls == []

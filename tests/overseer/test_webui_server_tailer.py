"""RED oracle for the tools/webui_server.py EDIT leaf (harness_plumbing).

THIN wiring: add logs/overseer_chat.jsonl to build_tailer's fixed-paths set so
the driver's streamed deltas relay to the browser over the existing /events SSE
channel. Functional assertion against the real StateTailer.paths.
"""
from tools.webui_server import build_tailer


def test_overseer_chat_log_is_in_the_tailers_fixed_paths(tmp_path):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()

    tailer = build_tailer(state_dir, logs_dir, buffer_size=64)
    watched = [str(p) for p in tailer.paths]

    expected = str(logs_dir / "overseer_chat.jsonl")
    assert expected in watched, f"tailer does not watch {expected}; watches {watched}"


def test_existing_stream_logs_still_watched(tmp_path):
    # Additive edit: the pre-existing fixed paths must be preserved.
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()

    tailer = build_tailer(state_dir, logs_dir, buffer_size=64)
    watched = [str(p) for p in tailer.paths]

    assert str(logs_dir / "claude_stream.jsonl") in watched
    assert str(state_dir / "impl_progress.jsonl") in watched

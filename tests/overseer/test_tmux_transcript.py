"""Oracle: read a claude-tmux turn's reply from the structured session transcript.

For the ``claude-tmux`` backend the agent runs as an INTERACTIVE claude in a tmux
pane, which persists a structured transcript JSONL at
``<config_dir>/projects/<sanitized-cwd>/<session-uuid>.jsonl`` -- one record per
message. ``overseer.tmux_transcript`` reads the reply from THAT file (never by
scraping the TUI): it locates the project dir from the cwd, picks the session
file, parses the JSONL, and folds the NEW ``assistant`` records since a marker
into an ``overseer.driver.AssistantTurn`` (text + tool_use blocks + session id).

Everything is pure over INJECTED ``read_text`` / ``list_dir`` seams -- no real
filesystem walk of the operator's home, no agent, no network. The cwd-slug
fixture is the REAL sanitisation claude produced for ``/tmp/jm_tmux_spike`` in a
live drive (-> ``-tmp-jm-tmux-spike``); note an underscore sanitises to ``-``.
"""
from __future__ import annotations

import json

from overseer import tmux_transcript as tt
from overseer.driver import AssistantTurn


# --- real record shapes (claude transcript JSONL) ---------------------------

def _rec(**kw):
    return json.dumps(kw)


def _assistant_text(text):
    return _rec(type="assistant",
                message={"role": "assistant", "content": [{"type": "text", "text": text}]})


def _assistant_tool(name, tid="t1"):
    return _rec(type="assistant",
                message={"role": "assistant",
                         "content": [{"type": "tool_use", "name": name, "id": tid, "input": {}}]})


USER_REC = _rec(type="user", message={"role": "user", "content": "what is 19*23?"})
SYSTEM_REC = _rec(type="system", subtype="something")
ATTACH_REC = _rec(type="attachment")


class FakeFS:
    """Injected fs seams: list_dir(dir)->names, read_text(path)->str."""

    def __init__(self, tree):
        # tree: {dirpath: {filename: text}}
        self.tree = tree

    def list_dir(self, path):
        return list(self.tree.get(str(path), {}).keys())

    def read_text(self, path):
        import os
        d, n = os.path.split(str(path))
        return self.tree[d][n]


# --- cwd sanitisation / path derivation -------------------------------------

def test_sanitize_cwd_matches_real_claude_slug():
    # the live-captured truth: '/tmp/jm_tmux_spike' -> '-tmp-jm-tmux-spike'
    assert tt.sanitize_cwd("/tmp/jm_tmux_spike") == "-tmp-jm-tmux-spike"


def test_sanitize_cwd_non_alnum_all_become_dash():
    assert tt.sanitize_cwd("/a/b.c_d") == "-a-b-c-d"


def test_project_dir_is_config_projects_slug():
    pd = str(tt.project_dir("/cfg", "/tmp/jm_tmux_spike"))
    assert pd.replace("\\", "/") == "/cfg/projects/-tmp-jm-tmux-spike"


# --- session-file selection -------------------------------------------------

def test_pick_session_file_prefers_named_session():
    names = ["aaa.jsonl", "bbb.jsonl"]
    assert tt.pick_session_file(names, prefer="bbb") == "bbb.jsonl"


def test_pick_session_file_ignores_non_jsonl_and_handles_empty():
    assert tt.pick_session_file(["notes.txt"], prefer=None) is None
    assert tt.pick_session_file([], prefer=None) is None


# --- record parsing ---------------------------------------------------------

def test_parse_records_skips_malformed_lines():
    recs = tt.parse_records([_assistant_text("ok"), "{not json", "", _assistant_text("two")])
    assert [r.get("type") for r in recs] == ["assistant", "assistant"]


# --- folding records into an AssistantTurn ----------------------------------

def test_fold_collects_assistant_text_only():
    recs = tt.parse_records([USER_REC, _assistant_text("Hello"), SYSTEM_REC, _assistant_text(" world")])
    turn = tt.fold_records(recs, session_id="sess-9")
    assert isinstance(turn, AssistantTurn)
    assert turn.text == "Hello world"          # user/system ignored, assistant text joined
    assert turn.session_id == "sess-9"
    assert turn.tool_uses == []


def test_fold_collects_tool_use_blocks():
    recs = tt.parse_records([_assistant_tool("Read", "t1"), _assistant_text("done")])
    turn = tt.fold_records(recs, session_id="s")
    names = [b.get("name") for b in turn.tool_uses]
    assert names == ["Read"]
    assert turn.text == "done"


def test_fold_empty_records_is_empty_turn():
    turn = tt.fold_records([], session_id="s")
    assert turn.text == "" and turn.tool_uses == []


# --- read_new_turn: the seam-driven orchestrator ----------------------------

def _tree(slug_dir, fname, lines):
    return {slug_dir: {fname: "\n".join(lines) + "\n"}}


def test_read_new_turn_reads_reply_and_advances_marker():
    pdir = "/cfg/projects/-tmp-jm-tmux-spike"
    lines = [USER_REC, _assistant_text("437")]
    fs = FakeFS(_tree(pdir, "sess-uuid.jsonl", lines))
    turn, marker = tt.read_new_turn(
        "/cfg", "/tmp/jm_tmux_spike", marker=0,
        read_text=fs.read_text, list_dir=fs.list_dir, session_pref="sess-uuid")
    assert turn.text == "437"
    assert turn.session_id == "sess-uuid"      # session id is the file stem
    assert marker == 2                          # both lines consumed


def test_read_new_turn_only_reads_lines_after_marker():
    pdir = "/cfg/projects/-tmp-jm-tmux-spike"
    lines = [USER_REC, _assistant_text("first"), USER_REC, _assistant_text("second")]
    fs = FakeFS(_tree(pdir, "s.jsonl", lines))
    # marker=2 means the first two lines were already consumed in a prior turn
    turn, marker = tt.read_new_turn(
        "/cfg", "/tmp/jm_tmux_spike", marker=2,
        read_text=fs.read_text, list_dir=fs.list_dir, session_pref="s")
    assert turn.text == "second"               # only the new assistant record
    assert marker == 4


def test_read_new_turn_missing_dir_returns_empty_turn_same_marker():
    fs = FakeFS({})  # no project dir at all
    turn, marker = tt.read_new_turn(
        "/cfg", "/tmp/whatever", marker=5,
        read_text=fs.read_text, list_dir=fs.list_dir, session_pref="x")
    assert isinstance(turn, AssistantTurn)
    assert turn.text == "" and turn.tool_uses == []
    assert marker == 5                          # marker unchanged when nothing read


def test_read_new_turn_no_session_file_is_tolerated():
    pdir = "/cfg/projects/-tmp-x"
    fs = FakeFS({pdir: {"README.txt": "not a transcript"}})
    turn, marker = tt.read_new_turn(
        "/cfg", "/tmp/x", marker=0,
        read_text=fs.read_text, list_dir=fs.list_dir, session_pref=None)
    assert turn.text == "" and marker == 0

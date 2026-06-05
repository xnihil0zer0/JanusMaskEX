"""Oracle for the autobrief stdout parser (stream-json vs single-JSON).

RED on HEAD: ``tools.webui_control`` has no ``_parse_autobrief_stdout`` helper;
``post_brief_autocomplete.run_attempt`` does a bare ``json.loads`` over the whole
agent stdout, which raises ``json.JSONDecodeError: Extra data`` on the Claude CLI
``--output-format stream-json`` NDJSON transcript (many JSON events, one per
line). The autocomplete then 502s, the brief slug/content never populate in the
UI, and ``POST /api/briefs//validate`` 404s on the empty slug.

GREEN after the fix: a top-level ``_parse_autobrief_stdout(stdout_text)`` helper
extracts the ``{slug, content}`` payload from BOTH agent output shapes:

  * a single JSON document (agy / antigravity ``-p`` plain output), and
  * stream-json NDJSON, where the final ``{"type":"result"}`` line carries the
    real payload as a JSON STRING in its ``result`` field.
"""
import json

import pytest


def _get_parser():
    from tools.webui_control import _parse_autobrief_stdout
    return _parse_autobrief_stdout


# A realistic, trimmed Claude CLI --output-format stream-json transcript: an
# init system event, an assistant event, then the terminal result event whose
# ``result`` string is the JSON the endpoint actually wants.
_PAYLOAD = {
    "slug": "commit_lock_reclaim",
    "content": "---\nfreeze_lift: x\nauthor: a\nsynthesis_of: []\nrelates_to: []\n---\n\n# Title\nT\n",
}
_STREAM_JSON = "\n".join([
    json.dumps({"type": "system", "subtype": "init", "session_id": "abc", "model": "claude-opus-4-8"}),
    json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "..."}]}}),
    json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(_PAYLOAD)}),
]) + "\n"

# agy / antigravity plain ``-p`` output: a single JSON document on stdout.
_SINGLE_JSON = json.dumps(_PAYLOAD)


def test_parses_stream_json_ndjson():
    """The Claude stream-json transcript yields the nested {slug, content}."""
    parser = _get_parser()
    out = parser(_STREAM_JSON)
    assert out["slug"] == "commit_lock_reclaim"
    assert out["content"].startswith("---")


def test_parses_single_json_document():
    """agy-style single-JSON stdout still parses (regression: must not break)."""
    parser = _get_parser()
    out = parser(_SINGLE_JSON)
    assert out["slug"] == "commit_lock_reclaim"
    assert out["content"].startswith("---")


def test_stream_json_takes_last_result_event():
    """When multiple result events appear, the final one wins."""
    parser = _get_parser()
    early = json.dumps({"type": "result", "result": json.dumps({"slug": "stale", "content": "old"})})
    transcript = early + "\n" + _STREAM_JSON
    out = parser(transcript)
    assert out["slug"] == "commit_lock_reclaim"


def test_unparseable_stdout_raises():
    """Non-JSON / payload-less stdout is rejected (caller maps to parse_failed)."""
    parser = _get_parser()
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parser("this is not json at all\nneither is this\n")


def test_missing_slug_or_content_raises():
    """A JSON object lacking slug/content is not a valid payload."""
    parser = _get_parser()
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parser(json.dumps({"slug": "only_slug"}))

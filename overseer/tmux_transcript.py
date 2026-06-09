"""Read a claude-tmux turn's reply from the structured session transcript.

For the ``claude-tmux`` backend the agent runs as an INTERACTIVE claude in a
tmux pane, which persists a structured transcript JSONL at
``<config_dir>/projects/<sanitized-cwd>/<session-uuid>.jsonl`` -- one record per
message. This module reads the reply from THAT file (never by scraping the
TUI): it locates the project dir from the cwd, picks the session file, parses
the JSONL, and folds the NEW ``assistant`` records since a marker into an
``overseer.driver.AssistantTurn`` (text + tool_use blocks + session id).

Everything is pure over INJECTED ``read_text`` / ``list_dir`` seams -- no real
filesystem walk of the operator's home, no agent, no network.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from overseer.driver import AssistantTurn

def sanitize_cwd(cwd: str) -> str:
    """Replace EVERY non-alphanumeric char with '-' (matches claude's slug)."""
    return re.sub('[^a-zA-Z0-9]', '-', cwd)

def project_dir(config_dir: str, cwd: str) -> str:
    """Return ``<config_dir>/projects/<sanitize_cwd(cwd)>``."""
    return os.path.join(config_dir, 'projects', sanitize_cwd(cwd))

def pick_session_file(names: List[str], *, prefer: Optional[str]=None) -> Optional[str]:
    """Return ``prefer+'.jsonl'`` if present, else the sorted-last ``.jsonl``.

    Non-``.jsonl`` names are ignored. Returns ``None`` when there is no
    candidate.
    """
    jsonls = [n for n in names if n.endswith('.jsonl')]
    if prefer is not None:
        wanted = prefer + '.jsonl'
        if wanted in jsonls:
            return wanted
    if jsonls:
        return sorted(jsonls)[-1]
    return None

def parse_records(lines: List[str]) -> List[Dict[str, Any]]:
    """Return the list of dict JSON records, skipping empty/malformed lines."""
    records: List[Dict[str, Any]] = []
    for line in lines:
        if not line or not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records

def fold_records(records: List[Dict[str, Any]], *, session_id: str) -> AssistantTurn:
    """Fold ``assistant`` records into an :class:`AssistantTurn`.

    Collects ONLY assistant-record text (joined) and ``tool_use`` blocks;
    ``user``/``system``/``attachment`` records are ignored.
    """
    texts: List[str] = []
    tool_uses: List[Dict[str, Any]] = []
    for rec in records:
        if rec.get('type') != 'assistant':
            continue
        message = rec.get('message') or {}
        content = message.get('content') or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get('type')
            if btype == 'text':
                texts.append(block.get('text', ''))
            elif btype == 'tool_use':
                tool_uses.append(block)
    return AssistantTurn(session_id=session_id, text=''.join(texts), tool_uses=tool_uses)

def read_new_turn(config_dir: str, cwd: str, *, marker: int=0, read_text: Callable[[str], str], list_dir: Callable[[str], List[str]], session_pref: Optional[str]=None) -> Tuple[AssistantTurn, int]:
    """Read the new assistant turn from the session transcript.

    ``list_dir`` the project dir, pick the file, ``read_text`` it, parse only
    ``lines[marker:]``, and fold with ``session_id`` = the file stem.
    ``new_marker`` is the total line count. On any miss (no dir/file, read
    error) return ``(AssistantTurn(), marker)`` -- never raises.
    """
    pdir = project_dir(config_dir, cwd)
    try:
        names = list_dir(pdir)
    except Exception:
        return (AssistantTurn(), marker)
    if not names:
        return (AssistantTurn(), marker)
    fname = pick_session_file(list(names), prefer=session_pref)
    if fname is None:
        return (AssistantTurn(), marker)
    path = os.path.join(pdir, fname)
    try:
        text = read_text(path)
    except Exception:
        return (AssistantTurn(), marker)
    lines = text.splitlines()
    total = len(lines)
    session_id = fname[:-len('.jsonl')]
    records = parse_records(lines[marker:])
    turn = fold_records(records, session_id=session_id)
    return (turn, total)
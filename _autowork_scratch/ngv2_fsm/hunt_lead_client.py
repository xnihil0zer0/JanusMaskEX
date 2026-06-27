"""Agy-backed HUNT lead generator for the NobleGreedv2 conductor loop.

The hunt-phase worker (``ngv2.workers.hunt``) expects its ``llm_client`` seam to
be a callable that takes the stage pool (``target``/``context``/...) and returns
``{"candidates": [<finding-shaped dict>, ...]}`` -- NOT the raw chat-completion
``complete(messages=...)`` callable. ``make_hunt_lead_client`` returns exactly
that adapter: it reads a bounded slice of the target repo's source, asks the agy
CLI (via :func:`ngv2.agy_client.make_agy_complete`, so the selection oracle's
``.backend == 'agy'`` contract holds) to enumerate concrete vulnerability
candidates as JSON, and parses the reply into the candidate list.

Each candidate is shaped so the rest of the FSM can act on it: ``title``,
``category``, ``severity``, ``description``, ``evidence`` (``["file:line"]``),
``sink_name``, ``call_sites``, ``expected_signature`` (a literal substring that
must be present in the vulnerable source), plus the detonation oracle hints
``expected_fs_signature`` and ``success_marker``. Missing oracle hints default to
the project-wide markers so a genuine PoC can still be semantically confirmed.

Pure-ish and fail-soft: any error (no repo, agy failure, unparseable reply)
yields ``{"candidates": []}`` rather than raising, so a hunt step degrades to
"no leads" instead of crashing the conductor.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

DEFAULT_SUCCESS_MARKER = "VULNERABLE"
DEFAULT_FS_SIGNATURE = "pwned_marker"

_SOURCE_EXTENSIONS = (".py",)
_MAX_FILES = 40
_MAX_FILE_BYTES = 20_000
_MAX_TOTAL_BYTES = 180_000
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "tests",
              "test", "docs", "examples", "build", "dist", ".tox"}

_SYSTEM = (
    "You are a senior application-security researcher hunting for HIGH-IMPACT, "
    "ATTACKER-REACHABLE vulnerabilities (command/SQL/code injection, SSRF, "
    "path traversal, deserialization, auth/IDOR) in the provided source. Only "
    "report a vulnerability when a concrete untrusted input reaches a dangerous "
    "sink. Do NOT invent issues."
)

_INSTRUCTION = (
    "Return ONLY a JSON array (no prose) of vulnerability candidates. Each item "
    "MUST be an object with keys: title, category (a CWE id like 'CWE-89'), "
    "severity (low|medium|high|critical), description, evidence (an array of "
    "\"relative/path.py:line\" strings pointing at the vulnerable line), "
    "sink_name (the dangerous call, e.g. 'os.system'), call_sites (an array of "
    "short code strings showing the sink called with untrusted, non-constant "
    "input), and expected_signature (a literal substring copied verbatim from "
    "the vulnerable source line). Return [] if you find nothing solid."
)


def _iter_source(repo: str) -> List[str]:
    """Walk ``repo`` and return a bounded list of 'path\\n<source>' blocks."""
    blocks: List[str] = []
    total = 0
    if not isinstance(repo, str) or not os.path.isdir(repo):
        return blocks
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if not name.endswith(_SOURCE_EXTENSIONS):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    continue
                with open(path, "r", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue
            rel = os.path.relpath(path, repo)
            block = "### FILE: {0}\n{1}".format(rel, text)
            total += len(block)
            blocks.append(block)
            if len(blocks) >= _MAX_FILES or total >= _MAX_TOTAL_BYTES:
                return blocks
    return blocks


def _build_messages(repo: str, target: Any) -> List[Dict[str, str]]:
    blocks = _iter_source(repo)
    corpus = "\n\n".join(blocks) if blocks else "(no readable source files)"
    user = (
        "Target: {0}\nRepo root: {1}\n\n{2}\n\n--- SOURCE ---\n{3}\n--- END SOURCE ---"
    ).format(target, repo, _INSTRUCTION, corpus)
    return [{"role": "user", "content": user}]


def _extract_json_array(text: str) -> List[Any]:
    """Best-effort parse of a JSON array of candidates from an LLM reply."""
    if not isinstance(text, str) or not text.strip():
        return []
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ("candidates", "findings", "results", "items", "vulnerabilities"):
                if isinstance(obj.get(key), list):
                    return obj[key]
            return [obj]
    except Exception:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, list):
                return obj
        except Exception:
            return []
    return []


def _normalize_candidate(raw: Any, index: int, target: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = raw.get("title") or raw.get("name") or raw.get("summary")
    if not title:
        return None
    cand: Dict[str, Any] = dict(raw)
    cand.setdefault("id", "HUNT-{0:03d}".format(index + 1))
    cand["title"] = title
    cand.setdefault("category", raw.get("cwe") or "CWE-000")
    cand.setdefault("severity", "high")
    cand.setdefault("description", raw.get("detail") or "")
    cand.setdefault("target", target)
    ev = cand.get("evidence")
    if not isinstance(ev, list):
        cand["evidence"] = [str(ev)] if ev else []
    cs = cand.get("call_sites")
    if not isinstance(cs, list):
        cand["call_sites"] = [str(cs)] if cs else []
    cand.setdefault("expected_fs_signature", DEFAULT_FS_SIGNATURE)
    cand.setdefault("success_marker", DEFAULT_SUCCESS_MARKER)
    return cand


def make_hunt_lead_client(
    *,
    complete: Optional[Callable[..., str]] = None,
    max_tokens: int = 4096,
    **agy_kwargs: Any,
) -> Callable[..., Dict[str, List[Dict[str, Any]]]]:
    """Return the hunt ``llm_client`` adapter ``(**pool) -> {'candidates': [...]}``.

    ``complete`` defaults to :func:`ngv2.agy_client.make_agy_complete` so the
    returned adapter is agy-backed and tagged ``.backend == 'agy'``.
    """
    chat = complete
    if chat is None:
        from ngv2.agy_client import make_agy_complete
        chat = make_agy_complete(**agy_kwargs)

    def lead_client(**pool: Any) -> Dict[str, List[Dict[str, Any]]]:
        ctx = pool.get("context") or pool.get("ctx") or {}
        if not isinstance(ctx, dict):
            ctx = {}
        repo = ctx.get("repo") or pool.get("repo") or ""
        target = pool.get("target") or pool.get("subject") or ctx.get("target") or repo
        try:
            messages = _build_messages(repo, target)
            reply = chat(messages, max_tokens=max_tokens, system=_SYSTEM)
        except Exception:
            return {"candidates": []}
        raw_items = _extract_json_array(reply)
        candidates: List[Dict[str, Any]] = []
        for index, raw in enumerate(raw_items):
            cand = _normalize_candidate(raw, index, target)
            if cand is not None:
                candidates.append(cand)
        return {"candidates": candidates}

    lead_client.backend = "agy"
    return lead_client

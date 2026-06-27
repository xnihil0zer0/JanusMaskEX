"""Pure React-Server-Component (RSC) flight payload extractor for huntr.com.

huntr.com is a Next.js SPA. Its server-rendered HTML embeds RSC "flight" rows
either inside ``<script>self.__next_f.push([1, "<row>"])</script>`` chunks, or
(when fetched with the ``RSC: 1`` header) as a bare flight stream with no HTML
wrapper at all.

A flight stream is a concatenation of rows. Each row begins with a hex id and a
colon::

    <hexid>:<payload>\\n

The payload is usually a single-line JSON value (objects/arrays/strings/etc.),
but it can also be a *length-prefixed text row*::

    <hexid>:T<hexlen>,<raw text>

whose ``<raw text>`` is exactly ``<hexlen>`` UTF-8 bytes long and may itself
contain literal newlines. Naive line-splitting therefore mis-frames the stream;
this module scan-decodes rows honoring the ``T`` length framing instead.

This module is PURE over the injected string: no network, no browser. It never
raises on malformed / payload-free input -- it yields empty results instead.

Public API:
    parse_hacktivity(html: str) -> list[dict]
    parse_repo_page(html: str) -> dict
    parse_bounties_index(html: str) -> list[str]
"""
from __future__ import annotations
import json
import re
import urllib.parse
from typing import Any, Iterator
__all__ = ['parse_hacktivity', 'parse_repo_page', 'parse_bounties_index']
_PUSH_NEEDLE = 'self.__next_f.push('
_ROW_HEADER = re.compile('([0-9a-fA-F]+):')

def _extract_push_chunks(html: str) -> list[str]:
    """Pull the string payload out of every ``self.__next_f.push([1, "..."])``
    call, in document order. Next.js may split the flight stream across many
    pushes; concatenating these strings reassembles the full stream."""
    chunks: list[str] = []
    decoder = json.JSONDecoder()
    length = len(html)
    pos = 0
    while True:
        i = html.find(_PUSH_NEEDLE, pos)
        if i == -1:
            break
        j = i + len(_PUSH_NEEDLE)
        while j < length and html[j] in ' \t\r\n':
            j += 1
        if j >= length or html[j] != '[':
            pos = i + len(_PUSH_NEEDLE)
            continue
        try:
            arr, end = decoder.raw_decode(html, j)
        except ValueError:
            pos = i + len(_PUSH_NEEDLE)
            continue
        pos = end
        if isinstance(arr, list) and len(arr) >= 2 and isinstance(arr[1], str):
            chunks.append(arr[1])
    return chunks

def _get_stream(html: str) -> str:
    """Return the bare flight stream for either input shape."""
    if not html:
        return ''
    if _PUSH_NEEDLE in html:
        return ''.join(_extract_push_chunks(html))
    return html

def _advance_bytes(s: str, start: int, length: int) -> int:
    """Return the index ``end`` such that ``s[start:end]`` encodes to exactly
    ``length`` UTF-8 bytes (the framing unit RSC ``T`` rows use)."""
    n = len(s)
    fast_end = start + length
    if fast_end <= n and s[start:fast_end].isascii():
        return fast_end
    count = 0
    i = start
    while i < n and count < length:
        o = ord(s[i])
        if o < 128:
            count += 1
        elif o < 2048:
            count += 2
        elif o < 65536:
            count += 3
        else:
            count += 4
        i += 1
    return i

def _iter_rows(stream: str) -> Iterator[tuple[str, str]]:
    """Yield ``(kind, payload)`` for each framed flight row.

    ``kind`` is ``"json"`` for ordinary rows (payload is the raw single-line
    value) or ``"text"`` for length-prefixed ``T`` rows (payload is the raw
    text, which is skipped for record extraction but framed correctly so it
    never mis-frames the rows that follow).
    """
    pos = 0
    n = len(stream)
    while pos < n:
        match = _ROW_HEADER.match(stream, pos)
        if not match:
            nl = stream.find('\n', pos)
            if nl == -1:
                break
            pos = nl + 1
            continue
        body_pos = match.end()
        if body_pos < n and stream[body_pos] == 'T':
            comma = stream.find(',', body_pos)
            if comma == -1:
                break
            hexpart = stream[body_pos + 1:comma]
            try:
                row_len = int(hexpart, 16)
            except ValueError:
                nl = stream.find('\n', body_pos)
                if nl == -1:
                    break
                pos = nl + 1
                continue
            raw_start = comma + 1
            end = _advance_bytes(stream, raw_start, row_len)
            yield ('text', stream[raw_start:end])
            pos = end
            if pos < n and stream[pos] == '\n':
                pos += 1
        else:
            nl = stream.find('\n', body_pos)
            if nl == -1:
                yield ('json', stream[body_pos:])
                pos = n
            else:
                yield ('json', stream[body_pos:nl])
                pos = nl + 1

def _decode_payloads(html: str) -> list[Any]:
    """Decode every JSON-bearing flight row into a Python tree, in order."""
    stream = _get_stream(html)
    payloads: list[Any] = []
    for kind, payload in _iter_rows(stream):
        if kind != 'json':
            continue
        text = payload.strip()
        if not text or text[0] not in '[{"-0123456789tfn':
            continue
        try:
            payloads.append(json.loads(payload))
        except (ValueError, TypeError):
            continue
    return payloads

def _is_record(node: Any) -> bool:
    """A hacktivity / disclosure record carries, at minimum, ``id`` + ``title``
    plus a ``repository`` dict with ``owner``/``name`` and the ``cwe`` /
    ``disclosure`` signature fields."""
    if not isinstance(node, dict):
        return False
    if 'id' not in node or 'title' not in node:
        return False
    repository = node.get('repository')
    if not isinstance(repository, dict):
        return False
    if 'owner' not in repository or 'name' not in repository:
        return False
    if 'cwe' not in node or 'disclosure' not in node:
        return False
    return True

def _collect_records(tree: Any, out: list[dict]) -> None:
    """Append every record dict found in ``tree`` to ``out`` in document order.

    Iterative DFS (preserving order) so deeply nested RSC trees never blow the
    recursion limit. A matched record is not descended into.
    """
    stack: list[Any] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if _is_record(node):
                out.append(node)
                continue
            for value in reversed(list(node.values())):
                stack.append(value)
        elif isinstance(node, list):
            for item in reversed(node):
                stack.append(item)

def _extract_records(html: str) -> list[dict]:
    """Return de-duplicated (by ``id``) records in document order."""
    found: list[dict] = []
    for payload in _decode_payloads(html):
        _collect_records(payload, found)
    seen: set = set()
    result: list[dict] = []
    for record in found:
        ident = record.get('id')
        marker = ident if isinstance(ident, (str, int, float, bool)) else id(record)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(record)
    return result

def parse_hacktivity(html: str) -> list[dict]:
    """Extract hacktivity feed record dicts from an injected page string.

    Accepts both HTML-wrapped ``self.__next_f.push`` chunks and bare raw RSC
    flight streams. Returns records in document order; never raises.
    """
    if not isinstance(html, str) or not html:
        return []
    return _extract_records(html)

def parse_repo_page(html: str) -> dict:
    """Extract a per-repo disclosure page into ``{"disclosures": [...]}``.

    Each disclosure record preserves any maintainer triage rationale string
    (e.g. ``#score|0|awarded`` / ``#self_closedduplicate``) verbatim. Never
    raises; payload-free input yields an empty disclosure list.
    """
    if not isinstance(html, str) or not html:
        return {'disclosures': []}
    return {'disclosures': _extract_records(html)}
_TARGET = re.compile('target=([^\\"\'&\\s>]+)')
_GITHUB = re.compile('github\\.com/([^/\\"\'?#]+)/([^/\\"\'?#]+)')

def parse_bounties_index(html: str) -> list[str]:
    """Extract the eligible ``owner/name`` set from the server-rendered
    ``/bounties`` index page.

    Repo cards link via
    ``href=".../bounties/disclose/opensource?target=https://github.com/{owner}/{name}"``.
    The returned list is lowercased, de-duplicated, and sorted.
    """
    if not isinstance(html, str) or not html:
        return []
    repos: set = set()
    for match in _TARGET.finditer(html):
        target = urllib.parse.unquote(match.group(1))
        github = _GITHUB.search(target)
        if not github:
            continue
        owner = github.group(1).strip()
        name = github.group(2).strip()
        if not owner or not name:
            continue
        repos.add(f'{owner.lower()}/{name.lower()}')
    return sorted(repos)
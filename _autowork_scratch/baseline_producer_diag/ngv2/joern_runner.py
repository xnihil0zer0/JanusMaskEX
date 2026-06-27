"""Deterministic Joern CPG taint-analysis seam for NGv2.

The legacy NobleGreed ``joern_analyzer`` shelled out to the Joern JVM CLI to
build a Code Property Graph and run reachability / taint queries.  That live
JVM subprocess is a runtime concern; this module distils only the DURABLE,
deterministic capability: the pure shell that assembles a query operation,
hands it to an INJECTED runner ``runner(op, args) -> str`` (``op`` is one of
``'parse'`` / ``'flow'`` / ``'sources'``) and PARSES the textual stdout Joern
emits (the ``FLOW_COUNT=`` / ``FLOW_PATH=`` / ``SOURCE=`` protocol) into stable
``dict`` / ``list`` shapes.

This module never imports, spawns, or otherwise touches the real Joern binary
or any subprocess: every engine call is routed through the injected runner.
Stdlib only; no sibling Epic-4 leaf is imported.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Mapping, Optional, Union
__all__ = ['create_cpg', 'verify_taint_flow', 'find_taint_sources', 'make_mock_joern', 'make_scripted_joern', 'JOERN_HEAP', 'JOERN_TIMEOUT', 'TAINT_FLOW_FIELDS', 'TAINT_SOURCE_FIELDS']
JOERN_HEAP: str = '16g'
JOERN_TIMEOUT: int = 120
TAINT_FLOW_FIELDS = ('confirmed', 'path', 'hops', 'query_time_s')
TAINT_SOURCE_FIELDS = ('file', 'line', 'function', 'source_type')
_MAX_PATHS = 5
JoernRunner = Callable[[str, Mapping[str, object]], str]

def create_cpg(repo_path: str, runner: JoernRunner) -> str:
    """Build a CPG for ``repo_path`` through the injected ``runner``.

    The runner is invoked with the ``'parse'`` op and returns the path to the
    generated CPG binary on stdout.  The trimmed stdout is returned verbatim.
    An empty / whitespace-only response is treated as a build failure.
    """
    args: Dict[str, object] = {'repo': repo_path, 'heap': JOERN_HEAP, 'timeout': JOERN_TIMEOUT}
    stdout = runner('parse', args)
    cpg_path = (stdout or '').strip()
    if not cpg_path:
        raise RuntimeError('joern parse produced no CPG path for repo: {0}'.format(repo_path))
    return cpg_path

def verify_taint_flow(cpg_path: str, source_file: str, source_line: int, sink_file: str, sink_line: int, runner: JoernRunner) -> Dict[str, object]:
    """Confirm whether tainted data flows from a source to a sink.

    Invokes the injected ``runner`` with the ``'flow'`` op and parses the
    ``FLOW_COUNT=`` / ``FLOW_PATH=`` protocol from stdout.  Returns a dict with
    at least the :data:`TAINT_FLOW_FIELDS`.  A runner error yields an
    unconfirmed verdict (``confirmed`` is ``None``) with the error recorded.
    """
    args: Dict[str, object] = {'cpg': cpg_path, 'source_file': source_file, 'source_line': source_line, 'sink_file': sink_file, 'sink_line': sink_line, 'timeout': JOERN_TIMEOUT}
    try:
        stdout = runner('flow', args)
    except Exception as exc:
        message = str(exc)
        if len(message) > 300:
            message = message[:300]
        return {'confirmed': None, 'path': [], 'hops': 0, 'query_time_s': 0.0, 'error': message}
    hops = 0
    paths: List[str] = []
    for raw in (stdout or '').splitlines():
        field_name = raw.strip()
        if field_name.startswith('FLOW_COUNT='):
            value = field_name[len('FLOW_COUNT='):].strip()
            try:
                hops = int(value)
            except ValueError:
                hops = 0
        elif field_name.startswith('FLOW_PATH='):
            paths.append(field_name[len('FLOW_PATH='):])
    return {'confirmed': hops > 0, 'path': paths[:_MAX_PATHS], 'hops': hops, 'query_time_s': 0.0}

def find_taint_sources(cpg_path: str, runner: JoernRunner) -> List[Dict[str, object]]:
    """Enumerate external-input taint sources in the CPG.

    Invokes the injected ``runner`` with the ``'sources'`` op and parses the
    ``SOURCE=file:line:function:code`` protocol from stdout.  Lines that do not
    follow the protocol are ignored; a non-numeric line becomes ``-1``.  A
    runner error yields an empty list.
    """
    args: Dict[str, object] = {'cpg': cpg_path, 'timeout': JOERN_TIMEOUT}
    try:
        stdout = runner('sources', args)
    except Exception:
        return []
    sources: List[Dict[str, object]] = []
    for raw in (stdout or '').splitlines():
        line = raw.strip()
        if not line.startswith('SOURCE='):
            continue
        payload = line[len('SOURCE='):]
        parts = payload.split(':', 3)
        if len(parts) < 3:
            continue
        file_name = parts[0]
        line_token = parts[1]
        function_name = parts[2]
        try:
            line_no = int(line_token)
        except ValueError:
            line_no = -1
        sources.append({'file': file_name, 'line': line_no, 'function': function_name, 'source_type': 'external_input'})
    return sources

def make_mock_joern(parse_out: str='', flow_out: str='', sources_out: str='') -> JoernRunner:
    """Build a fixed-output injected runner double.

    The returned callable dispatches on the op label, returning the matching
    scripted stdout regardless of the args mapping.  Unknown ops return ``''``.
    """
    by_op: Dict[str, str] = {'parse': parse_out, 'flow': flow_out, 'sources': sources_out}

    def _runner(op: str, args: Mapping[str, object]) -> str:
        return by_op.get(op, '')
    return _runner

def make_scripted_joern(script: Mapping[str, str]) -> JoernRunner:
    """Build an injected runner double from an op -> stdout mapping.

    Ops absent from ``script`` produce empty stdout.
    """
    mapping: Dict[str, str] = dict(script)

    def _runner(op: str, args: Mapping[str, object]) -> str:
        return mapping.get(op, '')
    return _runner
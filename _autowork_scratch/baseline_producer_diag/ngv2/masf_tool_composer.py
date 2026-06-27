"""Pure tool-composition shell for ngv2.

``make_tools`` turns an injected ``dispatch_table`` (``dict[str, Callable]``)
into a list of typed, agent-facing tool callables.  All live wiring -- the real
MCP tool functions and the gating ``bypass_set`` -- is injected at call time, so
this module performs NO network / LLM / subprocess work and imports nothing
outside the Python standard library.

The composition is deterministic: identical inputs always yield identical
wrappers, and ``_call_tool`` always returns a ``str`` (already-string results
pass through verbatim; everything else is serialized to JSON).
"""
from __future__ import annotations
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
_TOOL_PAIRS: List[Tuple[str, str]] = [('proxy_read_file', 'read_file'), ('proxy_write_file', 'write_file'), ('proxy_edit_file', 'edit_file'), ('proxy_bash', 'run_command'), ('proxy_commit', 'git_commit'), ('log_progress', 'log_progress'), ('complete_task', 'complete_task'), ('search_code', 'search_code'), ('index_repository', 'index_repo'), ('submit_finding', 'submit_finding')]
BUILTIN_TOOL_MAP: Dict[str, str] = {proxy: public for proxy, public in _TOOL_PAIRS}
TOOL_NAMES: Tuple[str, ...] = tuple(BUILTIN_TOOL_MAP.values())
_TOOL_PARAMS: Dict[str, List[Tuple[Any, ...]]] = {'read_file': [('file_path',), ('offset', 0), ('limit', 2000)], 'write_file': [('file_path',), ('content',)], 'edit_file': [('file_path',), ('old_string',), ('new_string',), ('replace_all', False)], 'run_command': [('command',), ('timeout', 120)], 'git_commit': [('message',), ('files',)], 'log_progress': [('task_id',), ('message',), ('phase', 'operation'), ('status', 'running')], 'complete_task': [('task_id',), ('summary',)], 'search_code': [('query',), ('repo_path', '')], 'index_repo': [('repo_path',)], 'submit_finding': [('task_id',), ('repo',), ('cwe',), ('severity',), ('confidence',), ('title',), ('description',), ('affected_file',), ('affected_lines',), ('evidence',), ('poc_status', 'none'), ('bounty_eligible', True)]}

def _make_signature(params: List[Tuple[Any, ...]]) -> inspect.Signature:
    """Build an ``inspect.Signature`` from a list of param descriptors."""
    sig_params: List[inspect.Parameter] = []
    for descriptor in params:
        field_name = descriptor[0]
        if len(descriptor) == 1:
            sig_params.append(inspect.Parameter(field_name, inspect.Parameter.POSITIONAL_OR_KEYWORD))
        else:
            sig_params.append(inspect.Parameter(field_name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=descriptor[1]))
    return inspect.Signature(sig_params)
_TOOL_SIGNATURES: Dict[str, inspect.Signature] = {name: _make_signature(params) for name, params in _TOOL_PARAMS.items()}
_GENERIC_SIGNATURE: inspect.Signature = inspect.Signature([inspect.Parameter('kwargs', inspect.Parameter.VAR_KEYWORD)])

def _call_tool(dispatch_table: Dict[str, Callable[..., Any]], bypass_set: Optional[Set[str]], session_id: str, tool_name: str, **kwargs: Any) -> str:
    """Invoke ``dispatch_table[tool_name]`` and normalize the outcome to ``str``.

    Behaviour:
      * Missing tool -> JSON ``{"error": ...}`` string.
      * ``session_id`` is injected only when the target accepts it and the
        caller did not already supply it.
      * Surplus kwargs are filtered to the target's parameters unless the target
        declares ``**kwargs`` (``VAR_KEYWORD``).
      * ``session_id`` is added to ``bypass_set`` before the call and discarded
        in a ``finally`` block, even on failure.
      * Non-string return values are serialized with ``json.dumps``; raised
        exceptions become JSON ``{"error": "<tool> failed: <msg>"}`` strings.
    """
    if tool_name not in dispatch_table:
        return json.dumps({'error': f"Tool '{tool_name}' not in dispatch table"})
    if bypass_set is None:
        bypass_set = set()
    target = dispatch_table[tool_name]
    try:
        signature = inspect.signature(target)
        params = signature.parameters
    except (TypeError, ValueError):
        params = {}
    has_var_keyword = any((param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()))
    call_kwargs = dict(kwargs)
    if 'session_id' in params and 'session_id' not in call_kwargs:
        call_kwargs['session_id'] = session_id
    if not has_var_keyword and params:
        call_kwargs = {k: v for k, v in call_kwargs.items() if k in params}
    try:
        bypass_set.add(session_id)
        result = target(**call_kwargs)
        if isinstance(result, str):
            return result
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({'error': f'{tool_name} failed: {exc}'})
    finally:
        bypass_set.discard(session_id)

def _build_wrapper(dispatch_table: Dict[str, Callable[..., Any]], bypass_set: Set[str], session_id: str, tool_name: str, public_name: str, display_name: str) -> Callable[..., str]:
    """Create a single agent-facing tool callable with an exact signature.

    The wrapper accepts ``*args, **kwargs``, binds them against the typed
    signature (without applying defaults so only supplied arguments are
    forwarded), and dispatches through :func:`_call_tool`.
    """
    signature = _TOOL_SIGNATURES.get(public_name, _GENERIC_SIGNATURE)

    def wrapper(*args: Any, **kwargs: Any) -> str:
        bound = signature.bind(*args, **kwargs)
        return _call_tool(dispatch_table, bypass_set, session_id, tool_name, **bound.arguments)
    wrapper.__name__ = display_name
    wrapper.__qualname__ = display_name
    wrapper.__signature__ = signature
    wrapper.__doc__ = f"Agent-facing tool '{display_name}' dispatching to '{tool_name}'."
    return wrapper

def make_tools(dispatch_table: Dict[str, Callable[..., Any]], session_id: str='', allowed_commands: Optional[Dict[str, Dict[str, Any]]]=None, bypass_set: Optional[Set[str]]=None) -> List[Callable[..., str]]:
    """Build a list of typed tool callables from ``dispatch_table``.

    Two modes:
      * ``allowed_commands is None`` -- build every entry of
        ``BUILTIN_TOOL_MAP`` whose proxy name is present in ``dispatch_table``,
        in map order, named by the public tool name.
      * ``allowed_commands`` provided -- build, in dict-iteration order, one tool
        per entry.  The dispatch name is ``cmd_spec.get("tool", short_name)`` and
        the wrapper is named by the ``short_name`` (the dict key).

    The shared ``bypass_set`` (a fresh local set when ``None``) is captured by
    every wrapper so gating state is consistent across the built tools.
    """
    if bypass_set is None:
        bypass_set = set()
    tools: List[Callable[..., str]] = []
    if allowed_commands is not None:
        for short_name, cmd_spec in allowed_commands.items():
            spec = cmd_spec or {}
            tool_name = spec.get('tool', short_name)
            if tool_name not in dispatch_table:
                continue
            public_name = BUILTIN_TOOL_MAP.get(tool_name, short_name)
            tools.append(_build_wrapper(dispatch_table, bypass_set, session_id, tool_name, public_name, short_name))
        return tools
    for proxy_name, public_name in BUILTIN_TOOL_MAP.items():
        if proxy_name not in dispatch_table:
            continue
        tools.append(_build_wrapper(dispatch_table, bypass_set, session_id, proxy_name, public_name, public_name))
    return tools
__all__ = ['make_tools', '_call_tool', 'BUILTIN_TOOL_MAP', 'TOOL_NAMES']
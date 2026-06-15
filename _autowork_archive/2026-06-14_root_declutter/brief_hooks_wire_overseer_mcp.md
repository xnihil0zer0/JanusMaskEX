---
interfaces: "overseer/turn_runner.py: make_seams(*, config, repo_root, state_dir, work_dir, timeout=DEFAULT_TIMEOUT_SEC) -> (runner, env_builder, jail_builder, stream_parser). Wire the operator's ~/.claude.json mcpServers into the overseer agent spawn: append mcp__<server> tokens to the agent --tools allowlist and bind each stdio server's host paths into the bwrap jail (ro; a --user-data-dir is rw). Single-symbol partial edit of make_seams only."
meta_task_type: data_model
---

# Title

overseer/turn_runner.py

# Why — the overseer cannot reach the operator's MCP tools

`overseer.turn_runner.make_seams` builds the four real seams that drive an
overseer chat turn. Its `jail_builder` seam rewrites the spawn argv and (when
the sandbox is on) wraps it in `harness.agent_jail.build_jail_argv`. Today it
grants the agent only the built-in `--tools` the driver computed and binds none
of the operator's MCP servers, so the overseer can never call the same MCP tools
the operator's Claude Code uses (playwright / noblegreed / codebase-memory, etc.).

This leaf gives the overseer the SAME MCP server set the operator has — read
live from `$HOME/.claude.json`'s `mcpServers` — by (1) appending an
`mcp__<server>` token to the agent's existing `--tools` allowlist for every
declared server, and (2) binding each stdio server's host paths into the jail so
the servers can actually spawn inside it. MCP is granted regardless of mode (no
per-mode rationing).

# Scope

Edit ONLY the existing function `make_seams` in `overseer/turn_runner.py` (a
single-symbol partial edit). Do NOT add any new top-level symbol, do NOT touch
`run_chat_turn`, `_build_overseer_env`, `_resolve_claude_binary`, the driver, or
any other file. All new logic is inline inside `make_seams` (it already does
local imports such as `from harness import agent_jail`). IMPL-only: the RED
oracle `tests/overseer/test_turn_runner_mcp.py` is a PRE-COMMITTED precondition —
author/edit NO test.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/turn_runner.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_turn_runner_mcp.py tests/overseer/test_turn_runner.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition; author/edit NO test.
- Single-symbol partial edit of the EXISTING `make_seams` only. Do NOT submit a
  whole-file rewrite.
- The task spec.non_goals MUST contain the literal word "integration".
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Inputs

`tests/overseer/test_turn_runner_mcp.py` (committed, RED) is authoritative. Its
structural facts:
- `make_seams` reads `mcpServers` from `$HOME/.claude.json`.
- For each server, the `jail_builder` seam appends `mcp__<server>` to the value
  following `--tools` in the argv (preserving the existing tools), but ONLY when
  the argv already contains `--tools` (the agy backend has none → skip).
- When the sandbox is on, `build_jail_argv` is called with `extra_ro` = each
  server's command dir, absolute arg dirs, and absolute env-value paths (e.g.
  `PYTHONPATH`), and `extra_rw` = each `--user-data-dir=` value. A path in
  `extra_rw` must NOT also appear in `extra_ro`.
- With no `mcpServers` (or no `.claude.json`) the argv is unchanged: no `mcp__`
  token, no extra bind.

# Implementation notes (the exact target function)

PARTIAL EDIT of the EXISTING `make_seams` ONLY (single top-level symbol). Replace
its body with the version below. `env_builder` and `runner` stay byte-for-byte;
only a pre-compute block is added before `jail_builder` and `jail_builder`'s body
gains the token-append + bind wiring. Add `import json` as a LOCAL import inside
`make_seams` (next to the existing `from harness import agent_jail`) — do NOT
edit the module-level import block.

```python
def make_seams(*, config: Dict[str, Any], repo_root: Path, state_dir: Path,
               work_dir: Path, timeout: int = DEFAULT_TIMEOUT_SEC
               ) -> Tuple[Callable, Callable, Callable, Any]:
    """Construct the four real seams for ``overseer.driver.run_turn``."""
    from harness import agent_jail
    from harness.agent_streamer import ClaudeStreamParser
    import json

    claude_bin = _resolve_claude_binary(config, repo_root)

    # Give the overseer the SAME MCP servers the operator's Claude Code uses:
    # read $HOME/.claude.json's mcpServers, expose each as an mcp__<name> tool
    # token, and collect the host paths each stdio server needs bound into the
    # jail (command/arg/env dirs read-only; a --user-data-dir read-write).
    home = os.environ.get('HOME', '')
    mcp_servers: Dict[str, Any] = {}
    try:
        with open(os.path.join(home, '.claude.json'), 'r', encoding='utf-8') as _fh:
            _data = json.load(_fh)
        if isinstance(_data, dict) and isinstance(_data.get('mcpServers'), dict):
            mcp_servers = _data['mcpServers']
    except (OSError, ValueError):
        mcp_servers = {}
    mcp_tokens = ['mcp__' + name for name in mcp_servers]
    mcp_ro: set = set()
    mcp_rw: set = set()
    for _spec in mcp_servers.values():
        if not isinstance(_spec, dict):
            continue
        _cmd = _spec.get('command')
        if isinstance(_cmd, str) and os.path.isabs(_cmd):
            mcp_ro.add(os.path.dirname(_cmd))
        for _arg in _spec.get('args') or []:
            if not isinstance(_arg, str):
                continue
            if _arg.startswith('--user-data-dir='):
                _val = _arg.split('=', 1)[1]
                if _val:
                    mcp_rw.add(_val)
            elif os.path.isabs(_arg):
                mcp_ro.add(_arg if os.path.isdir(_arg) else os.path.dirname(_arg))
        for _val in (_spec.get('env') or {}).values():
            if not isinstance(_val, str):
                continue
            for _part in _val.split(os.pathsep):
                if _part and os.path.isabs(_part) and os.path.exists(_part):
                    mcp_ro.add(_part)
    if home:
        _cache = os.path.join(home, '.cache', 'ms-playwright')
        if os.path.isdir(_cache):
            mcp_ro.add(_cache)
    mcp_ro -= mcp_rw
    mcp_ro_list = sorted(mcp_ro)
    mcp_rw_list = sorted(mcp_rw)

    def jail_builder(argv: Sequence[str], **kw: Any) -> List[str]:
        inner = list(argv)
        if inner and inner[0] == 'claude':
            inner[0] = claude_bin
        # Grant the operator's MCP tools regardless of mode by extending the
        # agent's existing --tools allowlist (claude backend always sets it;
        # the agy backend has none, so MCP tokens are skipped there).
        if mcp_tokens and '--tools' in inner:
            _i = inner.index('--tools')
            if _i + 1 < len(inner):
                _existing = [t for t in inner[_i + 1].split(',') if t]
                for _tok in mcp_tokens:
                    if _tok not in _existing:
                        _existing.append(_tok)
                inner[_i + 1] = ','.join(_existing)
        if agent_jail.sandbox_enabled(config) and agent_jail.bwrap_available():
            for _d in mcp_rw_list:  # bwrap binds fail on a missing source
                try:
                    os.makedirs(_d, exist_ok=True)
                except OSError:
                    pass
            return agent_jail.build_jail_argv(
                inner, repo_root=repo_root, work_dir=work_dir, state_dir=state_dir,
                bind_credentials=True, extra_ro=mcp_ro_list, extra_rw=mcp_rw_list,
            )
        return inner

    def env_builder(conversation: Dict[str, Any], **kw: Any) -> Dict[str, str]:
        return _build_overseer_env(repo_root, work_dir, state_dir)

    def runner(cmd: Sequence[str], *, env: Dict[str, str], stdin: str, **kw: Any) -> List[str]:
        work_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            list(cmd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, start_new_session=True,
            cwd=str(work_dir),
        )
        try:
            out, _err = proc.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _err = proc.communicate()
        return (out or '').splitlines()

    return runner, env_builder, jail_builder, ClaudeStreamParser('claude')
```

# Non-Goals

INTEGRATION is out of scope beyond `make_seams`: do NOT add new top-level
symbols, a new module, or a new config file; do NOT touch `run_chat_turn`, the
driver, the mode registry, or any other file. Do NOT pass `--strict-mcp-config`
or `--mcp-config` (the jail already binds a copy of `$HOME/.claude.json`, so
claude loads the servers by default — only the tool allowlist and the jail binds
are missing). Do NOT author or edit any test; the oracle is pre-committed.

# Edge Cases

- A server with an absolute `command` → its command dir is a read-only bind.
- A server with an absolute script arg and a `PYTHONPATH` env → both are
  read-only binds.
- A `--user-data-dir=<p>` arg → `<p>` is a read-WRITE bind and is NOT also a
  read-only bind.
- The argv has no `--tools` (agy backend) → no MCP token is injected.
- No `mcpServers` / no `.claude.json` / unreadable `.claude.json` → argv is
  unchanged: no token, no extra bind (must not raise).

# Deliverables

`overseer/turn_runner.py` with `make_seams` wiring the operator's MCP servers
into the spawn (tokens + jail binds), GREEN under
`python -m pytest tests/overseer/test_turn_runner_mcp.py tests/overseer/test_turn_runner.py -q`,
with no new top-level symbol and no other file touched.

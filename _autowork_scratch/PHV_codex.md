# Adversarial verify: codex wiring (commit 1e41ecb)

## 1. config.yaml agents.codex — CONFIRMED (functionally; NOT a single literal)
Lines 35-44. Args are a YAML LIST, not the single string the handoff quoted:
```
codex:
  args: [exec, --dangerously-bypass-approvals-and-sandbox, --skip-git-repo-check, --color, never, -p, '']
  command: /home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/codex
```
Note `-p` is followed by '' (empty). orchestrator strips `-p <next>` (line 466-467) before STDIN routing → the empty positional is removed. OK.

## 2. orchestrator.py:459 _is_agy — CONFIRMED
`_is_agy = os.path.basename(config['agents'][agent]['command']) in ('agy', 'codex')`
Generalized. codex basename = "codex" → routed through STDIN/no-write/fenced-block path. OK.

## 3. synthesis.active_agents — CONFIRMED [claude, gemini] (lines 113-115). codex selectable, not default. OK.

## 4. _extract_python_block (test_author.py:150-175) — BUG / FRAGILE for codex
Logic: FIRST-MATCH only. Iterates lines; first line starting with ``` opens block,
next ``` closes it via `break`. Returns ONLY the first fenced block.
- If codex prints a BANNER then the SAME ```python block TWICE: extractor grabs the
  FIRST fenced block. IF that first block is the real code → accidentally OK.
- BUT: codex `exec` typically prefixes a status/banner line and may wrap output; any
  PROSE line beginning with ``` (or a non-python fence in the banner, e.g. a ```text
  preamble) becomes the "first block" and the real python is dropped.
- No `:::`/language-tag filtering: a bare ``` opens the block regardless of language.
- No selection by longest/valid-AST among multiple blocks; the double-print is simply
  ignored (2nd block unreachable after break) — harmless ONLY if block #1 == real code.
- Fallback (ast.parse whole text) FAILS once any banner/2nd-fence is present (not valid py).
VERDICT on #4: extraction is NOT robust to codex's banner+double-block shape. It works
ONLY if the very first ``` fence in stdout wraps the complete, correct python. A banner
fence or leading prose-fence silently yields wrong/empty submission → gate reject, no crash.
No codex-specific stripping exists anywhere (grep confirmed; only model_backends/webui
registry entries, no output normalization).

## 5. claude_fallback special-case (orchestrator.py:1188,1196,1220,1227) — CONFIRMED SAFE
Guard is exact slot-name equality: `if 'claude' == agent_a` / `'claude' == agent_b`.
agent name "codex" != "claude" → fallback NEVER misfires for codex. OK.

## Incompleteness flags
- model_backends.py registers codex as kind 'codex_cli' but config.yaml agents.codex is a
  plain command/args block consumed by orchestrator directly — two parallel definitions;
  the active synthesis path uses config.yaml, not the backend registry.
- Empty `-p ''` arg is dead (stripped); harmless but sloppy.

VERDICT: codex wiring CONFIG/ROUTING CORRECT, OUTPUT-PARSING BUGGY (first-match extractor
not hardened for codex banner+double-block) → overall INCOMPLETE/BUGGY.

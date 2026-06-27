"""ngv2/claude_cli_client.py -- claude-CLI-backed ``complete`` seam.

Production promotion of the proven e2e scaffolding ``_e2e_run/claude_cli_client``.
claude is used ONLY for the dual-agent PoC stage (write_poc + repair_poc); every
other hunt phase defaults to agy.

claude is invoked headless and OAuth/subscription-billed (never an API key):
``claude -p --model <model>`` with the prompt on stdin and plain-text stdout.
The model edge is the :data:`ngv2.llm_client.CompleteFn` contract::

    complete(messages, *, model=None, max_tokens=4096, system=None) -> str

The subprocess runner is an injected ``run=`` seam (defaulting to
``subprocess.run``) so unit tests stay hermetic. The returned callable carries a
``backend`` attribute (``'claude'``) so ``ngv2.workers._runner.build_seams`` can
assert per-phase selection offline.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List, Optional

CLAUDE_BIN = "claude"
DEFAULT_MODEL = "opus"
DEFAULT_TIMEOUT_S = 300


class ClaudeCLIError(RuntimeError):
    """Raised on claude CLI non-zero exit, empty output, timeout, or spawn failure."""


def _flatten(messages: List[Dict[str, Any]], system: Optional[str]) -> str:
    parts: List[str] = []
    if system:
        parts.append(system)
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                (block.get("text", "") if isinstance(block, dict) else str(block))
                for block in content
            )
        role = message.get("role", "user")
        if role and role != "user":
            parts.append("[{0}]\n{1}".format(role, content))
        else:
            parts.append(str(content))
    return "\n\n".join(parts)


_FENCE_RE = re.compile(r"```(?:python|py|javascript|js|node)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    """Recover clean source from a model reply (first fenced block, else prose-trim)."""
    if not text:
        return text
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip("\n") + "\n"
    lines = [line for line in text.splitlines() if line.strip() != "```"]
    code_starts = ("import ", "from ", "#!", "sys.", "const ", "require(",
                   "// ", "#", "def ", "class ", "os.", "payload", "target_")
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(code_starts):
            return "\n".join(lines[index:]).strip("\n") + "\n"
    return text


def make_claude_cli_complete(*, model: str = DEFAULT_MODEL,
                             timeout_s: int = DEFAULT_TIMEOUT_S, tag: str = "",
                             run: Optional[Any] = None):
    """Return a ``complete`` callable that shells out to the headless claude CLI."""
    runner = run or subprocess.run
    resolved_default = model or DEFAULT_MODEL

    def complete(messages: List[Dict[str, Any]], *, model: Optional[str] = None,
                 max_tokens: int = 4096, system: Optional[str] = None) -> str:
        prompt = _flatten(messages, system)
        use_model = model or resolved_default
        cmd = [CLAUDE_BIN, "-p", "--model", use_model]
        try:
            proc = runner(cmd, input=prompt, capture_output=True, text=True,
                          timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCLIError(
                "claude CLI timed out after {0}s".format(timeout_s)
            ) from exc
        except OSError as exc:
            raise ClaudeCLIError("claude CLI spawn failed: {0}".format(exc)) from exc
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise ClaudeCLIError(
                "claude CLI exited {0}: {1}".format(proc.returncode, (err or out)[-400:])
            )
        if not out:
            raise ClaudeCLIError("claude CLI returned empty output")
        return _extract_code(out)

    complete.backend = "claude"
    return complete

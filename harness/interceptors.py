"""Python-native interceptors for JanusMask.

By moving verification from external CLI hook binaries into Python-native runtime
interceptors, we bypass shell wrapper overhead and unify validation logic.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from services.neurosymbolic.ast_verifier import ASTVerifier
from services.neurosymbolic.bash_validator import validate_command, PermissionMode

logger = logging.getLogger("janusmask.interceptors")


class BaseInterceptor:
    """Base class for all orchestrator runtime interceptors."""

    def pre_invocation(self, agent: str, prompt: str, env: dict) -> None:
        """Called before spawning the agent subprocess."""
        pass

    def pre_tool_use(self, agent: str, tool_name: str, tool_input: dict) -> dict | None:
        """Called before a tool is executed. Returns a decision dict if intercepted."""
        pass

    def post_tool_use(self, agent: str, tool_name: str, result: dict) -> dict | None:
        """Called after a tool is executed. Returns a decision dict if intercepted."""
        pass


class ASTVerificationInterceptor(BaseInterceptor):
    """Intercepts file writes and submissions to enforce AST validation rules."""

    def pre_tool_use(self, agent: str, tool_name: str, tool_input: dict) -> dict | None:
        if tool_name not in ("Write", "submit_code"):
            return None

        code = tool_input.get("code") or tool_input.get("content")
        path = tool_input.get("path") or ""

        if path and not path.endswith(".py"):
            return None

        if not code or not isinstance(code, str):
            return None

        verifier = ASTVerifier()
        result = verifier.verify(code)

        if result.has_errors():
            bullets = [f"- L{v.line}: [{v.rule}] {v.message}" for v in result.violations if v.severity == "ERROR"]
            reason = "AST validation failed:\n" + "\n".join(bullets)
            return {"decision": "deny", "reason": reason}

        if result.has_warnings():
            bullets = [f"- L{v.line}: [{v.rule}] {v.message}" for v in result.violations if v.severity == "WARNING"]
            warns = "\n".join(bullets)
            return {
                "decision": "allow",
                "additionalContext": f"AST warnings (non-blocking):\n{warns}",
                "systemMessage": f"AST warnings (non-blocking):\n{warns}"
            }

        return None


class BashSafetyInterceptor(BaseInterceptor):
    """Intercepts bash commands to block unsafe operations or provide warnings."""

    def pre_tool_use(self, agent: str, tool_name: str, tool_input: dict) -> dict | None:
        if tool_name not in ("Bash", "execute_command", "mcp__janusmask__execute"):
            return None

        command = tool_input.get("command") or tool_input.get("cmd")
        if not command or not isinstance(command, str):
            # Check if nested inside args JSON
            args_str = tool_input.get("args")
            if args_str and isinstance(args_str, str):
                try:
                    import json
                    args = json.loads(args_str)
                    if isinstance(args, dict):
                        command = args.get("command") or args.get("cmd")
                except Exception:
                    pass

        if not command or not isinstance(command, str):
            return None

        workspace = Path(os.environ.get("JANUSMASK_PROJECT_DIR", "/home/xnihil0zer0/NobleJanus"))
        mode_str = os.environ.get("JANUSMASK_PERMISSION_MODE", "WORKSPACE_WRITE")

        try:
            mode = PermissionMode[mode_str]
        except KeyError:
            mode = PermissionMode.WORKSPACE_WRITE

        res = validate_command(command, mode, workspace)
        if res.get("result") == "block":
            return {"decision": "deny", "reason": res.get("reason", "Command blocked by safety policy.")}
        elif res.get("result") == "warn":
            msg = res.get("message", "Suspicious command pattern.")
            return {
                "decision": "allow",
                "additionalContext": f"Warning: {msg}",
                "systemMessage": f"Warning: {msg}"
            }

        return None


class InterceptorRegistry:
    """Registry to manage and execute active runtime interceptors."""

    def __init__(self) -> None:
        self._interceptors: list[BaseInterceptor] = []

    def register(self, interceptor: BaseInterceptor) -> None:
        self._interceptors.append(interceptor)

    def pre_invocation(self, agent: str, prompt: str, env: dict) -> None:
        for inter in self._interceptors:
            try:
                inter.pre_invocation(agent, prompt, env)
            except Exception as exc:
                logger.error("Error in pre_invocation interceptor %s: %s", type(inter).__name__, exc, exc_info=True)

    def pre_tool_use(self, agent: str, tool_name: str, tool_input: dict) -> dict | None:
        for inter in self._interceptors:
            try:
                res = inter.pre_tool_use(agent, tool_name, tool_input)
                if res is not None:
                    return res
            except Exception as exc:
                logger.error("Error in pre_tool_use interceptor %s: %s", type(inter).__name__, exc, exc_info=True)
        return None

    def post_tool_use(self, agent: str, tool_name: str, result: dict) -> dict | None:
        for inter in self._interceptors:
            try:
                res = inter.post_tool_use(agent, tool_name, result)
                if res is not None:
                    return res
            except Exception as exc:
                logger.error("Error in post_tool_use interceptor %s: %s", type(inter).__name__, exc, exc_info=True)
        return None


# Global registry instance
registry = InterceptorRegistry()

# Register built-in interceptors
registry.register(ASTVerificationInterceptor())
registry.register(BashSafetyInterceptor())

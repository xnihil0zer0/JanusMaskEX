import os
import pytest
from unittest.mock import patch

from harness.interceptors import ASTVerificationInterceptor, BashSafetyInterceptor


def test_ast_verification_interceptor():
    interceptor = ASTVerificationInterceptor()

    # 1. Non-Python writes should bypass validation (returns None)
    res = interceptor.pre_tool_use("claude", "Write", {"code": "invalid syntax text", "path": "notes.md"})
    assert res is None

    # 2. Python write with syntax/AST errors should block (returns deny decision)
    res = interceptor.pre_tool_use("claude", "Write", {"code": "def foo(", "path": "helper.py"})
    assert res is not None
    assert res["decision"] == "deny"
    assert "AST validation failed" in res["reason"]

    # 3. Python write with bare except should block
    res = interceptor.pre_tool_use("claude", "Write", {"code": "try:\n    pass\nexcept:\n    pass", "path": "helper.py"})
    assert res is not None
    assert res["decision"] == "deny"
    assert "bare_except" in res["reason"]

    # 4. Safe Python write should allow (returns None)
    res = interceptor.pre_tool_use("claude", "Write", {"code": "def hello():\n    return 'world'", "path": "helper.py"})
    assert res is None


def test_bash_safety_interceptor():
    interceptor = BashSafetyInterceptor()

    # Mock project directory and permission mode env variables
    with patch.dict(os.environ, {"JANUSMASK_PROJECT_DIR": "/home/xnihil0zer0/NobleJanus", "JANUSMASK_PERMISSION_MODE": "WORKSPACE_WRITE"}):
        # 1. Safe command should allow (returns None)
        res = interceptor.pre_tool_use("claude", "Bash", {"command": "ls -la"})
        assert res is None

        # 2. Destructive command should warn (returns allow with warning in additionalContext)
        res = interceptor.pre_tool_use("claude", "Bash", {"command": "rm -rf *"})
        assert res is not None
        assert res["decision"] == "allow"
        assert "Warning:" in res["additionalContext"]

    with patch.dict(os.environ, {"JANUSMASK_PROJECT_DIR": "/home/xnihil0zer0/NobleJanus", "JANUSMASK_PERMISSION_MODE": "READ_ONLY"}):
        # 3. Write command in READ_ONLY should block (returns deny)
        res = interceptor.pre_tool_use("claude", "Bash", {"command": "rm file.txt"})
        assert res is not None
        assert res["decision"] == "deny"
        assert "not allowed" in res["reason"]

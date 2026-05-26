import pytest
from pathlib import Path
from services.neurosymbolic.bash_validator import (
    validate_command,
    PermissionMode,
    classify_command,
    CommandIntent,
)


def test_validate_read_only():
    workspace = Path("/home/xnihil0zer0/NobleJanus")
    # Read-only safe commands
    assert validate_command("ls -la", PermissionMode.READ_ONLY, workspace)["result"] == "allow"
    assert validate_command("git diff", PermissionMode.READ_ONLY, workspace)["result"] == "allow"

    # Blocks write commands
    assert validate_command("rm file.txt", PermissionMode.READ_ONLY, workspace)["result"] == "block"
    assert validate_command("mkdir new_dir", PermissionMode.READ_ONLY, workspace)["result"] == "block"

    # Blocks write redirection
    assert validate_command("echo hello > out.txt", PermissionMode.READ_ONLY, workspace)["result"] == "block"


def test_destructive_commands():
    workspace = Path("/home/xnihil0zer0/NobleJanus")
    # Inherently destructive warning
    assert validate_command("rm -rf /", PermissionMode.WORKSPACE_WRITE, workspace)["result"] == "warn"
    assert validate_command("shred file.txt", PermissionMode.WORKSPACE_WRITE, workspace)["result"] == "warn"


def test_validate_paths():
    workspace = Path("/home/xnihil0zer0/NobleJanus")
    # directory traversal warn
    assert validate_command("cat ../outside.txt", PermissionMode.WORKSPACE_WRITE, workspace)["result"] == "warn"

    # git clone to /tmp/ block
    assert validate_command("git clone url /tmp/clone", PermissionMode.WORKSPACE_WRITE, workspace)["result"] == "block"


def test_classify_command():
    assert classify_command("ls -la") == CommandIntent.READ_ONLY
    assert classify_command("rm -rf file.txt") == CommandIntent.DESTRUCTIVE
    assert classify_command("cp a b") == CommandIntent.WRITE
    assert classify_command("curl google.com") == CommandIntent.NETWORK
    assert classify_command("kill -9 1234") == CommandIntent.PROCESS_MANAGEMENT
    assert classify_command("pip install mcp") == CommandIntent.PACKAGE_MANAGEMENT
    assert classify_command("sudo rm file") == CommandIntent.SYSTEM_ADMIN

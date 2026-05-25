"""Auto-commit message formatter for orchestrator integration."""


def format_auto_commit_message(task_id: str) -> str:
    """Return a deterministic commit message for auto-committed task output.
    
    Template:
    Integrate validated code for {task_id}
    
    Auto-committed via orchestrator after passing dual-agent
    AST generation, differential fuzzing, and cross-examination.
    
    Pure string formatting; never raises.
    
    Args:
        task_id: The task identifier to include in the commit message.
    
    Returns:
        A deterministic multi-line commit message string.
    """
    return f"""Integrate validated code for {task_id}

Auto-committed via orchestrator after passing dual-agent
AST generation, differential fuzzing, and cross-examination."""


if __name__ == "__main__":
    import pytest
    pytest.main(["-v", __file__])


class TestFormatAutoCommitMessage:
    """Tests for format_auto_commit_message function."""

    def test_basic_task_id(self):
        """Test with a standard task ID."""
        result = format_auto_commit_message("COMMIT-MSG-FMT-001")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_message_contains_task_id(self):
        """Test that the message contains the provided task_id."""
        task_id = "GIT-COMMIT-001"
        result = format_auto_commit_message(task_id)
        assert task_id in result

    def test_message_contains_auto_commit_text(self):
        """Test that the message contains auto-commit context text."""
        result = format_auto_commit_message("TEST-001")
        assert "Auto-committed via orchestrator" in result

    def test_message_contains_dual_agent_text(self):
        """Test that the message contains dual-agent validation text."""
        result = format_auto_commit_message("TEST-001")
        assert "dual-agent" in result
        assert "AST generation" in result
        assert "differential fuzzing" in result
        assert "cross-examination" in result

    def test_empty_task_id(self):
        """Test with empty task_id string."""
        result = format_auto_commit_message("")
        assert isinstance(result, str)
        assert "Integrate validated code for" in result
        assert len(result) > 0

    def test_deterministic_same_input_same_output(self):
        """Test that the same input always produces the same output."""
        task_id = "PS-001-reviewed"
        result1 = format_auto_commit_message(task_id)
        result2 = format_auto_commit_message(task_id)
        result3 = format_auto_commit_message(task_id)
        assert result1 == result2
        assert result2 == result3

    def test_multiline_format_is_valid(self):
        """Test that the returned message has the correct multiline structure."""
        result = format_auto_commit_message("TEST-001")
        lines = result.split("\n")
        # Should have at least 4 lines: subject, blank, and 2 body lines
        assert len(lines) >= 4
        # First line should contain the task_id
        assert "Integrate validated code for" in lines[0]
        # Second line should be blank
        assert lines[1] == ""
        # Remaining lines should contain the body
        body = "\n".join(lines[2:])
        assert "Auto-committed via orchestrator" in body

    def test_pure_no_side_effects(self):
        """Test that function is pure (no global state modifications)."""
        task_id = "PURE-TEST-001"
        # Call multiple times and verify no side effects
        for i in range(3):
            result = format_auto_commit_message(task_id)
            # Verify result is consistent
            assert "Integrate validated code for PURE-TEST-001" in result

    def test_special_characters_preserved(self):
        """Test that special characters in task_id are preserved as-is."""
        test_cases = [
            "TASK-001-with-dashes",
            "TASK.001.with.dots",
            "TASK/001/with/slashes",
            "TASK_001_with_underscores",
        ]
        for task_id in test_cases:
            result = format_auto_commit_message(task_id)
            # Task ID should appear exactly as provided (no normalization)
            assert task_id in result
            # The subject line should start with the intro text and contain the task_id
            assert result.startswith(f"Integrate validated code for {task_id}")

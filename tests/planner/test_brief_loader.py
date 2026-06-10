import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from harness.planner import load_brief, PlanningBrief, BriefValidationError, BriefTooLargeError


@pytest.fixture
def fixtures_dir(tmp_path):
    d = tmp_path / "briefs"
    d.mkdir()
    
    # valid.md
    (d / "valid.md").write_text("""---
title: My Project
---
# Scope
Scope details here.

# Non-Goals
Things not to do.

# Inputs
Some inputs.

# Deliverables
Some deliverables.
""", encoding="utf-8")

    # valid_all_md.md
    (d / "valid_all_md.md").write_text("""
# Title
My Project 2

# Scope
Scope 2

# Non-Goals
Non 2

# Inputs
In 2

# Deliverables
Out 2
""", encoding="utf-8")

    # missing_section.md
    (d / "missing_section.md").write_text("""---
title: Missing Scope
---
# Non-Goals
No goals

# Inputs
In

# Deliverables
Out
""", encoding="utf-8")

    # empty_section.md
    (d / "empty_section.md").write_text("""---
title: Empty Scope
---
# Scope

# Non-Goals
No goals

# Inputs
In

# Deliverables
Out
""", encoding="utf-8")

    # duplicate_keys.md
    (d / "duplicate_keys.md").write_text("""---
title: One
title: Two
---
# Scope
Scope
# Non-Goals
Non
# Inputs
In
# Deliverables
Out
""", encoding="utf-8")

    # non_utf8.bin
    (d / "non_utf8.bin").write_bytes(b"\xff\xfe\x00\x00")

    # too_large.md
    (d / "too_large.md").write_text("a" * 300000, encoding="utf-8")

    # symlink_loop.md
    link1 = d / "link1.md"
    link2 = d / "link2.md"
    os.symlink("link2.md", link1)
    os.symlink("link1.md", link2)

    return d


def test_load_brief_happy_path(fixtures_dir):
    brief = load_brief(fixtures_dir / "valid.md")
    assert isinstance(brief, PlanningBrief)
    assert brief.title == "My Project"
    assert "Scope details here." in brief.scope
    assert len(brief.sha256) == 64

def test_load_brief_all_markdown_happy_path(fixtures_dir):
    brief = load_brief(fixtures_dir / "valid_all_md.md")
    assert brief.title == "My Project 2"
    assert brief.scope == "Scope 2"

def test_load_brief_missing_section_raises(fixtures_dir):
    with pytest.raises(BriefValidationError) as exc_info:
        load_brief(fixtures_dir / "missing_section.md")
    assert "scope" in exc_info.value.missing

def test_load_brief_empty_section_raises(fixtures_dir):
    with pytest.raises(BriefValidationError) as exc_info:
        load_brief(fixtures_dir / "empty_section.md")
    assert "scope" in exc_info.value.empty

def test_load_brief_too_large(fixtures_dir):
    with pytest.raises(BriefTooLargeError) as exc_info:
        load_brief(fixtures_dir / "too_large.md", max_bytes=256 * 1024)
    assert exc_info.value.actual_bytes > 256 * 1024

def test_to_agent_prompt_is_deterministic(fixtures_dir):
    brief_a = load_brief(fixtures_dir / "valid.md")
    brief_b = load_brief(fixtures_dir / "valid.md")
    assert brief_a.to_agent_prompt() == brief_b.to_agent_prompt()

def test_load_brief_non_utf8_raises(fixtures_dir):
    with pytest.raises(BriefValidationError):
        load_brief(fixtures_dir / "non_utf8.bin")

def test_brief_loader_cli_exit_codes(fixtures_dir):
    # Valid brief
    valid_res = subprocess.run(
        [sys.executable, "-m", "harness.planner.brief_loader", str(fixtures_dir / "valid.md")],
        capture_output=True, text=True
    )
    assert valid_res.returncode == 0
    assert "Title: My Project" in valid_res.stdout

    # Broken brief
    broken_res = subprocess.run(
        [sys.executable, "-m", "harness.planner.brief_loader", str(fixtures_dir / "missing_section.md")],
        capture_output=True, text=True
    )
    assert broken_res.returncode != 0
    assert "Validation failed" in broken_res.stderr
    assert "Missing sections" in broken_res.stderr

import tempfile

@given(st.text())
def test_sha256_line_ending_invariant(text):
    # Create valid brief content with given text as body
    # We replace any occurrences of our section headers to avoid breaking parsing
    safe_text = text.replace("# Scope", "Scope").replace("# Non-Goals", "Non").replace("# Inputs", "In").replace("# Deliverables", "Out")

    base_content = f"""---
title: Title
---
# Scope
{safe_text}
# Non-Goals
x
# Inputs
x
# Deliverables
x
"""
    # Canonicalize to \n-only FIRST so the variants below are the same logical
    # content under different line endings. (Splitting a string that still
    # contains a bare \r and joining with \r\n would change the logical line
    # structure — e.g. '0\r\n' vs '0\r\r\n' — making the property unsatisfiable.)
    lf_content = base_content.replace("\r\n", "\n").replace("\r", "\n")
    crlf_content = "\r\n".join(lf_content.split("\n"))
    cr_content = "\r".join(lf_content.split("\n"))

    with tempfile.TemporaryDirectory() as td:
        lf_file = Path(td) / "lf.md"
        crlf_file = Path(td) / "crlf.md"
        cr_file = Path(td) / "cr.md"

        lf_file.write_bytes(lf_content.encode('utf-8'))
        crlf_file.write_bytes(crlf_content.encode('utf-8'))
        cr_file.write_bytes(cr_content.encode('utf-8'))

        # It's possible the random text creates invalid sections or something, so catch validation errors and skip if so.
        try:
            brief_lf = load_brief(lf_file)
            brief_crlf = load_brief(crlf_file)
            brief_cr = load_brief(cr_file)
            assert brief_lf.sha256 == brief_crlf.sha256
            assert brief_lf.sha256 == brief_cr.sha256
        except BriefValidationError:
            pass


def test_symlink_loop_rejected(fixtures_dir):
    with pytest.raises(BriefValidationError) as exc:
        load_brief(fixtures_dir / "link1.md")
    assert "Symlink loop" in str(exc.value)

def test_duplicate_frontmatter_keys_rejected(fixtures_dir):
    with pytest.raises(BriefValidationError) as exc:
        load_brief(fixtures_dir / "duplicate_keys.md")
    assert "Duplicate keys in front-matter" in str(exc.value)

def test_file_not_found(fixtures_dir):
    with pytest.raises(FileNotFoundError):
        load_brief(fixtures_dir / "does_not_exist.md")


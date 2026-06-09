"""RED oracle for wire-up-sweep leaf 3: advisory MCP cross-check.

The static AST sweep cannot see wiring the runtime resolves dynamically
(config-string entrypoints, reflective dispatch). The codebase-memory-mcp graph
sees some of it -- but it is proven unreliable BOTH ways, so it is ADVISORY
ONLY: for each static ORPHAN / ORPHAN_CLUSTER candidate, ``mcp_crosscheck``
queries the MCP for inbound usages via an INJECTED callable and RAISES a
disagreement note when the MCP shows inbound edges. It never flips a verdict and
never gates. The injected seam means the oracle drives it with a stub -- no live
MCP call. RED until ``mcp_crosscheck`` exists.
"""
from __future__ import annotations

from harness.wire_up import SweepReport, mcp_crosscheck


def _report() -> SweepReport:
    return SweepReport(
        wired=["a.py"],
        config_wired=[],
        orphan_cluster=["c.py"],
        orphan=["b.py"],
        roots=["root.py"],
    )


def test_disagreement_raised_for_mcp_inbound():
    report = _report()
    queried: list[str] = []

    def stub(module_rel: str) -> int:
        queried.append(module_rel)
        return 3 if module_rel == "b.py" else 0

    notes = mcp_crosscheck(report, stub)
    # A disagreement is raised for the orphan the MCP shows inbound usages for.
    assert any("b.py" in n for n in notes)
    assert any("3" in n for n in notes), "the note should surface the inbound count"
    # No disagreement for the cluster member the MCP agrees is unused.
    assert not any("c.py" in n for n in notes)
    # Both orphan/cluster candidates were queried; the WIRED module was NOT.
    assert set(queried) == {"b.py", "c.py"}
    assert "a.py" not in queried


def test_verdict_is_never_flipped():
    # Advisory only: even when the MCP claims inbound usages for everything, the
    # SweepReport's class lists are unchanged.
    report = _report()
    before = report.to_dict()
    mcp_crosscheck(report, lambda module_rel: 5)
    assert report.to_dict() == before


def test_no_disagreements_when_mcp_agrees():
    report = SweepReport(wired=[], config_wired=[], orphan_cluster=[], orphan=["b.py"], roots=[])
    notes = mcp_crosscheck(report, lambda module_rel: 0)
    assert notes == []


def test_notes_are_deterministic():
    report = _report()
    a = mcp_crosscheck(report, lambda module_rel: 1)
    b = mcp_crosscheck(report, lambda module_rel: 1)
    assert a == b

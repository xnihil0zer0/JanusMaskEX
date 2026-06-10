"""Adversarial battery for HOOK-51 equivalence comparator.

Targets the load_jsonl / load_shadow_log / load_mcp_audit / shadow_diff_key /
mcp_diff_key / compare / emit_report / run_comparison / main pipeline in
harness.hooks_equivalence. Each attack is a plausible real-world fault or
byzantine input the comparator must handle without crashing and without
mis-classifying match vs divergence.

Covers the augmented plan §5 P5 "shadow-write omits timestamp" and
"induced rate-limit divergence" attack rows, plus writer-side mutation
tests that make sure the decision-vocabulary collapse is the actual
load-bearing behaviour rather than something silently broken.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import os
import pathlib
import random
import time

import pytest

from harness import hooks_equivalence as he


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _shadow(tool: str, ah: str, dec: str, **extra) -> dict:
    row = {"tool_name": tool, "args_hash": ah, "policy_decision": dec, "policy_reason": ""}
    row.update(extra)
    return row


def _mcp(tool: str, ah: str, outcome: str, **extra) -> dict:
    row = {"tool": tool, "digest": ah, "outcome": outcome}
    row.update(extra)
    return row


# -- scale + performance ----------------------------------------------------


def test_adv_large_log_comparison_is_fast():
    """10k identical rows on each side must compare well under the O(n²) wall.

    Guards against accidentally O(n²) implementation of _multiset_diff. The
    comparator runs in-process in ~0.2s; the threshold is generous (10x) on
    purpose — a real O(n²) regression on 10k rows is seconds-to-minutes, so a
    wide bound still catches it while tolerating wall-clock jitter under heavy
    full-suite load (the assertion is not a microbenchmark).
    """
    shadow = [_shadow("Write", f"h{i}", "allow") for i in range(10_000)]
    mcp = [_mcp("Write", f"h{i}", "allow") for i in range(10_000)]
    start = time.perf_counter()
    rep = he.compare(shadow, mcp, session_id="scale")
    elapsed = time.perf_counter() - start
    assert rep.match_rate == 1.0
    assert elapsed < 10.0, f"comparator too slow: {elapsed:.2f}s for 10k rows (O(n²) regression?)"


def test_adv_large_divergence_set_not_truncated(tmp_path):
    """500 shadow-only rows must all appear in the report — no silent
    truncation that would mask real policy divergence."""
    shadow = [_shadow("Write", f"h{i}", "deny") for i in range(500)]
    rep = he.compare(shadow, [], session_id="trunc")
    assert len(rep.divergences) == 500
    target = he.emit_report(rep, output_dir=tmp_path)
    body = json.loads(target.read_text())
    assert len(body["divergences"]) == 500


# -- malformed / byzantine input -------------------------------------------


def test_adv_malformed_jsonl_on_shadow_side_is_skipped(tmp_path):
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "sess.jsonl").write_text(
        '{"tool_name":"Write","args_hash":"a","policy_decision":"allow"}\n'
        '{{{this line is junk\n'
        '{"tool_name":"Read","args_hash":"b","policy_decision":"allow"}\n',
        encoding="utf-8",
    )
    audit_root = tmp_path / "state"
    _write_jsonl(
        audit_root / "sessions" / "claude_sess.ledger.jsonl",
        [{"tool": "Write", "digest": "a", "outcome": "allow"},
         {"tool": "Read", "digest": "b", "outcome": "allow"}],
    )
    rep = he.run_comparison("sess", shadow_dir=shadow_dir,
                            audit_root=audit_root, output_dir=tmp_path / "out")
    assert rep.match_rate == 1.0
    assert rep.shadow_count == 2  # junk line dropped


def test_adv_unicode_tool_name_survives_report(tmp_path):
    shadow = [_shadow("Write-⚠", "h", "deny", policy_reason="中文 reason")]
    rep = he.compare(shadow, [], session_id="uni")
    target = he.emit_report(rep, output_dir=tmp_path)
    body = json.loads(target.read_text(encoding="utf-8"))
    assert body["divergences"][0]["key"][0] == "Write-⚠"
    assert body["divergences"][0]["row"]["policy_reason"] == "中文 reason"


def test_adv_none_values_in_mcp_row_project_to_empty_strings():
    """An MCP ledger row with None fields must not throw in mcp_diff_key."""
    row = {"tool": None, "digest": None, "outcome": None}
    tool, ah, dec = he.mcp_diff_key(row)
    assert tool == "" and ah == "" and dec == ""


def test_adv_extra_fields_on_shadow_row_ignored_in_key():
    """Shadow rows carrying extra telemetry (session_id, ts, etc.) must
    not pollute the diff-key — only (tool_name, args_hash, decision) do.
    """
    row = _shadow("Write", "h", "allow", session_id="x", ts="2026-01-01T00:00:00Z")
    assert he.shadow_diff_key(row) == ("Write", "h", "allow")


def test_adv_schema_omission_shadow_row_missing_ts_still_diffs():
    """Schema omission attack (augmented plan §5 row 1): a shadow writer
    that drops the 'ts' field emits usable rows for the comparator,
    because 'ts' is not part of the diff key. The loss is detectable by
    schema checks on the shadow writer side (covered in HOOK-50 adv),
    not by mis-matching here — that separation must hold."""
    row = {"tool_name": "Write", "args_hash": "h", "policy_decision": "allow"}
    assert he.shadow_diff_key(row) == ("Write", "h", "allow")


# -- equivalence-class semantics --------------------------------------------


def test_adv_induced_rate_limit_divergence_caught():
    """Augmented plan §5 row 3: hook counts one more submission than MCP.
    Result: shadow has an extra 'deny' (rate_limited in MCP world) and
    the comparator must flag it."""
    shadow = [_shadow("Write", f"h{i}", "allow") for i in range(5)] + \
             [_shadow("Write", "h6", "deny")]
    mcp = [_mcp("Write", f"h{i}", "allow") for i in range(5)]
    rep = he.compare(shadow, mcp, session_id="rate")
    assert rep.match_rate < 1.0
    assert len(rep.divergences) == 1
    assert rep.divergences[0]["source"] == "shadow"
    assert rep.divergences[0]["key"] == ("Write", "h6", "deny")


def test_adv_rate_limit_normalisation_mutation_detected():
    """Mutation: if mcp_diff_key stopped collapsing 'rate_limited' → 'deny',
    this fixture would produce a divergence. The current code normalises;
    reverting the collapse makes the diff fire, which the test catches."""
    shadow = [_shadow("Write", "h", "deny")]
    mcp = [_mcp("Write", "h", "rate_limited")]
    rep_current = he.compare(shadow, mcp, session_id="norm")
    assert rep_current.match_rate == 1.0

    # Explicit mutation: custom mcp_key that does NOT collapse.
    def no_collapse_mcp_key(row: dict):
        return (
            str(row.get("tool") or ""),
            str(row.get("digest") or ""),
            str(row.get("outcome") or ""),
        )
    rep_mutant = he.compare(shadow, mcp, mcp_key=no_collapse_mcp_key,
                             session_id="norm")
    # Without collapse, 'rate_limited' != 'deny' → two divergences.
    assert rep_mutant.match_rate < 1.0
    assert len(rep_mutant.divergences) == 2


def test_adv_policy_reason_not_part_of_diff_key():
    """Same (tool, hash, decision), different reasons → match. The
    equivalence definition is intentionally decision-only so reason
    wording evolution (e.g. minor copy edits) doesn't fail the gate."""
    shadow = [_shadow("Write", "h", "deny", policy_reason="submission cap")]
    mcp = [_mcp("Write", "h", "deny", detail={"reason": "rate limit"})]
    rep = he.compare(shadow, mcp, session_id="reason")
    assert rep.match_rate == 1.0


# -- fault injection --------------------------------------------------------


def test_adv_missing_audit_root_returns_empty_rows(tmp_path):
    """No state/sessions/ dir at all: load_mcp_audit must not raise."""
    rows = he.load_mcp_audit("sess", audit_root=tmp_path / "nope")
    assert rows == []


def test_adv_missing_shadow_dir_returns_empty_rows(tmp_path):
    rows = he.load_shadow_log("sess", shadow_dir=tmp_path / "nope")
    assert rows == []


def test_adv_oserror_during_load_is_swallowed(tmp_path, monkeypatch, capsys):
    """Make Path.read_text raise OSError — load_jsonl must catch and
    surface a single stderr line, not propagate."""
    target = tmp_path / "log.jsonl"
    target.write_text('{"ok":1}\n', encoding="utf-8")
    real_read = pathlib.Path.read_text

    def fail_read(self, *a, **k):
        if str(self) == str(target):
            raise OSError("i/o blip")
        return real_read(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", fail_read)
    rows = he.load_jsonl(target)
    assert rows == []
    err = capsys.readouterr().err
    assert "load_jsonl" in err


def test_adv_concurrent_run_comparison_isolates_reports(tmp_path):
    """Two run_comparison calls for distinct sessions must produce two
    independent report files; no race on the output directory."""
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    for sid in ("para-1", "para-2"):
        _write_jsonl(
            shadow_dir / f"{sid}.jsonl",
            [_shadow("Write", f"h-{sid}", "allow")],
        )
        _write_jsonl(
            audit_root / "sessions" / f"claude_{sid}.ledger.jsonl",
            [{"tool": "Write", "digest": f"h-{sid}", "outcome": "allow"}],
        )

    def worker(sid: str):
        return he.run_comparison(sid, shadow_dir=shadow_dir,
                                  audit_root=audit_root, output_dir=output_dir)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(worker, ["para-1", "para-2"]))

    for rep in results:
        assert rep.match_rate == 1.0
    assert (output_dir / "equiv_report_para-1.json").exists()
    assert (output_dir / "equiv_report_para-2.json").exists()


# -- CLI / diff gate contract -----------------------------------------------


def test_adv_cli_missing_session_id_is_argparse_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        he.main([])  # no session_id
    assert exc.value.code != 0


def test_adv_cli_deterministic_exit_on_divergence(tmp_path):
    """Two successive runs with the same divergent inputs must both exit
    with code 1. Guards against flaky gate behaviour when the report is
    rewritten atop an existing file."""
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    _write_jsonl(shadow_dir / "det.jsonl", [_shadow("Write", "h", "deny")])
    _write_jsonl(
        audit_root / "sessions" / "claude_det.ledger.jsonl",
        [{"tool": "Write", "digest": "h", "outcome": "allow"}],
    )

    argv = [
        "det",
        "--shadow-dir", str(shadow_dir),
        "--audit-root", str(audit_root),
        "--output-dir", str(output_dir),
    ]
    rc1 = he.main(argv)
    rc2 = he.main(argv)
    assert rc1 == 1 and rc2 == 1
    # Report file exists and is valid JSON after both runs.
    body = json.loads((output_dir / "equiv_report_det.json").read_text())
    assert body["match_rate"] < 1.0


def test_adv_fuzz_random_rows_never_crash():
    """Random byzantine rows fed through the full pipeline must not raise.
    Deterministic seed so a failure is reproducible."""
    rng = random.Random(0xDEADBEEF)
    tools = ["Write", "Read", "Glob", "Grep", "write_file", "replace", None, ""]
    outcomes = ["allow", "deny", "rate_limited", "invalid", "block", None, ""]
    shadow = []
    mcp = []
    for _ in range(200):
        shadow.append({
            "tool_name": rng.choice(tools),
            "args_hash": rng.choice([None, "", "a" * 16, "b" * 16, 42]),
            "policy_decision": rng.choice(outcomes),
        })
        mcp.append({
            "tool": rng.choice(tools),
            "digest": rng.choice([None, "", "a" * 16, "z" * 16]),
            "outcome": rng.choice(outcomes),
        })
    rep = he.compare(shadow, mcp, session_id="fuzz")
    # Report is well-formed regardless of content.
    assert 0.0 <= rep.match_rate <= 1.0
    assert isinstance(rep.divergences, list)
    assert rep.shadow_count == 200 and rep.mcp_count == 200

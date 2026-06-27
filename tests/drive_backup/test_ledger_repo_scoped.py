"""RED oracle: BackupLedger must support per-repo scoping.

A single global ledger (``~/.janusmask/drive_backup/ledger.ndjson``) holds rows
for BOTH JanusMaskEX and NobleGreedv2. An unscoped ``last_backed_up_sha()``
hands a push the most recent sha overall -- which may belong to the OTHER repo,
producing an invalid ``git diff <other-repo-sha>..<this-sha>``. ``record`` must
tag rows with ``repo`` and ``last_backed_up_sha(repo)`` must filter to that
repo, while preserving the original (untagged, global) behavior when ``repo`` is
omitted.

Hermetic: explicit tmp ledger path, no network.
"""
from tools.drive_backup.ledger import BackupLedger


def test_record_with_repo_then_scoped_query(tmp_path):
    led = BackupLedger(str(tmp_path / "ledger.ndjson"))
    led.record("n1" + "0" * 38, "NobleGreedv2_n1", True, repo="NobleGreedv2")
    led.record("j1" + "0" * 38, "JanusMaskEX_j1", True, repo="JanusMaskEX")
    led.record("n2" + "0" * 38, "NobleGreedv2_n2", True, repo="NobleGreedv2")

    assert led.last_backed_up_sha("NobleGreedv2") == "n2" + "0" * 38
    assert led.last_backed_up_sha("JanusMaskEX") == "j1" + "0" * 38
    # Unknown repo => no base (a first backup of that repo is a full archive).
    assert led.last_backed_up_sha("Unseen") is None


def test_unscoped_query_still_returns_most_recent_overall(tmp_path):
    led = BackupLedger(str(tmp_path / "ledger.ndjson"))
    led.record("a" * 40, "A", True, repo="RepoA")
    led.record("b" * 40, "B", True, repo="RepoB")
    # Back-compat: no repo arg => last row overall.
    assert led.last_backed_up_sha() == "b" * 40


def test_untagged_rows_are_skipped_by_scoped_query(tmp_path):
    led = BackupLedger(str(tmp_path / "ledger.ndjson"))
    # Legacy rows written before repo-tagging (3-arg record) carry no repo.
    led.record("old" + "0" * 37, "legacy", True)
    # A scoped query must not mistake a legacy untagged row for this repo.
    assert led.last_backed_up_sha("NobleGreedv2") is None
    # But the unscoped query still sees it.
    assert led.last_backed_up_sha() == "old" + "0" * 37


def test_record_without_repo_keeps_untagged_row_shape(tmp_path):
    path = tmp_path / "ledger.ndjson"
    led = BackupLedger(str(path))
    led.record("c" * 40, "C", False)
    rows = led.entries()
    assert rows and "repo" not in rows[0]

"""RED oracle for leaf `drive-backup-archiver` (ledger half).

Pins `tools/drive_backup/ledger.py`: BackupLedger(path) with an EXPLICIT
path seam, last_backed_up_sha() -> str|None, record(sha, archive_name,
uploaded) -> None (atomic append), entries() -> list[dict]. Hermetic: the
only side effect is a tmp_path file; no subprocess/network/clock.
"""
import json

import pytest

from tools.drive_backup.ledger import BackupLedger


def test_empty_or_missing_ledger_returns_none(tmp_path):
    led = BackupLedger(str(tmp_path / "absent.ndjson"))
    assert led.last_backed_up_sha() is None
    assert led.entries() == []


def test_record_then_last_backed_up_sha_is_most_recent(tmp_path):
    p = tmp_path / "ledger.ndjson"
    led = BackupLedger(str(p))
    led.record("a" * 40, "JanusMaskJR_aaaaaaa_20260612T000000Z.tar.zst", True)
    led.record("b" * 40, "JanusMaskJR_bbbbbbb_20260612T010000Z.tar.zst", False)
    assert led.last_backed_up_sha() == "b" * 40


def test_record_appends_atomically_and_roundtrips(tmp_path):
    p = tmp_path / "ledger.ndjson"
    led = BackupLedger(str(p))
    led.record("c" * 40, "name1.tar.zst", True)
    led.record("d" * 40, "name2.tar.zst", False)
    rows = led.entries()
    assert [r["sha"] for r in rows] == ["c" * 40, "d" * 40]
    assert [r["archive_name"] for r in rows] == ["name1.tar.zst", "name2.tar.zst"]
    assert rows[0]["uploaded"] is True
    assert rows[1]["uploaded"] is False
    # On-disk file is newline-delimited JSON, one object per line.
    on_disk = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    assert [r["sha"] for r in on_disk] == ["c" * 40, "d" * 40]


def test_corrupt_trailing_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "ledger.ndjson"
    led = BackupLedger(str(p))
    led.record("e" * 40, "good.tar.zst", True)
    # Append a corrupt/partial trailing line directly.
    with p.open("a") as fh:
        fh.write('{"sha": "partial", "archive_nam')
    rows = led.entries()
    # The one good row survives; the corrupt trailing line is skipped.
    assert [r["sha"] for r in rows] == ["e" * 40]
    assert led.last_backed_up_sha() == "e" * 40


def test_record_is_durable_across_instances(tmp_path):
    p = tmp_path / "ledger.ndjson"
    BackupLedger(str(p)).record("f" * 40, "n.tar.zst", True)
    # A fresh instance reading the same path sees the persisted entry.
    reread = BackupLedger(str(p))
    assert reread.last_backed_up_sha() == "f" * 40

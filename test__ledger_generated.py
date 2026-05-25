from __future__ import annotations
import datetime
import re
import pytest
from harness.hooks._ledger import _now_iso

def test_now_iso_format():
    val = _now_iso()
    assert isinstance(val, str)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", val)

def test_now_iso_correctness():
    t1 = datetime.datetime.now(datetime.timezone.utc)
    val = _now_iso()
    t2 = datetime.datetime.now(datetime.timezone.utc)
    
    # parse val
    parsed = datetime.datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    
    # Check that the timestamp is within 5 seconds of the current time
    assert abs((parsed - t1).total_seconds()) < 5
    assert t1.replace(microsecond=0) <= parsed <= t2.replace(microsecond=0) + datetime.timedelta(seconds=1)

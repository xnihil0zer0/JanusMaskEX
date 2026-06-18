"""Filter stale brief/plan/task artifacts out of the JanusMaskJR repo root.

Three buckets:
  KEEP    -- active overseer-chat build + code-referenced fixtures (stay in root)
  ARCHIVE -- reusable but inactive (NGv2 parked work, overseer reference briefs,
             external/open fix-plans) -> moved to _autowork_archive/<STAMP>/
  DELETE  -- confirmed-superseded JM-internal fix-plans whose fix already landed
             on master (worthless clutter, irreversible removal)

Dry-run by default; pass --execute to act. Re-runnable / idempotent.
Stamp is passed in (the runtime forbids Date.now-style calls in some contexts);
default mirrors the handoff date.
"""
import argparse
import json
import pathlib
import shutil
import sys
REPO = pathlib.Path(__file__).resolve().parent.parent

def main():
    pass
if __name__ == '__main__':
    main()
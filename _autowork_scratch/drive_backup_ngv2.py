"""Operational: correctly back up the NobleGreedv2 repo to Drive using the
existing drive_backup tool seams (the pre-push hook can't do this itself
because it cd's into JANUSMASK_ROOT and resolves repo-root from cwd)."""
import datetime as _dt
import os
import subprocess
from tools.drive_backup import archiver as archiver_mod
from tools.drive_backup import uploader as uploader_mod
from tools.drive_backup import ledger as ledger_mod

NGV2 = '/home/xnihil0zer0/NobleGreedv2'
SHA = subprocess.run(['git', '-C', NGV2, 'rev-parse', 'HEAD'],
                     capture_output=True, text=True, check=True).stdout.strip()

base_dir = os.path.join(os.path.expanduser('~'), '.janusmask', 'drive_backup')
out_dir = os.path.join(base_dir, 'artifacts')
queue_dir = os.path.join(base_dir, 'queue')
ledger_path = os.path.join(base_dir, 'ledger.ndjson')


def runner(argv):
    return subprocess.run(argv, capture_output=True, check=False)


def now():
    return _dt.datetime.now(_dt.timezone.utc)


print('NGv2 HEAD =', SHA)
res = archiver_mod.build_archive(NGV2, SHA, runner=runner, now=now,
                                 out_dir=out_dir, base_sha=None)
print('archive   =', res.archive_path,
      os.path.getsize(res.archive_path) if os.path.exists(res.archive_path) else 'MISSING')
print('repo(manifest) =', res.manifest.get('repo'))
up = uploader_mod.upload(res, runner=runner, queue_dir=queue_dir)
print('upload    =', up)
ledger_mod.BackupLedger(ledger_path).record(SHA, res.manifest.get('stem'), bool(up.uploaded))
print('ledger recorded; uploaded =', up.uploaded)

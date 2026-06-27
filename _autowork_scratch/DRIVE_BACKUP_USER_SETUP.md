# Drive Backup on Push — One-Time User Setup

This subsystem backs up the WHOLE project directory of **JanusMaskJR** and
**NobleGreedv2** to your Google Drive on every `git push`. The code is built by
the factory, but THREE things require YOU (a human) to run them once, because a
standalone git hook cannot use Claude's Google Drive MCP — it needs its own
credential, and that credential must live OUTSIDE both repos.

You will need to do a Google login in your browser during step 2.

---

## Step 1 — Install rclone (not currently installed)

```bash
# Official one-line installer (asks for sudo to place the binary in /usr/bin):
curl https://rclone.org/install.sh | sudo bash

# Verify:
rclone version
```

(Alternative without sudo, if you prefer: download the zip from
https://rclone.org/downloads/ , unzip, and put the `rclone` binary on your PATH,
e.g. `~/.local/bin/rclone`.)

---

## Step 2 — Configure a Google Drive remote named `gdrive:`  ← THIS IS THE LOGIN

The uploader expects a remote literally named **`gdrive`**. Run:

```bash
rclone config
```

Then answer the interactive prompts:

1. `n`  → **New remote**
2. name → type **`gdrive`**   (must match exactly; the uploader defaults to `gdrive:`)
3. Storage → choose the number for **`drive`** (Google Drive)
4. `client_id` → press **Enter** (leave blank — uses rclone's built-in; fine for personal use)
5. `client_secret` → press **Enter** (leave blank)
6. `scope` → choose **`1`** (`drive` — full access) so it can create the backup folder
7. `root_folder_id` → press **Enter** (leave blank)
8. `service_account_file` → press **Enter** (leave blank)
9. `Edit advanced config?` → **`n`**
10. `Use auto config?` → **`y`** (opens your browser)
    - **>>> A browser window opens here — log in to your Google account and click "Allow". <<<**
    - (If you are on a headless box with no browser, answer **`n`** and follow the
      `rclone authorize "drive"` instructions it prints — run that on a machine WITH
      a browser, then paste the token back.)
11. `Configure this as a Shared Drive (Team Drive)?` → **`n`** (unless you want a Team Drive)
12. Confirm the remote → **`y`**
13. `q` → **Quit config**

The credential token is now stored at **`~/.config/rclone/rclone.conf`** — OUTSIDE
both repos, never committed. (To put it elsewhere, set `RCLONE_CONFIG=/your/path`.)

### Verify the remote works
```bash
rclone lsd gdrive:
```
You should see your Drive's top-level folders. The backups will land in
`gdrive:repo-push-backups/<repo>/` (the folder is created automatically on first push).

---

## Step 3 — Install the pre-push hook into BOTH repos

From the JanusMaskJR repo root, once the factory has built the subsystem:

```bash
cd /home/xnihil0zer0/JanusMaskJR
python -m tools.drive_backup.install_hooks            # add --dry-run first to preview
```

This writes a thin, marker-guarded `pre-push` hook into:
- `/home/xnihil0zer0/JanusMaskJR/.git/hooks/pre-push`
- `/home/xnihil0zer0/NobleGreedv2/.git/hooks/pre-push`

It is idempotent (safe to re-run) and preserves any existing pre-push hook by
chaining to it.

---

## What happens on each `git push`

1. The pre-push hook fires LOCALLY, before the push proceeds.
2. It builds `<repo>_<sha7>_<utc-timestamp>.tar.zst` — a zstd-compressed tar of the
   whole working tree at the pushed commit — PLUS a `<...>.diff` (`git diff` against
   the previously-backed-up commit).
3. It uploads both to `gdrive:repo-push-backups/<repo>/` via rclone.
4. **The push is NEVER blocked.** If Drive is down or rclone errors, the artifacts
   are queued locally and the failure is logged loudly; the push still proceeds.

### Excluded from the archive (caches/bloat, by design)
`node_modules`, `.venv` / `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`,
`*.pyc`, `state/output`, `_autowork_archive`. The `.git` directory IS included
(you asked for the whole directory). The exact exclude list is recorded in each
archive's manifest. Adjust in `tools/drive_backup/archiver.py:DEFAULT_EXCLUDES`.

### Retry queued backups manually (after a Drive outage)
```bash
python -c "from tools.drive_backup.uploader import drive_backup_drain; \
print(drive_backup_drain('/home/xnihil0zer0/JanusMaskJR/state/drive_backup_queue'))"
```

---

## Summary: where a login/credential is required
- **Step 2 (`rclone config`)** is the ONLY login — a Google OAuth consent in your
  browser. The token is stored in `~/.config/rclone/rclone.conf`, outside both
  repos, and is never committed. Nothing else requires you to log in.

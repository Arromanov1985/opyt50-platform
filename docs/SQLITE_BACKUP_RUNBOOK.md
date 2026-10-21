# SQLite backup and restore runbook — preview only

## Before deployment
Current database: `/srv/data/opyt50.db` (container overlay, not durable). A backup left in the container may disappear when the container is replaced.

1. Confirm no real personal data are being used in preview.
2. In the Timeweb console, create a unique backup in the temporary directory:
   ```sh
   python scripts/backup_sqlite.py --output /tmp/opyt50-before-deploy.db
   ```
3. Validate the file exists: `ls -lh /tmp/opyt50-before-deploy.db`.
4. **Export the backup to a secure location outside the container before any deployment.** The console alone may not provide file download. If no safe export mechanism is available, stop; do not deploy assuming the backup is protected.
5. Never commit database backups to GitHub; they may contain account information, hashes and contact data.

## Restoration policy
Restoration is intentionally **not automated**. Stop application writes before replacing a database. Make a second independent copy of the current DB, restore into a new file, run `PRAGMA integrity_check`, verify expected row counts, then arrange a controlled swap with a rollback plan. SQLite WAL sidecar files must be handled consistently; never overwrite a live database file in place.

## Acceptance criteria
- Backup script exits successfully and prints verified path.
- Backup file can be read independently, with integrity `ok`.
- Backup is transferred outside Timeweb before a destructive deployment.
- Restoration is rehearsed only on an isolated copy, not the live database.
- No paid infrastructure is provisioned without approval.

# Release 0.5: SQLite persistence investigation (preview only)

## Verified implementation
- Dockerfile declares `OPYT50_DB_PATH=/srv/data/opyt50.db`.
- The Docker image creates `/srv/data`, but does not mount durable storage.
- `app/db.py` initializes SQLite in WAL mode.
- `deploy/start.sh` runs `seed_demo.py` when `OPYT50_PREVIEW_SEED_DEMO=1`; seeding skips a database that already contains users.
- App startup calls `init_db` and `init_release02`. Their `CREATE TABLE IF NOT EXISTS` statements do not guarantee persistence across container replacements.

## Read-only diagnostic
Run inside the existing preview container, if console access is available:

```sh
python scripts/audit_storage.py
```

The diagnostic prints only file existence, table row counts, and SQLite integrity status. It never creates a missing DB, modifies rows, or displays personal information. Compare output **before and after** a future deployment. Do not redeploy solely to test data loss.

## Acceptance criteria
1. A missing DB is reported as missing without being created.
2. Existing DB row counts are correct and integrity is `ok`.
3. No database contents change during auditing.
4. Persisting data across container replacement requires an actual durable volume or external database; this PR does not claim to provide it.
5. No changes to Timeweb deployment settings, real payments, or production data.

## Recommended next step
Verify whether Timeweb App Platform offers a supported persistent mount for this app. If not, evaluate external PostgreSQL and its cost **before** requesting deployment approval. Do not create paid resources without explicit consent.

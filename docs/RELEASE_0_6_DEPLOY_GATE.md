# Release 0.6 — production status

**Status:** Release 0.6 functionality is present on the PostgreSQL runtime used by production. The old SQLite/App Platform persistence gate is superseded by the completed PostgreSQL cutover.

## Production state

- Production application: `opytno-production`.
- Durable database: managed PostgreSQL.
- PostgreSQL runtime branch lineage includes the release 0.6 employer UI.
- Production data was migrated from the verified final SQLite snapshot.
- PostgreSQL backups are enabled.
- The retired SQLite production app was removed after cutover verification.
- `main` has not been merged with the PostgreSQL/release branch yet.

## Release 0.6 scope

Release 0.6 adds the employer vacancy overview and application analytics:

- vacancy filters: all / open / closed;
- vacancy counts;
- application metrics;
- interested-candidate and introduction metrics;
- per-vacancy navigation to applications;
- reuse of the employer applications page with vacancy filtering.

## Acceptance status

- [x] Vacancy overview: all/open/closed, counts and filter controls
- [x] Applications metrics and per-vacancy link
- [x] Existing employer applications page reused, filtering by vacancy
- [x] Browser smoke coverage for release 0.6
- [x] Manual visual acceptance performed before the database migration
- [x] Durable PostgreSQL storage verified
- [x] SQLite-to-PostgreSQL migration completed and record counts verified
- [x] Production cutover completed
- [x] Production homepage, vacancy list, employer login and employer cabinet verified after cutover
- [x] PostgreSQL backups enabled
- [ ] Repository housekeeping: reconcile the release/PostgreSQL branch with the one newer commit on `main`
- [ ] Merge to `main` only after explicit approval

## Safety rule

Do not re-run the SQLite migration, clean the PostgreSQL schema, change the production domain, remove the private network, or merge to `main` without a separate reason and explicit approval where required.

## Current release branch

Active continuation branch:

`feature/release-0.6-postgres`

It was created from the verified PostgreSQL runtime commit:

`ef1a1e9bb6d582cc77c101d44ae7a8501897720e`

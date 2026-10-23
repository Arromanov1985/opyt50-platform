# Release 0.6 — pre-deploy acceptance gate

**Status:** DO NOT deploy to `opytno-preview` until durable storage has been demonstrated.

## Why this gate exists

The preview's SQLite database is at `/srv/data/opyt50.db`. On the inspected Timeweb deployment, `/srv/data` belongs to the container's `overlay` filesystem. It has **not** been verified as persistent across container replacement. An application redeploy may replace the writable layer and lose accounts, job applications and invitations.

A tested, encrypted off-container backup is necessary but **not sufficient** to provide continuous persistence: any changes since that backup can still be lost.

## Completed

- The employer UI release 0.6 is isolated in `feature/release-0.6-development`.
- Backend and browser CI must be green for the current head commit.
- An encrypted SQLite backup was made outside this repository and the restore integrity was checked with `PRAGMA integrity_check`.
- No real user accounts or personal data should be onboarded in the preview.

## Required before changing Timeweb settings or branch

1. Obtain Timeweb confirmation of a supported **persistent storage mount** for App Platform, or agree on a durable database migration path. Do **not** assume that a network disk is mountable or SQLite-safe.
2. Perform an isolated rehearsal that creates a record, replaces the container, and verifies it survives; never use real user data for this rehearsal.
3. Immediately before any approved deployment, take a new *consistent* SQLite backup, verify integrity and record counts, export it **outside the container**, and keep the password separately. The older backup is only a historical snapshot.
4. Record deployed branch and commit, environment variable **names** (not secrets), expected DB path, backup SHA-256 and a rollback procedure.
5. Confirm that preview demo seeding cannot overwrite an existing database and that no production personal data are present.
6. Obtain explicit approval for the Timeweb branch change, any infrastructure charges, and merging PR #17. Do not conflate CI success with permission to deploy.
7. After an approved deploy, verify the health endpoint and a fresh test of employer vacancy metrics, filters, and application-to-introduction flow.

## Rollback

Stop further writes and use only a separately verified backup on an isolated volume. Do not overwrite a live SQLite database or discard WAL sidecars. If persistence cannot be demonstrated, leave the current preview running and keep the release in GitHub.

## Release 0.6 acceptance matrix

- [x] Vacancy overview: all/open/closed, counts and filter controls added
- [x] Applications metrics and per-vacancy link added
- [x] Existing employer applications page reused, filtering by vacancy
- [x] GitHub Actions succeeded on release 0.6 browser smoke (check latest commit before approval)
- [ ] Manual visual acceptance on isolated preview
- [ ] Durable database storage independently verified
- [ ] Fresh off-container backup created immediately before deployment
- [ ] Explicit deployment/merge approval

# PostgreSQL diagnostic — isolated testing only

This tool confirms connectivity to a PostgreSQL instance without creating or altering tables.

The existing `opytno-preview` uses SQLite and **must not be reconfigured** at this stage.

## From a test container in `opytno-private`

1. Ensure the container shares the private network with the database cluster.
2. Install dependencies: `python -m pip install -r requirements-postgres.txt`.
3. In the **Timeweb environment variables UI**, set `DATABASE_URL` to a PostgreSQL DSN for the actual database (`default_db` on the current Timeweb cluster), not the cluster display name. Do not paste secrets into issue comments, logs, or GitHub files.
4. Run `python scripts/check_postgres_connection.py` from that container's console. It only runs a `SELECT` and returns database/user/version and whether TLS is active.
5. If the database offers TLS and its certificate has been validated, configure secure connection parameters in the DSN; `OPYTNO_REQUIRE_PG_TLS=1` will fail unless TLS is active. This diagnostic does **not** establish certificate trust by itself.

Do not create a paid test app, switch Timeweb branches, initialize the PostgreSQL schema, migrate personal data, or merge the PR without separate approval. The private PostgreSQL host is inaccessible from GitHub-hosted CI unless network access has explicitly been configured.

The current FastAPI app is still SQLite-only: this diagnostic does **not** imply that PostgreSQL application support is complete.

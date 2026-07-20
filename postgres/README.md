# PostgreSQL Database Driver

A native PostgreSQL backend for the `db-base` document layer. It keeps the
same `db.connect()` API as sqlite and Supabase while storing documents in a
regular PostgreSQL database through psycopg.

## Install

Requires `db-base` first (`package-req` enforces the order):

```text
python SyKit package add db-base --yes --allow-core
python SyKit package add postgres --yes --allow-core
python -m pip install "psycopg[binary]>=3.1,<4"
```

SyKit reports the psycopg dependency but never installs it. `--allow-core` is
required because this package adds `sykit/postgres.py`. Existing projects
should re-run `python SyKit init` after installation, then rebuild.

## Configuration

Pass a libpq connection string or `postgresql://` URL after the scheme:

```python
from sykit import db

store = db.connect("postgres:postgresql://user:password@db.example.com/app")
```

To keep credentials out of application code and config, leave the target
empty and set the shared PostgreSQL variable:

```text
SYKIT_POSTGRES_DSN=postgresql://user:password@db.example.com/app
```

```python
store = db.connect("postgres:")
```

This is the same variable and connection-string convention used by the
`postgres-sessions` package, so one database setting can serve both packages.
With SyKit's `use-dotenv`, it can live in the project-root `.env` file.

## Behavior

- Creates the `sykit_documents` table automatically on first use.
- Stores values as PostgreSQL `jsonb`; `db-base` validates JSON values,
  collection names, and document keys before the driver runs.
- Uses an atomic `INSERT ... ON CONFLICT` upsert for `put()`.
- Returns keys and items sorted by key, matching the sqlite driver.
- Opens one short-lived connection per operation. Driver instances are safe to
  share between endpoint threads and workers; use PgBouncer if connection
  churn matters at your scale.
- Wraps connection and query failures as `db.DatabaseError` without putting
  the connection string in the error message.

The package has no hosted-service setup or account dependency. Its tests use a
mock psycopg module and do not contact a database.

## Contents

- `add/sykit/postgres.py`
- `add/tests/test_postgres.py`

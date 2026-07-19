# PostgreSQL Sessions

A PostgreSQL backend for SyKit's `session-store` setting: sessions
shared by every worker on every host that reaches the database, with
real server-side revocation on logout. Lifts the built-in sqlite
store's single-machine limit.

## Install

Requires SyKit 0.5.0 or newer (`sykit-req` enforces this):

```
python SyKit package add postgres-sessions --yes
```

The package only adds files (a `files/core/` module and a test), so the
pre-install report shows a `dependency` warning for psycopg and no
critical findings. SyKit never installs dependencies; install it
yourself:

```
python -m pip install "psycopg[binary]>=3.1,<4"
```

## Setup

Point `session-store` at the database in `src/sykit/config.json`:

```json
"session-store": "postgres:host=db.example.com dbname=app user=sykit password=..."
```

or keep the connection string out of the config:

```json
"session-store": "postgres:"
```

| Variable | Meaning |
| --- | --- |
| `SYKIT_POSTGRES_DSN` | Connection string used when the target after `postgres:` is empty; a libpq conninfo string or `postgresql://` URL |

Then rebuild (`python SyKit build`). The `sykit_sessions` table is
created automatically on first use. No import or endpoint code is
needed: SyKit resolves the `postgres` scheme to this package's
`core/_store_postgres.py` by name.

## Behavior

- Same contract as the built-in sqlite store: sliding expiry, session
  id rotation on login, logout deletes the row so every cookie copy
  dies at once.
- One short-lived connection per session operation; no pool to
  configure and safe under multiple workers. Put PgBouncer in front if
  connection churn matters at your scale.
- If the database is unreachable the app answers
  `503 {"error": "Sessions are temporarily unavailable."}` and logs the
  error, the same as any session store failure.

## Contents

- `add/files/core/_store_postgres.py`
- `add/tests/test_postgres_sessions.py`
- `edit/files/.env.example` (append)

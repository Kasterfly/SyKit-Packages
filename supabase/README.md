# Supabase Database Driver

A [Supabase](https://supabase.com) backend for the `db-base` document
layer: the same `db.connect()` API, with the documents stored in your
Supabase project's Postgres through its REST API (PostgREST). Standard
library only, no SDK dependency.

## Install

Requires the `db-base` package first (`package-req` enforces the order):

```
python SyKit package add db-base --yes --allow-core
python SyKit package add supabase --yes --allow-core
```

`--allow-core` is required because the package adds a module under
`sykit/`; the pre-install report shows a `core-edit` finding for
`sykit/supabase.py`, `env-read` findings for the credential variables,
and a `url` finding for the supabase.com link in the module docstring.
Existing projects should re-run `python SyKit init` afterwards so the
new module is copied into `src/`, then rebuild.

## Setup

Create the documents table once in the Supabase SQL editor:

```sql
create table if not exists sykit_documents (
    collection text not null,
    key text not null,
    value jsonb not null,
    primary key (collection, key)
);
```

Keep row level security enabled on the table. The server uses the
service role key, which bypasses RLS; anon clients stay locked out.

| Variable | Meaning |
| --- | --- |
| `SYKIT_SUPABASE_URL` | The project URL, `https://<project>.supabase.co` |
| `SYKIT_SUPABASE_KEY` | The service role key (server-side only; never ship it to browsers) |

With SyKit's `use-dotenv` setting both can live in the project `.env`.

## Usage

```python
from sykit import db

store = db.connect("supabase:")             # table sykit_documents
store = db.connect("supabase:other_table")  # a different table

store.put("users", "alice", {"role": "admin"})
user = store.get("users", "alice", default={})
names = store.keys("users")
everything = store.items("users")
store.delete("users", "alice")
```

No import of `sykit.supabase` is needed: `db.connect()` imports the
module by scheme name and the module registers the driver (db-base from
this repository or newer).

Values must be JSON-serializable; keys and collections follow db-base's
rules. `keys()` and `items()` page through Supabase's 1000-row response
cap, so large collections never truncate silently. Failures raise
`db.DatabaseError` with the HTTP status and the PostgREST message.

## Contents

- `add/sykit/supabase.py`
- `add/tests/test_supabase.py`
- `edit/files/.env.example` (append)

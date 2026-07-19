# Database Base

A small document database layer for SyKit apps: named collections of JSON
documents. SQLite (standard library) by default, with a driver interface
that other database packages (Supabase, DynamoDB, ...) register into so
apps can switch backends without changing endpoint code.

## Install

```
python SyKit package add db-base --yes --allow-core
```

`--allow-core` is required because the package adds a module under
`sykit/`; the pre-install report shows a `core-edit` finding for
`sykit/db.py`, an `env-read` finding for the optional path variable, and
an `exec-call` finding for the `importlib` call that loads provider
modules by scheme name. Existing projects should re-run
`python SyKit init` afterwards so the new module is copied into `src/`,
then rebuild.

## Configuration

| Variable | Meaning |
| --- | --- |
| `SYKIT_DB_PATH` | Optional sqlite file used by `db.connect()` when no target is passed (default `sykit.db` in the app's working directory) |

## Usage

```python
from sykit import db

store = db.connect()
store.put("users", "alice", {"role": "admin"})
user = store.get("users", "alice", default={})
names = store.keys("users")
everything = store.items("users")
store.delete("users", "alice")
store.close()
```

`connect()` also takes a path (`db.connect("data/app.db")`), an explicit
`sqlite:` target, or any registered driver scheme. Unknown schemes raise a
clear error naming the registered drivers, so a missing provider package
fails loudly. Values must be JSON-serializable; keys are strings up to 512
characters; collection names are simple identifiers.

## Writing a driver package

Provider packages add their own `sykit/` module, implement
`get/put/delete/keys/items/close`, and register a factory:

```python
from sykit import db

db.register_driver("myscheme", lambda target: MyDriver(target))
```

Then `db.connect("myscheme:whatever-the-driver-needs")` uses it. Name
the module after the scheme (`sykit/myscheme.py`): `connect()` imports
`sykit.<scheme>` automatically when it sees an unregistered scheme, so
apps never import the provider themselves. Declare
`"package-req": ["db-base"]` in the provider's `SyKitPackage.json`. The
`supabase` package in this repository is the reference implementation.

## Contents

- `add/sykit/db.py`
- `add/tests/test_db.py`
- `edit/files/.env.example` (append)

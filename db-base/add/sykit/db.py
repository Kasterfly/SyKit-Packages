"""Small document database layer for SyKit apps.

SQLite (standard library) by default; provider packages can register other
backends (Supabase, DynamoDB, ...) under a scheme name and reuse the same
API. Values are JSON documents grouped into named collections.

Usage from an endpoint:

    from sykit import db

    store = db.connect()
    store.put("users", "alice", {"role": "admin"})
    user = store.get("users", "alice", default={})

Targets accepted by connect():

    connect()                   sqlite file (SYKIT_DB_PATH or sykit.db)
    connect("data/app.db")      sqlite file at a path
    connect("sqlite:app.db")    the same, explicit
    connect("scheme:target")    any driver registered by another package

Driver packages implement get/put/delete/keys/items/close and register a
factory taking the target string:

    from sykit import db

    db.register_driver("myscheme", lambda target: MyDriver(target))

Name the provider module after its scheme (sykit/myscheme.py):
connect("myscheme:...") imports sykit.myscheme automatically, so apps
never need to import the provider themselves.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from importlib import import_module
from typing import Any, Callable

DEFAULT_PATH = "sykit.db"
PATH_ENV = "SYKIT_DB_PATH"
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MAX_KEY_LENGTH = 512


class DatabaseError(RuntimeError):
    """A user-facing database failure."""


def _valid_collection(value: Any) -> str:
    if not isinstance(value, str) or not NAME_PATTERN.fullmatch(value):
        raise DatabaseError(
            "collection names must be 1-64 characters of letters, digits, "
            '".", "_" or "-", starting with a letter or digit.'
        )
    return value


def _valid_key(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_KEY_LENGTH:
        raise DatabaseError(
            f"keys must be non-empty strings of at most {MAX_KEY_LENGTH} characters."
        )
    return value


class SqliteDriver:
    """Default driver: one sqlite file, one documents table."""

    def __init__(self, target: str) -> None:
        path = target or os.environ.get(PATH_ENV, "") or DEFAULT_PATH
        self._lock = threading.Lock()
        try:
            self._connection = sqlite3.connect(path, check_same_thread=False)
            with self._lock, self._connection:
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS documents ("
                    "collection TEXT NOT NULL, "
                    "key TEXT NOT NULL, "
                    "value TEXT NOT NULL, "
                    "PRIMARY KEY (collection, key))"
                )
        except sqlite3.Error as error:
            raise DatabaseError(f"Could not open database {path!r}: {error}") from error

    def get(self, collection: str, key: str) -> Any | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM documents WHERE collection = ? AND key = ?",
                (collection, key),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def put(self, collection: str, key: str, value: Any) -> None:
        text = json.dumps(value)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO documents (collection, key, value) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (collection, key) DO UPDATE SET value = excluded.value",
                (collection, key, text),
            )

    def delete(self, collection: str, key: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM documents WHERE collection = ? AND key = ?",
                (collection, key),
            )
        return cursor.rowcount > 0

    def keys(self, collection: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT key FROM documents WHERE collection = ? ORDER BY key",
                (collection,),
            ).fetchall()
        return [row[0] for row in rows]

    def items(self, collection: str) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT key, value FROM documents WHERE collection = ? ORDER BY key",
                (collection,),
            ).fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}

    def close(self) -> None:
        with self._lock:
            self._connection.close()


_DRIVERS: dict[str, Callable[[str], Any]] = {}


def register_driver(scheme: str, factory: Callable[[str], Any]) -> None:
    """Register a driver factory under a scheme name.

    The factory receives the target text after "scheme:" and returns an
    object implementing get/put/delete/keys/items/close.
    """
    if not isinstance(scheme, str) or not NAME_PATTERN.fullmatch(scheme):
        raise DatabaseError("driver schemes must be simple names.")
    if not callable(factory):
        raise DatabaseError("driver factories must be callable.")
    _DRIVERS[scheme.casefold()] = factory


register_driver("sqlite", SqliteDriver)


class Database:
    """Validated wrapper around a driver. Safe to share between threads
    as long as the driver is (the sqlite driver is)."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def get(self, collection: str, key: str, default: Any = None) -> Any:
        value = self._driver.get(_valid_collection(collection), _valid_key(key))
        return default if value is None else value

    def put(self, collection: str, key: str, value: Any) -> None:
        _valid_collection(collection)
        _valid_key(key)
        try:
            json.dumps(value)
        except (TypeError, ValueError) as error:
            raise DatabaseError(f"values must be JSON-serializable: {error}") from error
        self._driver.put(collection, key, value)

    def delete(self, collection: str, key: str) -> bool:
        return bool(self._driver.delete(_valid_collection(collection), _valid_key(key)))

    def keys(self, collection: str) -> list[str]:
        return list(self._driver.keys(_valid_collection(collection)))

    def items(self, collection: str) -> dict[str, Any]:
        return dict(self._driver.items(_valid_collection(collection)))

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_exception: Any) -> None:
        self.close()


def connect(target: str | None = None) -> Database:
    """Open a database.

    None or a plain path opens the sqlite driver. "scheme:rest" dispatches
    to a registered driver, importing sykit.<scheme> first when the scheme
    is not registered yet; a single-letter scheme is treated as a Windows
    drive letter and stays a sqlite path. Unknown schemes raise, so a
    missing provider package fails loudly instead of writing to an odd
    file.
    """
    if target is not None and not isinstance(target, str):
        raise DatabaseError("connect() takes None or a string target.")
    scheme = "sqlite"
    rest = target or ""
    if target and ":" in target:
        prefix, _, remainder = target.partition(":")
        folded = prefix.casefold()
        if folded not in _DRIVERS and len(prefix) != 1 and folded.isidentifier():
            # Provider packages register their scheme when their module is
            # imported; look for a module named after the scheme.
            try:
                import_module(f"sykit.{folded}")
            except ImportError:
                pass
        if folded in _DRIVERS:
            scheme, rest = folded, remainder
        elif len(prefix) != 1:
            known = ", ".join(sorted(_DRIVERS))
            raise DatabaseError(
                f"Unknown database driver {prefix!r}; registered drivers: "
                f"{known}. Install the matching package or use a plain "
                "sqlite path."
            )
    factory = _DRIVERS[scheme]
    return Database(factory(rest))

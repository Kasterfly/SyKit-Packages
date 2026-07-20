"""PostgreSQL driver for the sykit.db document layer.

Importing this module registers the "postgres" scheme. db.connect() imports
it automatically for targets such as:

    db.connect("postgres:postgresql://user:password@host/app")
    db.connect("postgres:")  # reads SYKIT_POSTGRES_DSN

The sykit_documents table is created automatically on first use. Values are
stored as jsonb and all SQL identifiers are fixed, while collection and key
values are passed as query parameters.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from sykit import db

DSN_ENV = "SYKIT_POSTGRES_DSN"
TABLE = "sykit_documents"


class PostgresDriver:
    """sykit.db driver over PostgreSQL via psycopg 3."""

    def __init__(self, target: str) -> None:
        conninfo = (target or "").strip() or os.environ.get(DSN_ENV, "").strip()
        if not conninfo:
            raise db.DatabaseError(
                "PostgreSQL is not configured; pass a connection string after "
                f'"postgres:" or set {DSN_ENV}.'
            )
        try:
            import psycopg
        except ImportError as error:
            raise db.DatabaseError(
                "The postgres database driver needs psycopg: "
                'python -m pip install "psycopg[binary]>=3.1,<4"'
            ) from error
        self._psycopg = psycopg
        self._conninfo = conninfo
        self._schema_ready = False

    def _connect(self):
        connection = self._psycopg.connect(self._conninfo)
        if self._schema_ready:
            return connection
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                    "collection text NOT NULL, "
                    "key text NOT NULL, "
                    "value jsonb NOT NULL, "
                    "PRIMARY KEY (collection, key))"
                )
            connection.commit()
        except Exception:
            connection.close()
            raise
        self._schema_ready = True
        return connection

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        try:
            with self._connect() as connection:
                yield connection
        except db.DatabaseError:
            raise
        except Exception as error:
            raise db.DatabaseError(
                f"PostgreSQL database operation failed: {error}"
            ) from error

    def get(self, collection: str, key: str) -> Any | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT value FROM {TABLE} WHERE collection = %s AND key = %s",
                    (collection, key),
                )
                row = cursor.fetchone()
        return None if row is None else row[0]

    def put(self, collection: str, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {TABLE} (collection, key, value) "
                    "VALUES (%s, %s, %s::jsonb) "
                    "ON CONFLICT (collection, key) DO UPDATE SET "
                    "value = EXCLUDED.value",
                    (collection, key, encoded),
                )

    def delete(self, collection: str, key: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {TABLE} "
                    "WHERE collection = %s AND key = %s RETURNING key",
                    (collection, key),
                )
                deleted = cursor.fetchone()
        return deleted is not None

    def keys(self, collection: str) -> list[str]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT key FROM {TABLE} WHERE collection = %s ORDER BY key",
                    (collection,),
                )
                rows = cursor.fetchall()
        return [row[0] for row in rows]

    def items(self, collection: str) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT key, value FROM {TABLE} "
                    "WHERE collection = %s ORDER BY key",
                    (collection,),
                )
                rows = cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    def close(self) -> None:
        pass


db.register_driver("postgres", PostgresDriver)

"""PostgreSQL session store for SyKit's "session-store" setting.

Activate with:

    "session-store": "postgres:host=db.example.com dbname=app user=..."

or "postgres:" plus the SYKIT_POSTGRES_DSN environment variable. The
text after "postgres:" is a libpq conninfo string or postgresql:// URL,
passed to psycopg unchanged.

Declared dependency (SyKit never installs it):

    python -m pip install "psycopg[binary]>=3.1,<4"

The sykit_sessions table is created automatically. Sessions are shared
by every worker on every host that reaches the database, which is the
point: this lifts the sqlite store's single-machine limit.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

DSN_ENV = "SYKIT_POSTGRES_DSN"
TABLE = "sykit_sessions"


class PostgresSessionStore:
    """SessionStore backend on PostgreSQL via psycopg (v3)."""

    def __init__(self, conninfo: str) -> None:
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError(
                'The "postgres" session store needs the psycopg package: '
                'python -m pip install "psycopg[binary]>=3.1,<4"'
            ) from error
        self._psycopg = psycopg
        self._conninfo = conninfo
        self._schema_ready = False
        self._last_cleanup = 0

    def _connect(self):
        connection = self._psycopg.connect(self._conninfo)
        if not self._schema_ready:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE IF NOT EXISTS {TABLE} ("
                    "session_id text PRIMARY KEY, "
                    "data text NOT NULL, "
                    "expires bigint NOT NULL)"
                )
            connection.commit()
            self._schema_ready = True
        return connection

    def load(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT data, expires FROM {TABLE} WHERE session_id = %s",
                    (session_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                if row[1] < int(time.time()):
                    cursor.execute(
                        f"DELETE FROM {TABLE} WHERE session_id = %s",
                        (session_id,),
                    )
                    return None
                value = json.loads(row[0])
                return value if isinstance(value, dict) else None

    def save(self, session_id: str, data: dict[str, Any], max_age: int) -> None:
        now = int(time.time())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {TABLE} (session_id, data, expires) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (session_id) DO UPDATE SET "
                    "data = EXCLUDED.data, expires = EXCLUDED.expires",
                    (session_id, json.dumps(data), now + max_age),
                )
                if now - self._last_cleanup >= 3600:
                    cursor.execute(f"DELETE FROM {TABLE} WHERE expires < %s", (now,))
                    self._last_cleanup = now

    def touch(self, session_id: str, max_age: int) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {TABLE} SET expires = %s WHERE session_id = %s",
                    (int(time.time()) + max_age, session_id),
                )

    def delete(self, session_id: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {TABLE} WHERE session_id = %s",
                    (session_id,),
                )


def create(target: str) -> PostgresSessionStore:
    conninfo = (target or "").strip() or os.environ.get(DSN_ENV, "").strip()
    if not conninfo:
        raise RuntimeError(
            'The "postgres" session store needs a connection string: use '
            f'"postgres:<conninfo>" or set {DSN_ENV}.'
        )
    return PostgresSessionStore(conninfo)

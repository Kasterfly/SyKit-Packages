from __future__ import annotations

import json
import sys
import types
import unittest
from unittest import mock

from sykit import db, postgres


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exception: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        if self.connection.module.execute_error is not None:
            raise self.connection.module.execute_error
        self.connection.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        if self.connection.rows:
            return self.connection.rows.pop(0)
        return None

    def fetchall(self):
        rows = list(self.connection.rows)
        self.connection.rows.clear()
        return rows


class FakeConnection:
    def __init__(self, module: "FakePsycopg") -> None:
        self.module = module
        self.executed: list[tuple[str, tuple | None]] = []
        self.rows = list(module.next_rows)
        module.next_rows = []
        self.committed = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exception: object) -> None:
        self.committed = True
        self.closed = True


class FakePsycopg(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("psycopg")
        self.conninfos: list[str] = []
        self.connections: list[FakeConnection] = []
        self.next_rows: list[tuple] = []
        self.connect_error: Exception | None = None
        self.execute_error: Exception | None = None

    def connect(self, conninfo: str) -> FakeConnection:
        if self.connect_error is not None:
            raise self.connect_error
        self.conninfos.append(conninfo)
        connection = FakeConnection(self)
        self.connections.append(connection)
        return connection


class PostgresDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakePsycopg()
        patcher = mock.patch.dict(sys.modules, {"psycopg": self.fake})
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def sql(connection: FakeConnection) -> list[str]:
        return [statement for statement, _params in connection.executed]

    def driver(self, target: str = "dbname=app") -> postgres.PostgresDriver:
        return postgres.PostgresDriver(target)

    def test_scheme_dispatch_and_connection_configuration(self) -> None:
        self.assertIn("postgres", db._DRIVERS)
        store = db.connect("postgres:dbname=app user=sykit")
        self.assertEqual(store._driver._conninfo, "dbname=app user=sykit")
        store.close()

        with mock.patch.dict("os.environ", {postgres.DSN_ENV: "postgresql://db/app"}):
            store = db.connect("postgres:")
        self.assertEqual(store._driver._conninfo, "postgresql://db/app")

        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(db.DatabaseError, postgres.DSN_ENV):
                postgres.PostgresDriver("")

    def test_missing_psycopg_says_how_to_install(self) -> None:
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with self.assertRaisesRegex(db.DatabaseError, "pip install"):
                postgres.PostgresDriver("dbname=app")

    def test_schema_is_created_once(self) -> None:
        driver = self.driver()
        driver.delete("users", "alice")
        driver.delete("users", "bob")
        first, second = self.fake.connections
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS sykit_documents",
            self.sql(first)[0],
        )
        self.assertNotIn("CREATE TABLE", " ".join(self.sql(second)))
        self.assertTrue(first.committed)
        self.assertTrue(first.closed and second.closed)

    def test_get_returns_jsonb_value_or_none(self) -> None:
        driver = self.driver()
        self.fake.next_rows = [({"role": "admin"},)]
        self.assertEqual(driver.get("users", "alice"), {"role": "admin"})
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("SELECT value FROM sykit_documents", statement)
        self.assertEqual(params, ("users", "alice"))

        self.fake.next_rows = []
        self.assertIsNone(driver.get("users", "missing"))

    def test_put_uses_jsonb_upsert(self) -> None:
        driver = self.driver()
        driver.put("users", "alice", {"roles": ["admin"], "active": True})
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("VALUES (%s, %s, %s::jsonb)", statement)
        self.assertIn("ON CONFLICT (collection, key) DO UPDATE", statement)
        self.assertEqual(params[:2], ("users", "alice"))
        self.assertEqual(
            json.loads(params[2]),
            {"roles": ["admin"], "active": True},
        )

    def test_delete_reports_whether_a_document_existed(self) -> None:
        driver = self.driver()
        self.fake.next_rows = [("alice",)]
        self.assertTrue(driver.delete("users", "alice"))
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("DELETE FROM sykit_documents", statement)
        self.assertIn("RETURNING key", statement)
        self.assertEqual(params, ("users", "alice"))

        self.fake.next_rows = []
        self.assertFalse(driver.delete("users", "missing"))

    def test_keys_and_items_are_sorted_queries(self) -> None:
        driver = self.driver()
        self.fake.next_rows = [("alice",), ("bob",)]
        self.assertEqual(driver.keys("users"), ["alice", "bob"])
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("ORDER BY key", statement)
        self.assertEqual(params, ("users",))

        self.fake.next_rows = [("alice", {"n": 1}), ("bob", [2])]
        self.assertEqual(
            driver.items("users"),
            {"alice": {"n": 1}, "bob": [2]},
        )
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("SELECT key, value", statement)
        self.assertIn("ORDER BY key", statement)
        self.assertEqual(params, ("users",))

    def test_database_wrapper_validates_before_connecting(self) -> None:
        store = db.Database(self.driver())
        with self.assertRaisesRegex(db.DatabaseError, "collection"):
            store.get("no/slashes", "key")
        with self.assertRaisesRegex(db.DatabaseError, "JSON-serializable"):
            store.put("users", "alice", object())
        self.assertEqual(self.fake.connections, [])

    def test_connection_and_query_errors_are_wrapped(self) -> None:
        driver = self.driver()
        self.fake.connect_error = OSError("offline")
        with self.assertRaisesRegex(db.DatabaseError, "offline") as raised:
            driver.get("users", "alice")
        self.assertNotIn(driver._conninfo, str(raised.exception))

        self.fake.connect_error = None
        self.fake.execute_error = RuntimeError("query failed")
        with self.assertRaisesRegex(db.DatabaseError, "query failed"):
            driver.keys("users")
        self.assertTrue(self.fake.connections[-1].closed)


if __name__ == "__main__":
    unittest.main()

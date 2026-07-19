from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "files" / "core" / "_store_postgres.py"


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exception: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.connection.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        if self.connection.rows:
            return self.connection.rows.pop(0)
        return None


class FakeConnection:
    def __init__(self, module: "FakePsycopg") -> None:
        self.module = module
        self.executed: list[tuple[str, tuple | None]] = []
        self.rows: list[tuple] = []
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

    def connect(self, conninfo: str) -> FakeConnection:
        self.conninfos.append(conninfo)
        connection = FakeConnection(self)
        connection.rows = list(self.next_rows)
        self.next_rows = []
        self.connections.append(connection)
        return connection


def _load_store_module():
    spec = importlib.util.spec_from_file_location(
        "sykit_test_store_postgres", STORE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostgresStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_store_module()
        self.fake = FakePsycopg()
        patcher = mock.patch.dict(sys.modules, {"psycopg": self.fake})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sql(self, connection: FakeConnection) -> list[str]:
        return [statement for statement, _params in connection.executed]

    def test_create_uses_target_then_environment(self) -> None:
        store = self.module.create("dbname=app user=sykit")
        store.delete("sid")
        self.assertEqual(self.fake.conninfos, ["dbname=app user=sykit"])

        with mock.patch.dict(
            "os.environ", {self.module.DSN_ENV: "postgresql://db/app"}
        ):
            store = self.module.create("")
            store.delete("sid")
        self.assertEqual(self.fake.conninfos[-1], "postgresql://db/app")

        with mock.patch.dict("os.environ", {self.module.DSN_ENV: ""}):
            with self.assertRaisesRegex(RuntimeError, self.module.DSN_ENV):
                self.module.create("")

    def test_missing_psycopg_says_how_to_install(self) -> None:
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with self.assertRaisesRegex(RuntimeError, "pip install"):
                self.module.create("dbname=app")

    def test_schema_is_created_once(self) -> None:
        store = self.module.create("dbname=app")
        store.delete("sid-1")
        store.delete("sid-2")
        first, second = self.fake.connections
        self.assertIn("CREATE TABLE IF NOT EXISTS sykit_sessions", self._sql(first)[0])
        self.assertNotIn("CREATE TABLE", " ".join(self._sql(second)))

    def test_load_roundtrip_expiry_and_shape(self) -> None:
        store = self.module.create("dbname=app")
        future = int(time.time()) + 600

        self.fake.next_rows = [(json.dumps({"role": "admin"}), future)]
        self.assertEqual(store.load("sid"), {"role": "admin"})

        self.fake.next_rows = [(json.dumps({"role": "admin"}), 1)]
        self.assertIsNone(store.load("sid"))
        expired_connection = self.fake.connections[-1]
        self.assertIn(
            "DELETE FROM sykit_sessions WHERE session_id = %s",
            self._sql(expired_connection),
        )

        self.fake.next_rows = []
        self.assertIsNone(store.load("missing"))

        self.fake.next_rows = [(json.dumps(["not", "a", "dict"]), future)]
        self.assertIsNone(store.load("sid"))

    def test_save_upserts_and_cleans_up(self) -> None:
        store = self.module.create("dbname=app")
        before = int(time.time())
        store.save("sid", {"role": "admin"}, 600)
        connection = self.fake.connections[-1]
        statement, params = connection.executed[-2]
        self.assertIn("ON CONFLICT (session_id) DO UPDATE", statement)
        self.assertEqual(params[0], "sid")
        self.assertEqual(json.loads(params[1]), {"role": "admin"})
        self.assertGreaterEqual(params[2], before + 600)
        cleanup, _ = connection.executed[-1]
        self.assertIn("DELETE FROM sykit_sessions WHERE expires <", cleanup)
        self.assertTrue(connection.committed)

        store.save("sid", {"role": "user"}, 600)
        second = self.fake.connections[-1]
        self.assertNotIn("expires <", " ".join(self._sql(second)))

    def test_touch_and_delete(self) -> None:
        store = self.module.create("dbname=app")
        before = int(time.time())
        store.touch("sid", 900)
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("UPDATE sykit_sessions SET expires = %s", statement)
        self.assertGreaterEqual(params[0], before + 900)
        self.assertEqual(params[1], "sid")

        store.delete("sid")
        statement, params = self.fake.connections[-1].executed[-1]
        self.assertIn("DELETE FROM sykit_sessions WHERE session_id = %s", statement)
        self.assertEqual(params, ("sid",))

    def test_resolve_store_convention_loads_this_file(self) -> None:
        sessions_spec = importlib.util.spec_from_file_location(
            "sykit_test_sessions_pg", ROOT / "files" / "core" / "_sessions.py"
        )
        sessions = importlib.util.module_from_spec(sessions_spec)
        sessions_spec.loader.exec_module(sessions)

        with tempfile.TemporaryDirectory(prefix="sykit-pg-store-") as directory:
            core = Path(directory) / "core"
            core.mkdir()
            (core / "__init__.py").write_text("", encoding="utf-8")
            shutil.copy2(STORE_PATH, core / "_store_postgres.py")
            sys.path.insert(0, directory)
            try:
                store = sessions.resolve_store("postgres:dbname=live", Path(directory))
                store.delete("sid")
                self.assertEqual(self.fake.conninfos[-1], "dbname=live")
            finally:
                sys.path.remove(directory)
                for name in [
                    name
                    for name in sys.modules
                    if name == "core" or name.startswith("core.")
                ]:
                    del sys.modules[name]


if __name__ == "__main__":
    unittest.main()

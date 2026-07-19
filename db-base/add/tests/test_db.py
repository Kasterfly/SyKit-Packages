from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from sykit import db


class SqliteRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sykit-db-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name) / "test.db")

    def test_put_get_delete_roundtrip(self) -> None:
        with db.connect(self.path) as store:
            self.assertIsNone(store.get("users", "alice"))
            self.assertEqual(store.get("users", "alice", default={}), {})
            store.put("users", "alice", {"role": "admin", "logins": 3})
            self.assertEqual(
                store.get("users", "alice"), {"role": "admin", "logins": 3}
            )
            store.put("users", "alice", {"role": "viewer"})
            self.assertEqual(store.get("users", "alice"), {"role": "viewer"})
            self.assertTrue(store.delete("users", "alice"))
            self.assertFalse(store.delete("users", "alice"))
            self.assertIsNone(store.get("users", "alice"))

    def test_keys_and_items_are_per_collection(self) -> None:
        with db.connect(self.path) as store:
            store.put("users", "alice", 1)
            store.put("users", "bob", 2)
            store.put("posts", "first", {"title": "Hi"})
            self.assertEqual(store.keys("users"), ["alice", "bob"])
            self.assertEqual(store.items("users"), {"alice": 1, "bob": 2})
            self.assertEqual(store.keys("posts"), ["first"])
            self.assertEqual(store.keys("empty"), [])

    def test_values_persist_across_reconnect(self) -> None:
        with db.connect(self.path) as store:
            store.put("config", "flags", ["a", "b", None, 4.5, True])
        with db.connect("sqlite:" + self.path) as store:
            self.assertEqual(store.get("config", "flags"), ["a", "b", None, 4.5, True])

    def test_invalid_names_and_values_raise(self) -> None:
        with db.connect(self.path) as store:
            with self.assertRaisesRegex(db.DatabaseError, "collection"):
                store.get("no/slashes", "key")
            with self.assertRaisesRegex(db.DatabaseError, "keys must"):
                store.get("users", "")
            with self.assertRaisesRegex(db.DatabaseError, "keys must"):
                store.get("users", "x" * (db.MAX_KEY_LENGTH + 1))
            with self.assertRaisesRegex(db.DatabaseError, "JSON-serializable"):
                store.put("users", "alice", object())


class DriverDispatchTests(unittest.TestCase):
    def test_unknown_scheme_raises_with_known_drivers(self) -> None:
        # The scheme must be one no provider package will ever register;
        # connect() also tries to import sykit.<scheme> before giving up.
        with self.assertRaisesRegex(db.DatabaseError, "sqlite"):
            db.connect("nosuchdriver:target")

    def test_single_letter_scheme_is_a_windows_path(self) -> None:
        # A drive-letter path must not be mistaken for a driver scheme; a
        # nonexistent drive fails as a database path, not as an unknown
        # driver.
        try:
            store = db.connect(r"Q:\definitely\missing\dir\x.db")
        except db.DatabaseError as error:
            self.assertNotIn("Unknown database driver", str(error))
        else:
            store.close()

    def test_registered_driver_receives_target(self) -> None:
        calls: dict[str, object] = {}

        class FakeDriver:
            def __init__(self, target: str) -> None:
                calls["target"] = target
                self.data: dict[tuple[str, str], object] = {}

            def get(self, collection, key):
                return self.data.get((collection, key))

            def put(self, collection, key, value):
                self.data[(collection, key)] = value

            def delete(self, collection, key):
                return self.data.pop((collection, key), None) is not None

            def keys(self, collection):
                return [key for (name, key) in self.data if name == collection]

            def items(self, collection):
                return {
                    key: value
                    for (name, key), value in self.data.items()
                    if name == collection
                }

            def close(self):
                calls["closed"] = True

        db.register_driver("fake-test", FakeDriver)
        try:
            with db.connect("fake-test:some-target") as store:
                store.put("users", "alice", {"ok": True})
                self.assertEqual(store.get("users", "alice"), {"ok": True})
                self.assertEqual(store.keys("users"), ["alice"])
            self.assertEqual(calls["target"], "some-target")
            self.assertTrue(calls["closed"])
        finally:
            db._DRIVERS.pop("fake-test", None)

    def test_register_driver_validates_input(self) -> None:
        with self.assertRaises(db.DatabaseError):
            db.register_driver("bad scheme", lambda target: None)
        with self.assertRaises(db.DatabaseError):
            db.register_driver("okname", "not-callable")

    def test_connect_auto_imports_provider_module(self) -> None:
        import sykit

        with tempfile.TemporaryDirectory(prefix="sykit-db-provider-") as directory:
            (Path(directory) / "autodrv.py").write_text(
                textwrap.dedent(
                    """
                    from sykit import db


                    class AutoDriver:
                        def __init__(self, target):
                            self.target = target
                            self.data = {}

                        def get(self, collection, key):
                            return self.data.get((collection, key))

                        def put(self, collection, key, value):
                            self.data[(collection, key)] = value

                        def delete(self, collection, key):
                            return self.data.pop((collection, key), None) is not None

                        def keys(self, collection):
                            return sorted(
                                key for (name, key) in self.data if name == collection
                            )

                        def items(self, collection):
                            return {
                                key: value
                                for (name, key), value in self.data.items()
                                if name == collection
                            }

                        def close(self):
                            pass


                    db.register_driver("autodrv", AutoDriver)
                    """
                ),
                encoding="utf-8",
            )
            sykit.__path__.append(directory)
            try:
                with db.connect("autodrv:target-text") as store:
                    store.put("users", "alice", {"ok": True})
                    self.assertEqual(store.get("users", "alice"), {"ok": True})
                self.assertEqual(store._driver.target, "target-text")
            finally:
                sykit.__path__.remove(directory)
                sys.modules.pop("sykit.autodrv", None)
                db._DRIVERS.pop("autodrv", None)


if __name__ == "__main__":
    unittest.main()

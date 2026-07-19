from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from sykit import db, supabase

ENVIRONMENT = {
    supabase.URL_ENV: "https://project.supabase.co",
    supabase.KEY_ENV: "service-role-key",
}


def driver(target: str = "") -> supabase.SupabaseDriver:
    with mock.patch.dict("os.environ", ENVIRONMENT):
        return supabase.SupabaseDriver(target)


class ConfigurationTests(unittest.TestCase):
    def test_scheme_is_registered_and_connect_dispatches(self) -> None:
        self.assertIn("supabase", db._DRIVERS)
        with mock.patch.dict("os.environ", ENVIRONMENT):
            store = db.connect("supabase:")
        self.assertEqual(
            store._driver._endpoint,
            "https://project.supabase.co/rest/v1/sykit_documents",
        )
        store.close()

    def test_target_selects_the_table(self) -> None:
        self.assertTrue(driver("notes")._endpoint.endswith("/rest/v1/notes"))

    def test_invalid_tables_and_missing_configuration_raise(self) -> None:
        with self.assertRaisesRegex(db.DatabaseError, "table names"):
            driver("bad-table!")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(db.DatabaseError, supabase.URL_ENV):
                supabase.SupabaseDriver("")
        with mock.patch.dict(
            "os.environ",
            {**ENVIRONMENT, supabase.URL_ENV: "http://plain.example"},
        ):
            with self.assertRaisesRegex(db.DatabaseError, "https"):
                supabase.SupabaseDriver("")

    def test_explicit_arguments_beat_environment(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            instance = supabase.SupabaseDriver(
                "notes", url="https://other.supabase.co/", key="k2"
            )
        self.assertEqual(instance._endpoint, "https://other.supabase.co/rest/v1/notes")
        self.assertEqual(instance._headers["apikey"], "k2")


class RequestTranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = driver()

    def test_get_translates_and_unwraps(self) -> None:
        with mock.patch.object(
            self.driver, "_request", return_value=[{"value": {"role": "admin"}}]
        ) as request:
            self.assertEqual(self.driver.get("users", "alice"), {"role": "admin"})
        request.assert_called_once_with(
            "GET", "collection=eq.users&key=eq.alice&select=value"
        )
        with mock.patch.object(self.driver, "_request", return_value=[]):
            self.assertIsNone(self.driver.get("users", "missing"))

    def test_filters_are_url_quoted(self) -> None:
        with mock.patch.object(self.driver, "_request", return_value=[]) as request:
            self.driver.get("users", "a,b c&d=e/f")
        query = request.call_args[0][1]
        self.assertIn("key=eq.a%2Cb%20c%26d%3De%2Ff", query)

    def test_put_upserts(self) -> None:
        with mock.patch.object(self.driver, "_request", return_value=[]) as request:
            self.driver.put("users", "alice", {"n": 1})
        request.assert_called_once_with(
            "POST",
            "on_conflict=collection,key",
            payload=[{"collection": "users", "key": "alice", "value": {"n": 1}}],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def test_delete_reports_whether_rows_existed(self) -> None:
        with mock.patch.object(
            self.driver, "_request", return_value=[{"key": "alice"}]
        ) as request:
            self.assertTrue(self.driver.delete("users", "alice"))
        request.assert_called_once_with(
            "DELETE",
            "collection=eq.users&key=eq.alice",
            prefer="return=representation",
        )
        with mock.patch.object(self.driver, "_request", return_value=[]):
            self.assertFalse(self.driver.delete("users", "alice"))

    def test_keys_and_items_paginate(self) -> None:
        full_page = [
            {"key": f"k{index:04}", "value": index}
            for index in range(supabase.PAGE_SIZE)
        ]
        short_page = [{"key": "last", "value": -1}]
        with mock.patch.object(
            self.driver, "_request", side_effect=[full_page, short_page]
        ) as request:
            items = self.driver.items("users")
        self.assertEqual(len(items), supabase.PAGE_SIZE + 1)
        self.assertEqual(items["last"], -1)
        self.assertEqual(request.call_count, 2)
        first, second = request.call_args_list
        self.assertEqual(first.kwargs["page"], (0, supabase.PAGE_SIZE - 1))
        self.assertEqual(
            second.kwargs["page"], (supabase.PAGE_SIZE, 2 * supabase.PAGE_SIZE - 1)
        )

    def test_database_wrapper_validates_before_the_driver_runs(self) -> None:
        store = db.Database(self.driver)
        with mock.patch.object(self.driver, "_request") as request:
            with self.assertRaisesRegex(db.DatabaseError, "collection"):
                store.get("no/slashes", "key")
            with self.assertRaisesRegex(db.DatabaseError, "JSON-serializable"):
                store.put("users", "alice", object())
        request.assert_not_called()


class TransportErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = driver()

    def test_http_errors_wrap_with_postgrest_message(self) -> None:
        error = urllib.error.HTTPError(
            "https://project.supabase.co/rest/v1/sykit_documents",
            401,
            "Unauthorized",
            None,
            io.BytesIO(json.dumps({"message": "JWT expired"}).encode("utf-8")),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(db.DatabaseError, "HTTP 401: JWT expired"):
                self.driver.get("users", "alice")

    def test_network_errors_wrap(self) -> None:
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("refused"),
        ):
            with self.assertRaisesRegex(db.DatabaseError, "Could not reach"):
                self.driver.get("users", "alice")

    def test_invalid_json_wraps(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"not json"
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(db.DatabaseError, "invalid JSON"):
                self.driver.get("users", "alice")


if __name__ == "__main__":
    unittest.main()

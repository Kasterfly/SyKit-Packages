from __future__ import annotations

import unittest
from unittest import mock

from sykit import textbelt


class SendSmsTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict("os.environ", {textbelt.API_KEY_ENV: ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_posts_expected_payload(self) -> None:
        response = {"success": True, "textId": "12345", "quotaRemaining": 40}
        with mock.patch.object(
            textbelt, "_request_json", return_value=response
        ) as request:
            result = textbelt.send_sms(
                " +15551234567 ", "Hello there", api_key="test-key"
            )
        self.assertEqual(result, response)
        (url, payload, timeout), _ = request.call_args
        self.assertEqual(url, textbelt.SEND_URL)
        self.assertEqual(
            payload,
            {"phone": "+15551234567", "message": "Hello there", "key": "test-key"},
        )
        self.assertEqual(timeout, textbelt.DEFAULT_TIMEOUT)

    def test_environment_provides_key(self) -> None:
        with mock.patch.dict("os.environ", {textbelt.API_KEY_ENV: "env-key"}):
            with mock.patch.object(
                textbelt, "_request_json", return_value={"success": True}
            ) as request:
                textbelt.send_sms("+15551234567", "Hi")
        (_, payload, _), _ = request.call_args
        self.assertEqual(payload["key"], "env-key")

    def test_missing_key_and_invalid_arguments_raise(self) -> None:
        with self.assertRaisesRegex(textbelt.TextBeltError, textbelt.API_KEY_ENV):
            textbelt.send_sms("+15551234567", "Hi")
        with self.assertRaisesRegex(textbelt.TextBeltError, "phone"):
            textbelt.send_sms("  ", "Hi", api_key="k")
        with self.assertRaisesRegex(textbelt.TextBeltError, "message"):
            textbelt.send_sms("+15551234567", "", api_key="k")

    def test_unsuccessful_send_raises_with_api_error(self) -> None:
        response = {"success": False, "error": "Out of quota"}
        with mock.patch.object(textbelt, "_request_json", return_value=response):
            with self.assertRaisesRegex(textbelt.TextBeltError, "Out of quota"):
                textbelt.send_sms("+15551234567", "Hi", api_key="k")


class StatusAndQuotaTests(unittest.TestCase):
    def test_status_uses_get_and_returns_status(self) -> None:
        with mock.patch.object(
            textbelt, "_request_json", return_value={"status": "DELIVERED"}
        ) as request:
            status = textbelt.sms_status("abc 123")
        self.assertEqual(status, "DELIVERED")
        (url, payload, _), _ = request.call_args
        self.assertEqual(url, textbelt.STATUS_URL + "abc%20123")
        self.assertIsNone(payload)

    def test_quota_returns_remaining(self) -> None:
        with mock.patch.object(
            textbelt, "_request_json", return_value={"quotaRemaining": 7}
        ) as request:
            remaining = textbelt.quota(api_key="my/key")
        self.assertEqual(remaining, 7)
        (url, _, _), _ = request.call_args
        self.assertEqual(url, textbelt.QUOTA_URL + "my%2Fkey")

    def test_missing_fields_raise(self) -> None:
        with mock.patch.object(textbelt, "_request_json", return_value={}):
            with self.assertRaisesRegex(textbelt.TextBeltError, "no status"):
                textbelt.sms_status("abc")
            with self.assertRaisesRegex(textbelt.TextBeltError, "no quota"):
                textbelt.quota(api_key="k")


if __name__ == "__main__":
    unittest.main()

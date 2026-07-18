from __future__ import annotations

import unittest
from unittest import mock

from sykit import resend


class SendEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(
            "os.environ",
            {resend.API_KEY_ENV: "", resend.FROM_ENV: ""},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, **overrides):
        arguments = {
            "to": "user@example.com",
            "subject": "Hello",
            "text": "Body",
            "api_key": "test-key",
            "from_address": "App <app@example.com>",
        }
        arguments.update(overrides)
        return resend.send_email(**arguments)

    def test_posts_expected_payload_and_headers(self) -> None:
        with mock.patch.object(
            resend, "_post_json", return_value={"id": "email-1"}
        ) as post:
            result = self.send(cc=["copy@example.com"], reply_to="reply@example.com")
        self.assertEqual(result, {"id": "email-1"})
        (url, payload, headers, timeout), _ = post.call_args
        self.assertEqual(url, resend.API_URL)
        self.assertEqual(headers, {"Authorization": "Bearer test-key"})
        self.assertEqual(timeout, resend.DEFAULT_TIMEOUT)
        self.assertEqual(payload["from"], "App <app@example.com>")
        self.assertEqual(payload["to"], ["user@example.com"])
        self.assertEqual(payload["subject"], "Hello")
        self.assertEqual(payload["text"], "Body")
        self.assertEqual(payload["cc"], ["copy@example.com"])
        self.assertEqual(payload["reply_to"], ["reply@example.com"])
        self.assertNotIn("html", payload)
        self.assertNotIn("bcc", payload)

    def test_environment_provides_key_and_sender(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {resend.API_KEY_ENV: "env-key", resend.FROM_ENV: "env@example.com"},
        ):
            with mock.patch.object(
                resend, "_post_json", return_value={"id": "email-2"}
            ) as post:
                resend.send_email("user@example.com", "Hi", text="Body")
        (_, payload, headers, _), _ = post.call_args
        self.assertEqual(headers, {"Authorization": "Bearer env-key"})
        self.assertEqual(payload["from"], "env@example.com")

    def test_missing_key_sender_body_and_subject_raise(self) -> None:
        with self.assertRaisesRegex(resend.ResendError, resend.API_KEY_ENV):
            self.send(api_key=None)
        with self.assertRaisesRegex(resend.ResendError, resend.FROM_ENV):
            self.send(from_address=None)
        with self.assertRaisesRegex(resend.ResendError, "text and/or html"):
            self.send(text=None)
        with self.assertRaisesRegex(resend.ResendError, "subject"):
            self.send(subject="   ")

    def test_invalid_recipients_raise(self) -> None:
        for bad in ("", [], ["ok@example.com", ""], 42):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(resend.ResendError, "to must be"):
                    self.send(to=bad)

    def test_api_error_is_wrapped(self) -> None:
        with mock.patch.object(
            resend,
            "_post_json",
            side_effect=resend.ResendError("Resend API returned HTTP 401"),
        ):
            with self.assertRaisesRegex(resend.ResendError, "HTTP 401"):
                self.send()


if __name__ == "__main__":
    unittest.main()

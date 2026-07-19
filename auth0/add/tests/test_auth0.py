from __future__ import annotations

import unittest
import urllib.parse
from unittest import mock

from sykit import auth0, utils

ENVIRONMENT = {
    auth0.DOMAIN_ENV: "tenant.us.auth0.com",
    auth0.CLIENT_ID_ENV: "client-123",
    auth0.CLIENT_SECRET_ENV: "secret-456",
    auth0.CALLBACK_ENV: "https://app.example.com/auth0",
}

PROFILE = {"sub": "auth0|abc", "email": "ada@example.com"}


class BeginTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict("os.environ", ENVIRONMENT)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session: dict[str, object] = {}
        token = utils._bind_session(self.session)
        self.addCleanup(utils._reset_session, token)

    def test_begin_builds_authorize_url_and_stores_state(self) -> None:
        url = auth0.begin()
        parsed = urllib.parse.urlsplit(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "tenant.us.auth0.com")
        self.assertEqual(parsed.path, "/authorize")
        query = dict(urllib.parse.parse_qsl(parsed.query))
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], "client-123")
        self.assertEqual(query["redirect_uri"], "https://app.example.com/auth0")
        self.assertEqual(query["scope"], auth0.DEFAULT_SCOPE)
        self.assertEqual(query["state"], self.session[auth0.STATE_KEY])
        self.assertNotIn("audience", query)

    def test_begin_honors_audience_and_connection(self) -> None:
        url = auth0.begin(audience="https://api.example.com", connection="github")
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual(query["audience"], "https://api.example.com")
        self.assertEqual(query["connection"], "github")

    def test_domain_accepts_scheme_and_rejects_garbage(self) -> None:
        with mock.patch.dict(
            "os.environ", {auth0.DOMAIN_ENV: "https://tenant.us.auth0.com/"}
        ):
            self.assertIn("tenant.us.auth0.com/authorize", auth0.begin())
        with mock.patch.dict("os.environ", {auth0.DOMAIN_ENV: "not a domain!"}):
            with self.assertRaisesRegex(auth0.Auth0Error, "bare domain"):
                auth0.begin()

    def test_missing_configuration_names_the_variable(self) -> None:
        with mock.patch.dict("os.environ", {auth0.CLIENT_ID_ENV: ""}):
            with self.assertRaisesRegex(auth0.Auth0Error, auth0.CLIENT_ID_ENV):
                auth0.begin()


class CompleteTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict("os.environ", ENVIRONMENT)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session: dict[str, object] = {auth0.STATE_KEY: "expected-state"}
        token = utils._bind_session(self.session)
        self.addCleanup(utils._reset_session, token)

    def test_complete_exchanges_code_and_returns_profile(self) -> None:
        responses = [{"access_token": "token-789"}, PROFILE]
        with mock.patch.object(
            auth0, "_request_json", side_effect=responses
        ) as request:
            profile = auth0.complete("expected-state", "the-code")
        self.assertEqual(profile, PROFILE)
        self.assertNotIn(auth0.STATE_KEY, self.session)
        exchange, userinfo = request.call_args_list
        self.assertEqual(exchange.args[0], "https://tenant.us.auth0.com/oauth/token")
        self.assertEqual(
            exchange.kwargs["payload"],
            {
                "grant_type": "authorization_code",
                "client_id": "client-123",
                "client_secret": "secret-456",
                "code": "the-code",
                "redirect_uri": "https://app.example.com/auth0",
            },
        )
        self.assertEqual(userinfo.args[0], "https://tenant.us.auth0.com/userinfo")
        self.assertEqual(userinfo.kwargs["bearer"], "token-789")

    def test_state_mismatch_or_missing_state_raises(self) -> None:
        with mock.patch.object(auth0, "_request_json") as request:
            with self.assertRaisesRegex(auth0.Auth0Error, "state"):
                auth0.complete("wrong-state", "the-code")
            with self.assertRaisesRegex(auth0.Auth0Error, "state"):
                auth0.complete("expected-state", "the-code")
        request.assert_not_called()

    def test_state_is_single_use(self) -> None:
        responses = [{"access_token": "token-789"}, PROFILE]
        with mock.patch.object(auth0, "_request_json", side_effect=responses):
            auth0.complete("expected-state", "the-code")
        with self.assertRaisesRegex(auth0.Auth0Error, "state"):
            auth0.complete("expected-state", "the-code")

    def test_missing_token_or_profile_raises(self) -> None:
        with mock.patch.object(auth0, "_request_json", return_value={}):
            with self.assertRaisesRegex(auth0.Auth0Error, "access token"):
                auth0.complete("expected-state", "the-code")
        self.session[auth0.STATE_KEY] = "expected-state"
        with mock.patch.object(
            auth0, "_request_json", side_effect=[{"access_token": "t"}, {}]
        ):
            with self.assertRaisesRegex(auth0.Auth0Error, "profile"):
                auth0.complete("expected-state", "the-code")

    def test_invalid_arguments_raise(self) -> None:
        with self.assertRaisesRegex(auth0.Auth0Error, "state and code"):
            auth0.complete("expected-state", "")
        with self.assertRaisesRegex(auth0.Auth0Error, "state and code"):
            auth0.complete(None, "code")


if __name__ == "__main__":
    unittest.main()

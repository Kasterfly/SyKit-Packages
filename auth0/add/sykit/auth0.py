"""Log SyKit users in through Auth0 (https://auth0.com).

Standard library only. Wraps the Authorization Code flow for a
server-side (confidential) client: begin() returns the Auth0 URL to
send the browser to, Auth0 redirects back to your callback page with
?code=&state=, the page posts both to an endpoint, and complete()
exchanges them for the user's profile, which you log into the SyKit
session with sykit.auth.

Environment (with SyKit's "use-dotenv" they can live in .env):

    SYKIT_AUTH0_DOMAIN         your-tenant.us.auth0.com (no scheme)
    SYKIT_AUTH0_CLIENT_ID      the application's client id
    SYKIT_AUTH0_CLIENT_SECRET  the application's client secret
    SYKIT_AUTH0_CALLBACK       the URL Auth0 redirects back to

Usage from endpoints:

    from sykit import auth, auth0
    from sykit.utils import expose, limits

    @expose("auth0_start")
    def auth0_start():
        return {"redirect": auth0.begin()}

    @expose("auth0_finish")
    @limits({"per-client": "10m"})
    def auth0_finish(state: str, code: str):
        profile = auth0.complete(state, code)
        auth.login({"user": profile["sub"], "role": "user"})
        return {"ok": True}

The callback page forwards its query parameters:

    const params = new URLSearchParams(window.location.search);
    await auth0_finish(params.get("state"), params.get("code"));

The profile is Auth0's /userinfo response ("sub", and depending on
scope "email", "name", ...). Decide the session claims yourself; do not
copy the whole profile into the session blindly.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sykit.utils import _session

DOMAIN_ENV = "SYKIT_AUTH0_DOMAIN"
CLIENT_ID_ENV = "SYKIT_AUTH0_CLIENT_ID"
CLIENT_SECRET_ENV = "SYKIT_AUTH0_CLIENT_SECRET"
CALLBACK_ENV = "SYKIT_AUTH0_CALLBACK"
DEFAULT_SCOPE = "openid profile email"
DEFAULT_TIMEOUT = 15
STATE_KEY = "_auth0_state"
DOMAIN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{2,253}")


class Auth0Error(RuntimeError):
    """A failed Auth0 call or an invalid login attempt."""


def _setting(name: str, override: str | None = None) -> str:
    value = (override or os.environ.get(name, "")).strip()
    if not value:
        raise Auth0Error(f"Auth0 is not configured; set {name}.")
    return value


def _domain() -> str:
    value = _setting(DOMAIN_ENV)
    if value.lower().startswith("https://"):
        value = value[len("https://") :]
    value = value.rstrip("/")
    if not DOMAIN_PATTERN.fullmatch(value) or "/" in value:
        raise Auth0Error(
            f"{DOMAIN_ENV} must be a bare domain like your-tenant.us.auth0.com."
        )
    return value


def _request_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    bearer: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    headers: dict[str, str] = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            parsed = json.loads(error.read().decode("utf-8", "replace"))
            if isinstance(parsed, dict):
                detail = str(
                    parsed.get("error_description", "") or parsed.get("error", "")
                )
        except (OSError, ValueError):
            pass
        message = f"Auth0 returned HTTP {error.code}"
        if detail:
            message += f": {detail}"
        raise Auth0Error(message) from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise Auth0Error(f"Could not reach Auth0: {error}") from error
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise Auth0Error(f"Auth0 returned invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise Auth0Error("Auth0 returned an unexpected response.")
    return value


def begin(
    *,
    scope: str = DEFAULT_SCOPE,
    audience: str = "",
    connection: str = "",
) -> str:
    """Start a login: returns the Auth0 URL to redirect the browser to.

    Stores a random state value in the visitor's session; complete()
    checks it. Call from an endpoint (a session must be active).
    """
    domain = _domain()
    state = secrets.token_urlsafe(32)
    _session()[STATE_KEY] = state
    parameters = {
        "response_type": "code",
        "client_id": _setting(CLIENT_ID_ENV),
        "redirect_uri": _setting(CALLBACK_ENV),
        "scope": scope,
        "state": state,
    }
    if audience:
        parameters["audience"] = audience
    if connection:
        parameters["connection"] = connection
    return f"https://{domain}/authorize?" + urllib.parse.urlencode(parameters)


def complete(
    state: str,
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Finish a login: verify the state, exchange the code, return the profile.

    Raises Auth0Error when the state does not match the session (restart
    the flow) or when Auth0 rejects the exchange. Log the returned
    profile into the session with sykit.auth.login().
    """
    if not isinstance(state, str) or not isinstance(code, str) or not code:
        raise Auth0Error("complete() needs the state and code query parameters.")
    session = _session()
    expected = session.pop(STATE_KEY, "")
    if (
        not isinstance(expected, str)
        or not expected
        or not hmac.compare_digest(expected, state)
    ):
        raise Auth0Error(
            "The login state does not match this session; restart the login flow."
        )
    domain = _domain()
    tokens = _request_json(
        f"https://{domain}/oauth/token",
        payload={
            "grant_type": "authorization_code",
            "client_id": _setting(CLIENT_ID_ENV),
            "client_secret": _setting(CLIENT_SECRET_ENV),
            "code": code,
            "redirect_uri": _setting(CALLBACK_ENV),
        },
        timeout=timeout,
    )
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise Auth0Error("Auth0 did not return an access token.")
    profile = _request_json(
        f"https://{domain}/userinfo",
        bearer=access_token,
        timeout=timeout,
    )
    if not isinstance(profile.get("sub"), str) or not profile["sub"]:
        raise Auth0Error("Auth0 did not return a user profile.")
    return profile


__all__ = ["Auth0Error", "begin", "complete"]

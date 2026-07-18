"""Send SMS through the TextBelt API (https://textbelt.com).

Standard library only. The API key comes from the TEXTBELT_API_KEY
environment variable (or the api_key argument); with SyKit's "use-dotenv"
setting it can live in the project .env file. TextBelt's free tier accepts
the literal key "textbelt" for one message per day.

Usage from an endpoint:

    from sykit.textbelt import send_sms

    @expose("alert")
    def alert(session: dict, message: str):
        result = send_sms("+15551234567", message)
        return {"sent": True, "quota": result["quotaRemaining"]}
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SEND_URL = "https://textbelt.com/text"
STATUS_URL = "https://textbelt.com/status/"
QUOTA_URL = "https://textbelt.com/quota/"
API_KEY_ENV = "TEXTBELT_API_KEY"
DEFAULT_TIMEOUT = 15


class TextBeltError(RuntimeError):
    """A failed TextBelt API call or an invalid request."""


def _request_json(
    url: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise TextBeltError(f"The TextBelt API returned HTTP {error.code}.") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise TextBeltError(f"Could not reach the TextBelt API: {error}") from error
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise TextBeltError(
            f"The TextBelt API returned invalid JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise TextBeltError("The TextBelt API returned an unexpected response.")
    return value


def _key(api_key: str | None) -> str:
    key = api_key or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise TextBeltError(f"No API key; pass api_key or set {API_KEY_ENV}.")
    return key


def send_sms(
    phone: str,
    message: str,
    *,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send an SMS and return the TextBelt response.

    The response contains "textId" (for sms_status) and "quotaRemaining".
    Raises TextBeltError on invalid arguments, transport failures, and
    when TextBelt reports the send failed.
    """
    if not isinstance(phone, str) or not phone.strip():
        raise TextBeltError("phone must be a non-empty string.")
    if not isinstance(message, str) or not message.strip():
        raise TextBeltError("message must be a non-empty string.")
    payload = {
        "phone": phone.strip(),
        "message": message,
        "key": _key(api_key),
    }
    result = _request_json(SEND_URL, payload, timeout)
    if not result.get("success"):
        raise TextBeltError(
            f"TextBelt did not accept the message: "
            f"{result.get('error', 'unknown error')}"
        )
    return result


def sms_status(
    text_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Return the delivery status of a sent message (for example DELIVERED)."""
    if not isinstance(text_id, str) or not text_id.strip():
        raise TextBeltError("text_id must be a non-empty string.")
    result = _request_json(
        STATUS_URL + urllib.parse.quote(text_id.strip(), safe=""), None, timeout
    )
    status = result.get("status")
    if not isinstance(status, str):
        raise TextBeltError("The TextBelt API returned no status.")
    return status


def quota(
    api_key: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """Return how many messages remain on the API key's quota."""
    key = _key(api_key)
    result = _request_json(QUOTA_URL + urllib.parse.quote(key, safe=""), None, timeout)
    remaining = result.get("quotaRemaining")
    if not isinstance(remaining, int):
        raise TextBeltError("The TextBelt API returned no quota information.")
    return remaining

"""Send email through the Resend API (https://resend.com).

Standard library only. The API key comes from the RESEND_API_KEY
environment variable (or the api_key argument), and the default sender
from RESEND_FROM; with SyKit's "use-dotenv" setting both can live in the
project .env file.

Usage from an endpoint:

    from sykit.resend import send_email

    @expose("contact")
    def contact(session: dict, message: str):
        send_email(
            to="owner@example.com",
            subject="New contact message",
            text=message,
        )
        return {"sent": True}
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

API_URL = "https://api.resend.com/emails"
API_KEY_ENV = "RESEND_API_KEY"
FROM_ENV = "RESEND_FROM"
DEFAULT_TIMEOUT = 15


class ResendError(RuntimeError):
    """A failed Resend API call or an invalid request."""


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            raw = error.read().decode("utf-8", "replace")
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                detail = str(parsed.get("message", ""))
        except (OSError, ValueError):
            pass
        message = f"Resend API returned HTTP {error.code}"
        if detail:
            message += f": {detail}"
        raise ResendError(message) from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ResendError(f"Could not reach the Resend API: {error}") from error
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ResendError(f"The Resend API returned invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ResendError("The Resend API returned an unexpected response.")
    return value


def _recipients(value: Any, label: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(entry, str) and entry.strip() for entry in value)
    ):
        raise ResendError(
            f"{label} must be an email address or a non-empty list of them."
        )
    return [entry.strip() for entry in value]


def send_email(
    to: str | list[str],
    subject: str,
    *,
    text: str | None = None,
    html: str | None = None,
    from_address: str | None = None,
    reply_to: str | list[str] | None = None,
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send an email and return the Resend response (contains the id).

    Provide text and/or html for the body. Raises ResendError on invalid
    arguments, transport failures, and API errors.
    """
    key = api_key or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ResendError(f"No API key; pass api_key or set {API_KEY_ENV}.")
    sender = from_address or os.environ.get(FROM_ENV, "")
    if not sender:
        raise ResendError(
            f"No sender; pass from_address or set {FROM_ENV} "
            '(for example "My App <app@yourdomain.com>").'
        )
    if not isinstance(subject, str) or not subject.strip():
        raise ResendError("subject must be a non-empty string.")
    if text is None and html is None:
        raise ResendError("Provide text and/or html content for the email body.")

    payload: dict[str, Any] = {
        "from": sender,
        "to": _recipients(to, "to"),
        "subject": subject,
    }
    if text is not None:
        payload["text"] = str(text)
    if html is not None:
        payload["html"] = str(html)
    if reply_to is not None:
        payload["reply_to"] = _recipients(reply_to, "reply_to")
    if cc is not None:
        payload["cc"] = _recipients(cc, "cc")
    if bcc is not None:
        payload["bcc"] = _recipients(bcc, "bcc")
    return _post_json(API_URL, payload, {"Authorization": f"Bearer {key}"}, timeout)

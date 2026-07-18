# Resend Email

Send email through the [Resend](https://resend.com) API from SyKit
endpoints. Standard library only; no new dependencies.

## Install

```
python SyKit package add resend --yes --allow-core
```

`--allow-core` is required because the package adds a module under
`sykit/`; the pre-install report shows exactly one `core-edit` finding for
`sykit/resend.py` plus the expected `url` and `env-read` warnings for the
API host and key. Existing projects should re-run `python SyKit init`
afterwards so the new module is copied into `src/`, then rebuild.

## Configuration

| Variable | Meaning |
| --- | --- |
| `RESEND_API_KEY` | API key from the Resend dashboard |
| `RESEND_FROM` | Default sender, e.g. `My App <app@yourdomain.com>` |

Both can live in the project `.env` when SyKit's `use-dotenv` setting is
on; the package appends commented entries to `.env.example`.

## Usage

```python
from sykit.resend import send_email

@expose("contact")
def contact(session: dict, message: str):
    send_email(
        to="owner@example.com",
        subject="New contact message",
        text=message,
    )
    return {"sent": True}
```

`send_email(to, subject, *, text=None, html=None, from_address=None,
reply_to=None, cc=None, bcc=None, api_key=None, timeout=15)` returns the
Resend response (with the email `id`) and raises `ResendError` on invalid
arguments, transport failures, or API errors.

## Contents

- `add/sykit/resend.py`
- `add/tests/test_resend.py`
- `edit/files/.env.example` (append)

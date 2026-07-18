# TextBelt SMS

Send SMS through the [TextBelt](https://textbelt.com) API from SyKit
endpoints. Standard library only; no new dependencies.

## Install

```
python SyKit package add textbelt --yes --allow-core
```

`--allow-core` is required because the package adds a module under
`sykit/`; the pre-install report shows exactly one `core-edit` finding for
`sykit/textbelt.py` plus the expected `url` and `env-read` warnings for the
API host and key. Existing projects should re-run `python SyKit init`
afterwards so the new module is copied into `src/`, then rebuild.

## Configuration

| Variable | Meaning |
| --- | --- |
| `TEXTBELT_API_KEY` | API key from textbelt.com; the literal key `textbelt` sends one free message per day |

The key can live in the project `.env` when SyKit's `use-dotenv` setting is
on; the package appends a commented entry to `.env.example`.

## Usage

```python
from sykit.textbelt import send_sms, sms_status, quota

@expose("alert")
def alert(session: dict, message: str):
    result = send_sms("+15551234567", message)
    return {"sent": True, "quota": result["quotaRemaining"]}
```

- `send_sms(phone, message, *, api_key=None, timeout=15)` returns the
  TextBelt response (`textId`, `quotaRemaining`) and raises
  `TextBeltError` when the send fails.
- `sms_status(text_id)` returns the delivery status string.
- `quota(api_key=None)` returns the remaining message quota.

## Contents

- `add/sykit/textbelt.py`
- `add/tests/test_textbelt.py`
- `edit/files/.env.example` (append)

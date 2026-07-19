# Auth0 Login

Log SyKit users in through [Auth0](https://auth0.com): the server-side
Authorization Code flow with the state check, code exchange, and profile
fetch handled for you. Standard library only, no SDK dependency. Pairs
with SyKit 0.5.0's `sykit.auth` login system.

## Install

Requires SyKit 0.5.0 or newer (`sykit-req` enforces this):

```
python SyKit package add auth0 --yes --allow-core
```

`--allow-core` is required because the package adds a module under
`sykit/`; the pre-install report shows a `core-edit` finding for
`sykit/auth0.py` and `env-read` findings for the credential variables.
Existing projects should re-run `python SyKit init` afterwards so the
new module is copied into `src/`, then rebuild.

## Setup

In the Auth0 dashboard create a Regular Web Application, allow your
callback URL, and set:

| Variable | Meaning |
| --- | --- |
| `SYKIT_AUTH0_DOMAIN` | The tenant domain, for example `your-tenant.us.auth0.com` |
| `SYKIT_AUTH0_CLIENT_ID` | The application's client id |
| `SYKIT_AUTH0_CLIENT_SECRET` | The application's client secret (server-side only) |
| `SYKIT_AUTH0_CALLBACK` | The URL Auth0 redirects back to, a page of your app |

With SyKit's `use-dotenv` setting they can live in the project `.env`.

## Usage

```python
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
```

Frontend: send the browser to the `auth0_start` redirect; on the
callback page forward the query parameters:

```js
const params = new URLSearchParams(window.location.search);
await auth0_finish(params.get("state"), params.get("code"));
```

Notes:

- `begin()` stores a single-use state value in the session and
  `complete()` refuses a mismatch, so the callback cannot be forged
  into a different visitor's browser.
- `complete()` returns Auth0's `/userinfo` profile (`sub`, and with the
  default scope `email`, `name`, ...). Choose the session claims
  yourself and pass them to `auth.login()`; do not copy the whole
  profile blindly.
- Pair with a server-side `session-store` so logout actually revokes
  sessions; see SyKit's `docs/auth.md`.
- `begin(audience=...)` requests an API audience and
  `begin(connection=...)` pins an identity provider connection.

## Contents

- `add/sykit/auth0.py`
- `add/tests/test_auth0.py`
- `edit/files/.env.example` (append)

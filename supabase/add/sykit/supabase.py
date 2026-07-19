"""Supabase driver for sykit.db (https://supabase.com).

Standard library only; talks to the project's REST API (PostgREST).
Importing this module registers the "supabase" scheme with sykit.db,
and db.connect() imports it automatically when it sees the scheme, so
endpoint code only needs:

    from sykit import db

    store = db.connect("supabase:")             # table sykit_documents
    store = db.connect("supabase:other_table")  # a different table

One-time setup in the Supabase SQL editor:

    create table if not exists sykit_documents (
        collection text not null,
        key text not null,
        value jsonb not null,
        primary key (collection, key)
    );

Environment (with SyKit's "use-dotenv" both can live in .env):

    SYKIT_SUPABASE_URL   https://<project>.supabase.co
    SYKIT_SUPABASE_KEY   the service role key (server-side only; do not
                         ship it to browsers)

Keep row level security enabled on the table; the service role key
bypasses it for the server while anon clients stay locked out.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sykit import db

URL_ENV = "SYKIT_SUPABASE_URL"
KEY_ENV = "SYKIT_SUPABASE_KEY"
DEFAULT_TABLE = "sykit_documents"
DEFAULT_TIMEOUT = 15
PAGE_SIZE = 1000
TABLE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


class SupabaseDriver:
    """sykit.db driver over the Supabase REST API."""

    def __init__(
        self,
        target: str,
        *,
        url: str | None = None,
        key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        table = (target or "").strip() or DEFAULT_TABLE
        if not TABLE_PATTERN.fullmatch(table):
            raise db.DatabaseError(
                "supabase table names must be plain identifiers of at most "
                "63 characters."
            )
        base = (url or os.environ.get(URL_ENV, "")).strip().rstrip("/")
        secret = (key or os.environ.get(KEY_ENV, "")).strip()
        if not base or not secret:
            raise db.DatabaseError(
                f"Supabase is not configured; set {URL_ENV} and {KEY_ENV}."
            )
        if not base.startswith("https://"):
            raise db.DatabaseError(f"{URL_ENV} must be an https:// URL.")
        self._endpoint = f"{base}/rest/v1/{table}"
        self._timeout = timeout
        self._headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}

    def _request(
        self,
        method: str,
        query: str,
        payload: Any = None,
        prefer: str | None = None,
        page: tuple[int, int] | None = None,
    ) -> list[Any]:
        url = self._endpoint + ("?" + query if query else "")
        headers = dict(self._headers)
        if prefer is not None:
            headers["Prefer"] = prefer
        if page is not None:
            headers["Range-Unit"] = "items"
            headers["Range"] = f"{page[0]}-{page[1]}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                parsed = json.loads(error.read().decode("utf-8", "replace"))
                if isinstance(parsed, dict):
                    detail = str(parsed.get("message", ""))
            except (OSError, ValueError):
                pass
            message = f"Supabase returned HTTP {error.code}"
            if detail:
                message += f": {detail}"
            raise db.DatabaseError(message) from error
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise db.DatabaseError(f"Could not reach Supabase: {error}") from error
        if not body:
            return []
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise db.DatabaseError(
                f"Supabase returned invalid JSON: {error}"
            ) from error
        return value if isinstance(value, list) else []

    @staticmethod
    def _filter(collection: str, key: str | None = None) -> str:
        parts = ["collection=eq." + urllib.parse.quote(collection, safe="")]
        if key is not None:
            parts.append("key=eq." + urllib.parse.quote(key, safe=""))
        return "&".join(parts)

    def get(self, collection: str, key: str) -> Any | None:
        rows = self._request("GET", self._filter(collection, key) + "&select=value")
        return rows[0]["value"] if rows else None

    def put(self, collection: str, key: str, value: Any) -> None:
        self._request(
            "POST",
            "on_conflict=collection,key",
            payload=[{"collection": collection, "key": key, "value": value}],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete(self, collection: str, key: str) -> bool:
        rows = self._request(
            "DELETE",
            self._filter(collection, key),
            prefer="return=representation",
        )
        return bool(rows)

    def _rows(self, collection: str, select: str) -> list[dict[str, Any]]:
        # Supabase caps responses at 1000 rows; page with Range headers so
        # large collections never truncate silently.
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            query = self._filter(collection) + f"&select={select}&order=key.asc"
            page = self._request("GET", query, page=(start, start + PAGE_SIZE - 1))
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE

    def keys(self, collection: str) -> list[str]:
        return [row["key"] for row in self._rows(collection, "key")]

    def items(self, collection: str) -> dict[str, Any]:
        return {row["key"]: row["value"] for row in self._rows(collection, "key,value")}

    def close(self) -> None:
        pass


db.register_driver("supabase", SupabaseDriver)

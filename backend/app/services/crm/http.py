"""
HTTP transports for CRM adapters.

Adapters call `await http.request("GET", "/v1/me")` with paths relative to the
provider's API root. NativeHttp sends them straight to the provider with the
account's API key; NangoHttp sends them through Nango's proxy, which adds the
OAuth token and the provider's base URL. The same adapter code serves both.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import settings

NANGO_API = "https://api.nango.dev"


class CrmError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or f"HTTP {resp.status_code}"
    if isinstance(body, dict):
        for k in ("error", "message", "errorMessage", "detail", "msg"):
            v = body.get(k)
            if isinstance(v, str) and v:
                return v[:200]
            if isinstance(v, dict) and isinstance(v.get("message"), str):
                return v["message"][:200]
    return str(body)[:200]


def _friendly(status: int, text: str) -> str:
    if status in (401, 403):
        return f"The CRM rejected the credentials ({status}): {text}"
    if status == 404:
        return f"Not found (404): {text}"
    if status == 429:
        return "The CRM is rate-limiting requests; we'll retry on the next call."
    return f"CRM error {status}: {text}"


# CRMs cap requests per few seconds (Follow Up Boss: per 10 s). A big scan can hit that; wait and retry.
RATE_LIMIT_RETRIES = 4


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    try:
        wait = float(resp.headers.get("Retry-After") or 0)
    except ValueError:
        wait = 0.0
    return min(max(wait, 2.0 * (2 ** attempt)), 20.0)


class BaseHttp:
    client_factory = staticmethod(lambda: httpx.AsyncClient(timeout=15.0))

    def _prepare(self, path: str) -> tuple[str, dict, dict, Any]:  # url, headers, params, auth
        raise NotImplementedError

    async def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        url, headers, extra_params, auth = self._prepare(path)
        query = {**extra_params, **(params or {})}
        async with self.client_factory() as client:
            for attempt in range(RATE_LIMIT_RETRIES + 1):
                try:
                    resp = await client.request(method, url, params=query or None, json=json, headers=headers, auth=auth)
                except httpx.HTTPError as exc:
                    raise CrmError(f"Couldn't reach the CRM: {exc.__class__.__name__}") from exc
                if resp.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                    break
                # Rate-limited: wait as long as the CRM asks (or back off), then try again instead of failing.
                await asyncio.sleep(_retry_after(resp, attempt))
        if resp.status_code >= 400:
            raise CrmError(_friendly(resp.status_code, _error_text(resp)), resp.status_code)
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}


class NativeHttp(BaseHttp):
    def __init__(self, base_url: str, *, headers: dict | None = None, params: dict | None = None,
                 basic: tuple[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Accept": "application/json", **(headers or {})}
        self.params = params or {}
        self.basic = basic

    def _prepare(self, path):
        return self.base_url + path, self.headers, self.params, (httpx.BasicAuth(*self.basic) if self.basic else None)


class NangoHttp(BaseHttp):
    def __init__(self, integration: str, connection_id: str, *, headers: dict | None = None):
        if not settings.nango_secret_key:
            raise CrmError("Nango isn't configured on the server (NANGO_SECRET_KEY).")
        self.integration, self.connection_id = integration, connection_id
        self.extra_headers = headers or {}

    def _prepare(self, path):
        headers = {
            "Authorization": f"Bearer {settings.nango_secret_key}",
            "Connection-Id": self.connection_id,
            "Provider-Config-Key": self.integration,
            "Accept": "application/json",
            # Nango forwards these to the provider.
            **{f"Nango-Proxy-{k}": v for k, v in self.extra_headers.items()},
        }
        return f"{NANGO_API}/proxy{path}", headers, {}, None


async def nango(method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
    """Call Nango's own API (connect sessions, connections, integrations)."""
    if not settings.nango_secret_key:
        raise CrmError("Nango isn't configured on the server (NANGO_SECRET_KEY).")
    async with BaseHttp.client_factory() as client:
        resp = await client.request(method, NANGO_API + path, json=json, params=params,
                                    headers={"Authorization": f"Bearer {settings.nango_secret_key}"})
    if resp.status_code >= 400:
        raise CrmError(f"Nango error {resp.status_code}: {_error_text(resp)}", resp.status_code)
    return resp.json() if resp.content else {}


class SalesforceHttp(BaseHttp):
    """Salesforce REST straight to the org. Two ways in: our OAuth sign-in (a refresh token gets new access
    tokens) or the customer's own Connected App (client credentials: their key + secret get access tokens)."""

    _tokens: dict[str, str] = {}  # refresh token / client id → current access token (per process)

    def __init__(self, tokens: dict, config: dict):
        self.client_id = tokens.get("client_id", "")
        self.client_secret = tokens.get("client_secret", "")
        self.refresh_token = tokens.get("refresh_token", "") or (f"cc:{self.client_id}" if self.client_id else "")
        self.base_url = (config.get("instance_url") or "").rstrip("/")
        self.login_host = config.get("login_host") or "login.salesforce.com"
        if tokens.get("access_token") and self.refresh_token not in self._tokens:
            self._tokens[self.refresh_token] = tokens["access_token"]

    def _prepare(self, path):
        return (self.base_url + path, {"Accept": "application/json",
                                       "Authorization": f"Bearer {self._tokens.get(self.refresh_token, '')}"}, {}, None)

    async def refresh(self) -> None:
        from app.services.crm.salesforce_oauth import client_credentials_token, refresh_access_token

        if self.client_id:
            token = await client_credentials_token(self.base_url, self.client_id, self.client_secret)
        else:
            token = await refresh_access_token(self.refresh_token, self.login_host)
        self._tokens[self.refresh_token] = token

    async def request(self, method, path, *, params=None, json=None):
        if not self._tokens.get(self.refresh_token):
            await self.refresh()
        try:
            return await super().request(method, path, params=params, json=json)
        except CrmError as exc:
            if exc.status != 401:
                raise
            await self.refresh()  # the access token expired — get a new one and try once more
            return await super().request(method, path, params=params, json=json)

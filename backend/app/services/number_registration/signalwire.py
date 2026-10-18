"""SignalWire official Numbers CNAM REST API, not Compatibility/lookup CNAM."""
import re
import unicodedata
import uuid
import httpx
from app.config import settings
from app.services import secret_store


class ProviderError(Exception):
    def __init__(self, code, *, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def normalize_name(value):
    value = ''.join(c for c in value if unicodedata.category(c) != 'Cc')
    value = ' '.join(value.split()).upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 &'.,-]{0,14}", value, flags=re.ASCII):
        raise ValueError("Caller name must be 1–15 characters, start with a letter or digit, and use only letters, digits, spaces, &, apostrophe, period, comma or hyphen. Choose an approved short name; it is never silently truncated.")
    return value


def configured():
    return bool(settings.signalwire_space and settings.signalwire_project_id and
                (settings.signalwire_api_token or secret_store.get('signalwire_api_token')))


class Client:
    def __init__(self, *, transport=None, receipt=None):
        space = settings.signalwire_space.strip().lower()
        if not re.fullmatch(r'[a-z0-9-]+\.signalwire\.com', space):
            raise ProviderError('signalwire_space_required')
        if not configured(): raise ProviderError('signalwire_credentials_required')
        self.base = 'https://' + space
        self.transport, self.receipt = transport, receipt

    async def request(self, method, number_id, *, cnam=False, name=None, missing_ok=False):
        try: number_id = str(uuid.UUID(str(number_id)))
        except (ValueError, TypeError, AttributeError): raise ProviderError('real_carrier_number_id_required') from None
        path = '/api/relay/rest/phone_numbers/' + number_id + ('/cnam' if cnam else '')
        auth = (settings.signalwire_project_id, settings.signalwire_api_token or secret_store.get('signalwire_api_token'))
        async with httpx.AsyncClient(auth=auth, timeout=20, follow_redirects=False, transport=self.transport) as client:
            try:
                response = await client.request(method, self.base + path,
                    **({'json': {'name': normalize_name(name)}} if name is not None else {}))
            except (httpx.TimeoutException, httpx.NetworkError):
                # POST/DELETE may already have reached the provider: durable intent forces GET reconciliation.
                raise ProviderError('carrier_request_outcome_unknown', retryable=True) from None
            try: body = response.json() if response.content else {}
            except ValueError: body = {'unparseable_response': True}
            if not isinstance(body, dict): body = {'data': body}
            request_id = response.headers.get('x-request-id') or body.get('id')
            receipt_body = body if cnam or response.status_code >= 400 else {k: body.get(k) for k in ('id','number','cnam','capabilities') if k in body}
            if self.receipt: await self.receipt(method, path, response.status_code, receipt_body, request_id)
            if response.status_code == 404 and missing_ok: return None
            if response.status_code in (401, 403): raise ProviderError('signalwire_numbers_permission_required')
            if response.status_code == 422:
                unsupported = any(e.get('detail') == "Caller ID name isn't available for this number." for e in (body.get('errors') or []) if isinstance(e,dict))
                raise ProviderError('unsupported_number' if unsupported else 'carrier_validation_failed')
            if response.status_code >= 400 or response.is_redirect:
                raise ProviderError('carrier_http_' + str(response.status_code), retryable=response.status_code == 429 or response.status_code >= 500)
            if body.get('unparseable_response'): raise ProviderError('invalid_carrier_response', retryable=True)
            return body

    async def number(self, number_id, *, missing_ok=False):
        return await self.request('GET', number_id, missing_ok=missing_ok)

    async def latest(self, number_id):
        return await self.request('GET', number_id, cnam=True, missing_ok=True)

    async def submit(self, number_id, name):
        return await self.request('POST', number_id, cnam=True, name=name)

    async def remove(self, number_id):
        return await self.request('DELETE', number_id, cnam=True, missing_ok=True)

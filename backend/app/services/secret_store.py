"""
Encrypted secrets pasted into the admin portal (e.g. the Stripe secret key).

Values are encrypted with Fernet using SECRETS_ENCRYPTION_KEY — an environment
variable, so the database alone can't reveal them — and cached in memory after
startup. An environment variable of the same purpose always wins over a stored value.
"""

from __future__ import annotations

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import AppSecret

log = structlog.get_logger(__name__)

_PREFIX = "enc:"
_cache: dict[str, str] = {}


class SecretStoreError(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not settings.secrets_encryption_key:
        raise SecretStoreError("SECRETS_ENCRYPTION_KEY isn't set on the server.")
    try:
        return Fernet(settings.secrets_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretStoreError("SECRETS_ENCRYPTION_KEY isn't a valid key.") from exc


def available() -> bool:
    try:
        _fernet()
        return True
    except SecretStoreError:
        return False


def get(name: str) -> str:
    return _cache.get(name, "")


async def load_all(db: AsyncSession) -> None:
    """Decrypt every stored secret into memory (called at startup)."""
    from sqlalchemy import select

    _cache.clear()
    if not available():
        return
    f = _fernet()
    rows = (await db.execute(select(AppSecret).where(AppSecret.key.like(f"{_PREFIX}%")))).scalars().all()
    for r in rows:
        try:
            _cache[r.key[len(_PREFIX):]] = f.decrypt(r.value.encode()).decode()
        except InvalidToken:
            log.error("secret_decrypt_failed", name=r.key[len(_PREFIX):])


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str | None) -> str:
    """'' when missing or unreadable (e.g. the encryption key changed)."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, SecretStoreError):
        log.error("secret_value_decrypt_failed")
        return ""


async def put(db: AsyncSession, name: str, value: str) -> None:
    """Encrypt and store (or replace) a secret. Caller commits."""
    token = _fernet().encrypt(value.encode()).decode()
    row = await db.get(AppSecret, _PREFIX + name)
    if row is None:
        db.add(AppSecret(key=_PREFIX + name, value=token))
    else:
        row.value = token
    _cache[name] = value


async def remove(db: AsyncSession, name: str) -> None:
    row = await db.get(AppSecret, _PREFIX + name)
    if row is not None:
        await db.delete(row)
    _cache.pop(name, None)

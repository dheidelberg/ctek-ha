"""OAuth2 password-grant handling for the CTEK cloud.

Verified behaviour (2026-09-02):
- Login: POST /oauth/token with a JSON body. The password is sent as a
  lowercase SHA-256 hex digest, not in plaintext.
- Refresh: POST /oauth/token form-encoded with client_id/client_secret in
  the body. The JSON variant without HTTP basic auth is rejected.
- Access tokens live ~24 h (expires_in 86399).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .const import BASE_URL, CLIENT_ID, CLIENT_SECRET, DEFAULT_HEADERS, TOKEN_REFRESH_MARGIN
from .exceptions import CtekAuthError, CtekConnectionError
from .models import Token

_LOGGER = logging.getLogger(__name__)

TokenListener = Callable[[Token], Awaitable[None] | None]


def hash_password(password: str) -> str:
    """The app sends sha256(password) as hex; the backend never sees plaintext."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class CtekAuth:
    """Owns the token set and refreshes it on demand."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        token: Token | None = None,
        token_listener: TokenListener | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token = token
        self._token_listener = token_listener
        self._lock = asyncio.Lock()

    @property
    def token(self) -> Token | None:
        return self._token

    def invalidate(self) -> None:
        """Force a refresh or login on the next access-token request."""
        if self._token:
            self._token.expires_at = 0

    async def async_get_access_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._token.expires_at - TOKEN_REFRESH_MARGIN:
                return self._token.access_token
            if self._token and self._token.refresh_token:
                try:
                    await self._async_refresh(self._token.refresh_token)
                    return self._token.access_token  # type: ignore[union-attr]
                except CtekAuthError as err:
                    _LOGGER.debug("Refresh token rejected (%s), falling back to login", err)
            await self._async_login()
            return self._token.access_token  # type: ignore[union-attr]

    async def async_login(self) -> Token:
        """Explicit login (used by the config flow to validate credentials)."""
        async with self._lock:
            await self._async_login()
            return self._token  # type: ignore[return-value]

    async def _async_login(self) -> None:
        payload = {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": self._email,
            "password": hash_password(self._password),
        }
        data = await self._post_token(json=payload)
        await self._store(Token.from_response(data))

    async def _async_refresh(self, refresh_token: str) -> None:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
        data = await self._post_token(data=payload)
        token = Token.from_response(data)
        if not token.refresh_token:
            token.refresh_token = refresh_token
        await self._store(token)

    async def _post_token(self, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{BASE_URL}/oauth/token", headers=DEFAULT_HEADERS, **kwargs
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = {}
                if resp.status != 200 or not isinstance(body, dict) or "access_token" not in body:
                    error = body.get("error", "unknown") if isinstance(body, dict) else "unknown"
                    desc = body.get("error_description", "") if isinstance(body, dict) else ""
                    raise CtekAuthError(f"{error}: {desc}".strip(": "))
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CtekConnectionError(str(err)) from err

    async def _store(self, token: Token) -> None:
        self._token = token
        if self._token_listener:
            result = self._token_listener(token)
            if asyncio.iscoroutine(result):
                await result

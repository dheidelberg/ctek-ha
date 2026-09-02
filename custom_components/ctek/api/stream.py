"""Per-device websocket stream delivering `lvAppDeviceState` messages.

Observed behaviour (2026-09-02, CS ONE Gen 2, firmware 5.6.5):
- Connect with a Bearer header, no subscribe frame needed.
- The server immediately sends the last known state, then one message
  every ~15 s while a charging session is running.
- No server pings were seen in 90 s; the client sends its own heartbeat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Callable

import aiohttp

from .auth import CtekAuth
from .const import DEFAULT_HEADERS, WS_URL
from .exceptions import CtekAuthError, CtekConnectionError
from .models import DeviceState

_LOGGER = logging.getLogger(__name__)

StateCallback = Callable[[DeviceState], None]
ConnectionCallback = Callable[[bool], None]

BACKOFF_INITIAL = 5
BACKOFF_MAX = 300
HEARTBEAT_SECONDS = 30


class CtekDeviceStream:
    """Keeps one websocket open per device and reconnects forever."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: CtekAuth,
        device_id: str,
        on_state: StateCallback,
        on_connection: ConnectionCallback | None = None,
    ) -> None:
        self._session = session
        self._auth = auth
        self.device_id = device_id
        self._on_state = on_state
        self._on_connection = on_connection
        self._task: asyncio.Task[None] | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"ctek-ws-{self.device_id}")

    async def async_stop(self) -> None:
        task, self._task = self._task, None
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            if self._on_connection:
                self._on_connection(value)

    async def _run(self) -> None:
        backoff = BACKOFF_INITIAL
        while True:
            try:
                await self._connect_and_listen()
                backoff = BACKOFF_INITIAL  # clean close -> reconnect quickly
            except asyncio.CancelledError:
                raise
            except CtekAuthError as err:
                _LOGGER.warning("Websocket auth failed for %s: %s", self.device_id, err)
                backoff = min(backoff * 2, BACKOFF_MAX)
            except (CtekConnectionError, aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                _LOGGER.debug("Websocket for %s dropped: %r", self.device_id, err)
                backoff = min(backoff * 2, BACKOFF_MAX)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected websocket error for %s", self.device_id)
                backoff = min(backoff * 2, BACKOFF_MAX)
            finally:
                self._set_connected(False)
            delay = backoff + random.uniform(0, backoff / 2)
            _LOGGER.debug("Reconnecting websocket for %s in %.0fs", self.device_id, delay)
            await asyncio.sleep(delay)

    async def _connect_and_listen(self) -> None:
        token = await self._auth.async_get_access_token()
        headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}
        url = WS_URL.format(device_id=self.device_id)
        try:
            async with self._session.ws_connect(url, headers=headers, heartbeat=HEARTBEAT_SECONDS) as ws:
                self._ws = ws
                self._set_connected(True)
                _LOGGER.debug("Websocket connected for %s", self.device_id)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._handle_text(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        except aiohttp.WSServerHandshakeError as err:
            if err.status in (401, 403):
                self._auth.invalidate()
                raise CtekAuthError(f"handshake rejected with {err.status}") from err
            raise CtekConnectionError(f"handshake failed with {err.status}") from err
        finally:
            self._ws = None

    def _handle_text(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.debug("Ignoring non-JSON websocket frame for %s: %.200s", self.device_id, text)
            return
        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")
        if msg_type not in (None, "lvAppDeviceState"):
            _LOGGER.debug("Ignoring websocket message type %s for %s", msg_type, self.device_id)
            return
        state = DeviceState.from_message(payload)
        if not state.device_id:
            state.device_id = self.device_id
        try:
            self._on_state(state)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("State callback failed for %s", self.device_id)

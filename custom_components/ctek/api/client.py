"""REST client for /api/v3 endpoints.

Every response is wrapped in an envelope:
    {"data": ..., "status_code": 200, "timestamp": "...", "status_message": "Success"}
Errors carry a non-200 status_code and a human readable status_message.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .auth import CtekAuth
from .const import BASE_URL, DEFAULT_HEADERS
from .exceptions import CtekApiError, CtekAuthError, CtekConnectionError
from .models import Device

_LOGGER = logging.getLogger(__name__)


class CtekClient:
    """Thin async wrapper around the REST API."""

    def __init__(self, session: aiohttp.ClientSession, auth: CtekAuth) -> None:
        self._session = session
        self._auth = auth

    @property
    def auth(self) -> CtekAuth:
        return self._auth

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        _retry: bool = True,
    ) -> Any:
        token = await self._auth.async_get_access_token()
        headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}
        try:
            async with self._session.request(
                method, f"{BASE_URL}{path}", params=params, json=json, headers=headers
            ) as resp:
                if resp.status == 401:
                    if _retry:
                        self._auth.invalidate()
                        return await self._request(method, path, params=params, json=json, _retry=False)
                    raise CtekAuthError("Unauthorized")
                try:
                    body = await resp.json(content_type=None)
                except ValueError:
                    body = None
                if resp.status >= 400:
                    raise CtekApiError(resp.status, _status_message(body))
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CtekConnectionError(str(err)) from err

        if isinstance(body, dict) and "status_code" in body:
            code = body.get("status_code")
            if isinstance(code, int) and code >= 400:
                raise CtekApiError(code, _status_message(body))
            return body.get("data")
        return body

    # ------------------------------------------------------------------ reads

    async def async_get_devices(self) -> list[Device]:
        data = await self._request("GET", "/api/v3/device/list")
        if isinstance(data, dict):
            data = data.get("devices", [])
        devices: list[Device] = []
        for entry in data or []:
            if not isinstance(entry, dict) or "device_id" not in entry:
                continue
            try:
                devices.append(Device.from_dict(entry))
            except Exception:  # noqa: BLE001 - never let one odd device break the list
                _LOGGER.warning("Skipping unparsable device entry: %s", entry, exc_info=True)
        return devices

    async def async_get_device_status(self, device_id: str) -> dict[str, Any]:
        data = await self._request("GET", "/api/v3/device/status", params={"deviceId": device_id})
        return data if isinstance(data, dict) else {}

    async def async_get_configurations(self, device_id: str) -> dict[str, str]:
        """Return configuration keys as a flat dict (e.g. LightIntensity -> '50')."""
        data = await self._request("GET", "/api/v3/device/configurations", params={"deviceId": device_id})
        result: dict[str, str] = {}
        for item in (data or {}).get("configurations", []) if isinstance(data, dict) else []:
            if isinstance(item, dict) and "key" in item:
                result[str(item["key"])] = str(item.get("value", ""))
        return result

    async def async_get_user_profile(self) -> dict[str, Any]:
        data = await self._request("GET", "/api/v3/user/profile")
        return data if isinstance(data, dict) else {}

    # ----------------------------------------------------------------- writes

    async def async_set_configuration(self, device_id: str, key: str, value: str) -> Any:
        return await self._request(
            "POST",
            "/api/v3/device/configuration",
            params={"deviceId": device_id, "pushToDevice": "true", "key": key, "value": value},
        )

    async def async_set_charge_program(self, device_id: str, program: str) -> Any:
        return await self._request(
            "PUT", f"/api/v3/device/{device_id}/charge-program", json={"charge_program": program}
        )


def _status_message(body: Any) -> str | None:
    if isinstance(body, dict):
        return body.get("status_message") or body.get("message") or body.get("error_description")
    return None

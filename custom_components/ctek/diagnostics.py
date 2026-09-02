"""Diagnostics support for CTEK."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN
from .coordinator import CtekConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN, "passkey", "mac_address", "access_token", "refresh_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CtekConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": {
            device_id: async_redact_data(device.raw, TO_REDACT) for device_id, device in data.devices.items()
        },
        "states": {device_id: asdict(state) for device_id, state in data.states.items()},
        "stream_connected": data.stream_connected,
    }

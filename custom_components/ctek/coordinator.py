"""Coordinator: slow REST polling plus websocket push per cloud device."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CtekApiError,
    CtekAuthError,
    CtekClient,
    CtekConnectionError,
    CtekDeviceStream,
    Device,
    DeviceState,
)
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class CtekData:
    """Everything the entities read from."""

    devices: dict[str, Device] = field(default_factory=dict)
    states: dict[str, DeviceState] = field(default_factory=dict)
    stream_connected: dict[str, bool] = field(default_factory=dict)


type CtekConfigEntry = ConfigEntry[CtekCoordinator]


class CtekCoordinator(DataUpdateCoordinator[CtekData]):
    """Polls the device list and fans websocket updates out to entities."""

    config_entry: CtekConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CtekConfigEntry, client: CtekClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._streams: dict[str, CtekDeviceStream] = {}
        self._data = CtekData()

    async def _async_update_data(self) -> CtekData:
        try:
            devices = await self.client.async_get_devices()
        except CtekAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CtekConnectionError, CtekApiError) as err:
            raise UpdateFailed(str(err)) from err

        self._data.devices = {d.device_id: d for d in devices}
        self._ensure_streams()
        return self._data

    def _ensure_streams(self) -> None:
        session = async_get_clientsession(self.hass)
        for device in self._data.devices.values():
            if not device.is_cloud_device or device.device_id in self._streams:
                continue
            stream = CtekDeviceStream(
                session,
                self.client.auth,
                device.device_id,
                on_state=self._handle_state,
                on_connection=partial(self._handle_connection, device.device_id),
            )
            self._streams[device.device_id] = stream
            self._data.stream_connected[device.device_id] = False
            stream.start()
            _LOGGER.debug("Started websocket stream for %s (%s)", device.device_id, device.name)

    @callback
    def _handle_state(self, state: DeviceState) -> None:
        self._data.states[state.device_id] = state
        self.async_set_updated_data(self._data)

    @callback
    def _handle_connection(self, device_id: str, connected: bool) -> None:
        self._data.stream_connected[device_id] = connected
        self.async_set_updated_data(self._data)

    async def async_shutdown_streams(self) -> None:
        streams, self._streams = list(self._streams.values()), {}
        for stream in streams:
            await stream.async_stop()

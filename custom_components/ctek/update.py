"""Firmware update entity (notification only, installing stays in the app)."""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CtekConfigEntry
from .entity import CtekEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: CtekConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        CtekFirmwareUpdate(coordinator, device_id)
        for device_id, device in coordinator.data.devices.items()
        if device.is_cloud_device
    )


class CtekFirmwareUpdate(CtekEntity, UpdateEntity):
    """Shows whether CTEK offers a newer firmware for the device."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_translation_key = "firmware"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "firmware")

    @property
    def installed_version(self) -> str | None:
        device = self.device
        return device.firmware_version if device else None

    @property
    def latest_version(self) -> str | None:
        device = self.device
        if device is None:
            return None
        if device.firmware_update_available:
            return device.firmware_update_version or "unknown"
        return device.firmware_version

    @property
    def release_summary(self) -> str | None:
        device = self.device
        if device is None:
            return None
        notes = (device.raw.get("firmware_update") or {}).get("release_notes")
        return notes if isinstance(notes, str) and notes else None

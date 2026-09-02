"""Binary sensors for CTEK chargers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Device, DeviceState
from .coordinator import CtekConfigEntry, CtekData
from .entity import CtekEntity


@dataclass(frozen=True, kw_only=True)
class CtekBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a CTEK binary sensor."""

    is_on_fn: Callable[[Device, DeviceState | None, CtekData], bool | None]
    needs_state: bool = True


BINARY_SENSORS: tuple[CtekBinarySensorDescription, ...] = (
    CtekBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        needs_state=False,
        is_on_fn=lambda d, _s, _data: d.connected,
    ),
    CtekBinarySensorDescription(
        key="stream_connected",
        translation_key="stream_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        needs_state=False,
        is_on_fn=lambda d, _s, data: data.stream_connected.get(d.device_id, False),
    ),
    CtekBinarySensorDescription(
        key="session_active",
        translation_key="session_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda _d, s, _data: s.session_started if s else None,
    ),
    CtekBinarySensorDescription(
        key="error_critical",
        translation_key="error_critical",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda _d, s, _data: s.has_critical_error if s else None,
    ),
    CtekBinarySensorDescription(
        key="error_recoverable",
        translation_key="error_recoverable",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda _d, s, _data: s.has_recoverable_error if s else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CtekConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        CtekBinarySensor(coordinator, device_id, description)
        for device_id, device in coordinator.data.devices.items()
        if device.is_cloud_device
        for description in BINARY_SENSORS
    )


class CtekBinarySensor(CtekEntity, BinarySensorEntity):
    """A CTEK binary sensor."""

    entity_description: CtekBinarySensorDescription

    def __init__(self, coordinator, device_id: str, description: CtekBinarySensorDescription) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_description.needs_state:
            return self.has_live_data
        return True

    @property
    def is_on(self) -> bool | None:
        device = self.device
        if device is None:
            return None
        return self.entity_description.is_on_fn(device, self.state_data, self.coordinator.data)

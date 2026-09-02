"""Sensors for CTEK chargers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfElectricCurrent, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CHARGER_STATE_NAMES, Device, DeviceState
from .api.const import CHARGE_PROGRAMS
from .coordinator import CtekConfigEntry
from .entity import CtekEntity


def _program_key(program: str | None) -> str | None:
    return program.lower().replace(" ", "_") if program else None


@dataclass(frozen=True, kw_only=True)
class CtekSensorDescription(SensorEntityDescription):
    """Describes a CTEK sensor."""

    value_fn: Callable[[Device, DeviceState | None], Any]
    attrs_fn: Callable[[Device, DeviceState | None], dict[str, Any]] | None = None
    needs_state: bool = True


SENSORS: tuple[CtekSensorDescription, ...] = (
    CtekSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda _d, s: s.voltage if s else None,
    ),
    CtekSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda _d, s: s.current if s else None,
    ),
    CtekSensorDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda _d, s: s.state_of_charge if s else None,
    ),
    CtekSensorDescription(
        key="charger_state",
        translation_key="charger_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGER_STATE_NAMES),
        value_fn=lambda _d, s: s.charger_state if s else None,
        attrs_fn=lambda _d, s: {"raw_code": s.charger_state_code} if s else {},
    ),
    CtekSensorDescription(
        key="charger_state_code",
        translation_key="charger_state_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:numeric",
        value_fn=lambda _d, s: s.charger_state_code if s else None,
    ),
    CtekSensorDescription(
        key="program",
        translation_key="program",
        device_class=SensorDeviceClass.ENUM,
        options=[_program_key(p) for p in CHARGE_PROGRAMS],
        value_fn=lambda _d, s: _program_key(s.program) if s else None,
    ),
    CtekSensorDescription(
        key="time_remaining",
        translation_key="time_remaining",
        icon="mdi:timer-sand",
        value_fn=lambda _d, s: s.time_remaining if s else None,
    ),
    CtekSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _d, s: datetime.fromtimestamp(s.received_at, tz=timezone.utc) if s else None,
        attrs_fn=lambda _d, s: {"device_timestamp": s.timestamp} if s else {},
    ),
    CtekSensorDescription(
        key="connector_status",
        translation_key="connector_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:power-plug",
        needs_state=False,
        value_fn=lambda d, _s: d.connector_status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CtekConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        CtekSensor(coordinator, device_id, description)
        for device_id, device in coordinator.data.devices.items()
        if device.is_cloud_device
        for description in SENSORS
    )


class CtekSensor(CtekEntity, SensorEntity):
    """A CTEK sensor."""

    entity_description: CtekSensorDescription

    def __init__(self, coordinator, device_id: str, description: CtekSensorDescription) -> None:
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
    def native_value(self) -> Any:
        device = self.device
        if device is None:
            return None
        return self.entity_description.value_fn(device, self.state_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self.device
        if device is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(device, self.state_data)

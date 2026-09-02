"""Base entity for CTEK devices."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device, DeviceState
from .const import DOMAIN
from .coordinator import CtekCoordinator


def device_display_name(coordinator: CtekCoordinator, device: Device) -> str:
    """Alias from the app; when two devices share an alias, add the serial tail."""
    same_alias = [d for d in coordinator.data.devices.values() if d.name == device.name]
    if len(same_alias) > 1:
        return f"{device.name} {device.device_id[-4:]}"
    return device.name


class CtekEntity(CoordinatorEntity[CtekCoordinator]):
    """Common device info and data access."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CtekCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"
        device = coordinator.data.devices[device_id]
        connections = {(CONNECTION_NETWORK_MAC, device.mac_address)} if device.mac_address else set()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections=connections,
            manufacturer="CTEK",
            model=device.standardized_model or device.model,
            model_id=device.model,
            name=device_display_name(coordinator, device),
            serial_number=device_id,
            sw_version=device.firmware_version,
            hw_version=device.hardware_id,
        )

    @property
    def device(self) -> Device | None:
        return self.coordinator.data.devices.get(self._device_id)

    @property
    def state_data(self) -> DeviceState | None:
        return self.coordinator.data.states.get(self._device_id)

    @property
    def has_live_data(self) -> bool:
        """True when the device is online and the websocket delivered a state.

        The server answers a websocket connect for an offline device with a
        placeholder state (charger_state -1, all values null), so the cloud
        `connected` flag from the device list gates the live entities.
        """
        device = self.device
        if device is None or device.connected is False:
            return False
        return self.state_data is not None

    @property
    def available(self) -> bool:
        return super().available and self.device is not None

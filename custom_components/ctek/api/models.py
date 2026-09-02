"""Data classes for CTEK API payloads.

All parsing is defensive: unknown fields are ignored, missing ones become
None. The API is unofficial and can change with any app release.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .const import CLOUD_DEVICE_TYPES

# charger_state arrives as an integer on the websocket. Only codes that were
# observed live with plausible electrical values are mapped; everything else
# is reported as unknown together with the raw code so the table can grow:
#   1 -> all values null, no session          -> idle
#   5 -> 14.18 V / 3.1 A / 90 %, session on    -> absorption
#   6 -> 13.27 V / 0.005 A / 100 %, session on -> float
# The app knows these names (in some order): DISCONNECTED, IDLE, START, PAIR,
# CHECK, ANALYZE, BULK, ABS, FLOAT, PULSE, CARE, CHARGE, WAIT, WAKE_UP, ERROR,
# RECOVERY_MODE, UPGRADING_FIRMWARE, STOPPED_OTA.
CHARGER_STATES: dict[int, str] = {
    1: "idle",
    5: "abs",
    6: "float",
}
CHARGER_STATE_NAMES: tuple[str, ...] = (
    "disconnected",
    "idle",
    "start",
    "pair",
    "check",
    "analyze",
    "bulk",
    "abs",
    "float",
    "pulse",
    "care",
    "charge",
    "wait",
    "wake_up",
    "error",
    "recovery_mode",
    "upgrading_firmware",
    "stopped_ota",
)
_CHARGER_STATE_BY_NAME = {v: k for k, v in CHARGER_STATES.items()}


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return None


@dataclass(slots=True)
class Token:
    """OAuth token set."""

    access_token: str
    refresh_token: str | None
    expires_at: float  # time.time() based

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Token:
        expires_in = _as_int(data.get("expires_in")) or 3600
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + expires_in,
        )


@dataclass(slots=True)
class Device:
    """One entry of /api/v3/device/list."""

    device_id: str
    alias: str | None
    device_type: str | None
    model: str | None
    standardized_model: str | None
    hardware_id: str | None
    firmware_id: str | None
    firmware_version: str | None
    connected: bool | None
    connector_status: str | None
    firmware_update_available: bool
    firmware_update_version: str | None
    mac_address: str | None
    owner: bool | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def is_cloud_device(self) -> bool:
        """True when the device talks to the cloud (Gen 2 with Wi-Fi)."""
        return self.device_type in CLOUD_DEVICE_TYPES or "device_status" in self.raw

    @property
    def name(self) -> str:
        return self.alias or self.standardized_model or self.device_id

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        status = data.get("device_status") or {}
        connectors = status.get("connectors") or []
        first_connector = connectors[0] if connectors and isinstance(connectors[0], dict) else {}
        fw_update = data.get("firmware_update") or {}
        info = data.get("device_info") or {}
        alias = (data.get("device_alias") or "").strip() or None
        return cls(
            device_id=str(data["device_id"]),
            alias=alias,
            device_type=data.get("device_type"),
            model=data.get("model"),
            standardized_model=data.get("standardized_model"),
            hardware_id=data.get("hardware_id"),
            firmware_id=data.get("firmware_id"),
            firmware_version=data.get("firmware_version") or None,
            connected=_as_bool(status.get("connected")) if status else None,
            connector_status=first_connector.get("current_status"),
            firmware_update_available=bool(fw_update.get("update_available")),
            firmware_update_version=fw_update.get("firmware_version"),
            mac_address=info.get("mac_address"),
            owner=_as_bool(data.get("owner")),
            raw=data,
        )


@dataclass(slots=True)
class DeviceState:
    """One `lvAppDeviceState` websocket message."""

    device_id: str
    session_started: bool | None
    program: str | None
    charger_state_code: int | None
    charger_state: str | None
    voltage: float | None  # volts
    current: float | None  # amperes
    state_of_charge: int | None  # percent
    time_remaining: int | None  # unit not confirmed (observed: 2 at ~90 % SoC)
    error_critical: Any
    error_recoverable: Any
    timestamp: str | None
    received_at: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def has_critical_error(self) -> bool:
        return _truthy_error(self.error_critical)

    @property
    def has_recoverable_error(self) -> bool:
        return _truthy_error(self.error_recoverable)

    @classmethod
    def from_message(cls, data: dict[str, Any]) -> DeviceState:
        state_raw = data.get("charger_state")
        code = _as_int(state_raw)
        name: str | None
        if code is not None:
            name = CHARGER_STATES.get(code)
        elif isinstance(state_raw, str) and state_raw:
            name = state_raw.strip().lower().replace(" ", "_")
            if name not in CHARGER_STATE_NAMES:
                name = None
            code = _CHARGER_STATE_BY_NAME.get(name) if name else None
        else:
            name = None

        millivolts = _as_int(data.get("sampled_voltage"))
        milliamps = _as_int(data.get("sampled_current"))
        program = data.get("program")
        return cls(
            device_id=str(data.get("device_id", "")),
            session_started=_as_bool(data.get("session_started")),
            program=program.strip() if isinstance(program, str) and program.strip() else None,
            charger_state_code=code,
            charger_state=name,
            voltage=millivolts / 1000 if millivolts is not None else None,
            current=milliamps / 1000 if milliamps is not None else None,
            state_of_charge=_as_int(data.get("state_of_charge")),
            time_remaining=_as_int(data.get("time_remaining")),
            error_critical=data.get("error_critical"),
            error_recoverable=data.get("error_recoverable"),
            timestamp=data.get("timestamp"),
            raw=data,
        )


def _truthy_error(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "none", "null")
    return bool(value)

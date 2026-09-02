"""Parsing of real (anonymised) payloads."""

from api import Device, DeviceState

from .conftest import load_fixture


def test_device_list_parsing() -> None:
    devices = [Device.from_dict(d) for d in load_fixture("device_list.json")["data"]]
    gen2 = next(d for d in devices if d.device_type == "CS_ONE_GEN_2")
    gen1 = next(d for d in devices if d.device_type == "CS_ONE_GEN_1")

    assert gen2.device_id == "TESTSERIAL0001"
    assert gen2.name == "Garage charger"
    assert gen2.firmware_version == "5.6.5"
    assert gen2.connected is True
    assert gen2.connector_status == "Offline"
    assert gen2.mac_address == "00:11:22:33:44:55"
    assert gen2.is_cloud_device
    assert gen2.firmware_update_available is False

    assert gen1.is_cloud_device is False
    assert gen1.connected is None
    assert gen1.firmware_version == "E022"


def test_device_state_idle_message() -> None:
    idle = DeviceState.from_message(load_fixture("ws_messages.json")[0])
    assert idle.charger_state == "idle"
    assert idle.charger_state_code == 1
    assert idle.session_started is False
    assert idle.voltage is None
    assert idle.current is None
    assert idle.state_of_charge is None
    assert idle.has_critical_error is False


def test_device_state_charging_message() -> None:
    state = DeviceState.from_message(load_fixture("ws_messages.json")[1])
    assert state.session_started is True
    assert state.program == "APTO"
    assert state.voltage == 14.183
    assert state.current == 3.081
    assert state.state_of_charge == 90
    assert state.time_remaining == 2
    assert state.charger_state_code == 5
    assert state.charger_state == "abs"
    assert state.timestamp == "2026-09-02T19:34:54.088Z"


def test_device_state_tolerates_string_state_and_errors() -> None:
    state = DeviceState.from_message(
        {"device_id": "x", "charger_state": "FLOAT", "error_critical": "E12", "error_recoverable": "0"}
    )
    assert state.charger_state == "float"
    assert state.charger_state_code == 6
    assert state.has_critical_error is True
    assert state.has_recoverable_error is False

    unknown_name = DeviceState.from_message({"charger_state": "SOMETHING NEW"})
    assert unknown_name.charger_state is None
    assert unknown_name.charger_state_code is None


def test_device_state_unknown_code_keeps_raw() -> None:
    state = DeviceState.from_message({"charger_state": 99})
    assert state.charger_state is None
    assert state.charger_state_code == 99

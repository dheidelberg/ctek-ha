# CTEK cloud API: verified findings

Live-tested on 2026-09-02 against `https://iot.ctek.com` with a CS ONE Gen 2
(firmware 5.6.5). Corrects and extends `briefing.md`; where the two disagree,
this file wins.

## Authentication

| | |
|---|---|
| Login | `POST /oauth/token`, **JSON body**, `grant_type=password` |
| Password | sent as **lowercase SHA-256 hex digest**, never plaintext |
| Client credentials | as in the briefing; wrong values give `401 invalid_client` |
| Wrong password | `400 {"error":"invalid_grant","error_description":"Invalid credentials."}` (same for unknown users) |
| Token lifetime | `expires_in: 86399` (24 h), no `scope` field |
| Refresh | `POST /oauth/token` **form-encoded** with `client_id`/`client_secret` in the body, or JSON with HTTP basic auth. JSON with the client in the body is rejected (`invalid_client`). |
| Revoke | `POST /oauth/revoke` returned 401 with the JSON body tried; not needed |

## Envelope

Confirmed: `{"data": ..., "status_code": 200, "timestamp": "...", "status_message": "Success"}`.
Errors: HTTP 400 with `{"data": null, "status_code": 400, "status_message": "<text>"}`.

## Device list (`GET /api/v3/device/list`)

`data` is a **list** (not an object). Differences to the briefing:

- `device_type` is `CS_ONE_GEN_2` / `CS_ONE_GEN_1`, not `CSONE`.
- `standardized_model` is `CS ONE GEN 2` / `CS ONE`; `model` is `40-701` / `40-330`.
- `device_status` exists **only for Gen 2** (Wi-Fi). Gen 1 is BLE-only, has no
  cloud status and never sends websocket data. The integration skips Gen 1.
- `firmware_update` is `{"update_available": false}` when current; with a
  pending update it carries `firmware_id`, `firmware_version`,
  `download_url`, `file_format` (`ENC`) and `release_notes`.
- `device_info` holds `mac_address` and `passkey` only.
- No `state_of_charge` / `battery_capacity` / `last_updated_timestamp` fields.

## Device status (`GET /api/v3/device/status`)

Gen 2: `connected`, `connectors[]` (`current_status` e.g. `Offline`,
`status_reason`, timestamps), `hardware_id`, `firmware_id`, `device_type`,
`model`, `standardized_model`, plus flags. Note `connectors[0].current_status`
was `Offline` while the device was `connected: true` and charging; it appears
to describe the OCPP-style connector, not the battery clamp.

## Configurations (`GET /api/v3/device/configurations`)

Keys are **CamelCase**, values are strings. Gen 2 returned:
`HeartbeatInterval`, `SessionInfoInterval` (60), `WifiApList`, `RssiLevel`,
`LightIntensity` (50), `ChargePrograms`, `FullPowerMode`,
`GetConfigurationMaxKeys`, `WebSocketPingInterval` (10),
`ActiveChargeProgram` ("0"), `SupportedFileTransferProtocols`, `DcCableType`,
`FactoryReset`. No `read_only` flag set on any of them. Gen 1 returns an empty
list.

The briefing's `LED_INTENSITY`, `ACTIVE_CHARGE_PROGRAM` etc. do not exist;
the LED setting is `LightIntensity`.

## Charge options (`GET /api/v3/device/charge-option`)

**Gen 1 only.** For Gen 2 it returns
`400 "Given device ... is not CS One Gen 1 type."`. Gen 1 returned
`[{"id": 4, "name": "SUPPLY"}, {"id": 5, "name": "RECOND"}]`.

## History and logs

- `/device/history/day?fromDate=YYYY-MM-DD`: `energy_unit: "Ah"`, records
  with `energy_used`, `duration`, `time`, `human_readable_time`.
- `/activity-logs?devices=<id>&days=10`: list of `{device, time, logType,
  logTitle, logMessage, logDetails}` with `logType` such as
  `CHARGING_STARTED`, `CHARGING_STOPPED`. Titles are localised via
  `Accept-Language`.
- `/device/update/ongoing`: last firmware update job with `logs[]`.

## Websocket (`wss://iot.ctek.com/api/v1/socket/devices/transaction/<id>`)

- Bearer header auth works; no subscribe frame needed.
- On connect the server sends the last known state at once, then a new
  message roughly **every 15 s** while a session runs (`SessionInfoInterval`
  is 60 in the config, so the cadence is not obviously tied to it).
- No server pings in 90 s; the client heartbeat (30 s) is harmless.
- Offline Gen 1: the socket opens but never sends anything.

Message (`type: lvAppDeviceState`):

```json
{"type":"lvAppDeviceState","device_id":"...","session_started":true,
 "program":"APTO","charger_state":5,"state_of_charge":90,
 "sampled_voltage":14183,"sampled_current":3081,"time_remaining":2,
 "error_critical":false,"error_recoverable":false,
 "timestamp":"2026-09-02T19:34:54.088Z"}
```

Differences to the briefing:

- `charger_state` is an **integer**, not a string. Observed so far:
  - `-1`: placeholder the server sends on connect for an **offline** device
    (all values `null`, `session_started: false`)
  - `1`: online, no session, all values `null` (idle)
  - `5`: 14.18 V / 3.08 A / 90 %, session running (absorption)
  - `6`: 13.27 V / 0.005 A / 100 %, session running (float)
  Only these are mapped in `api/models.py`; other codes surface as
  "unknown" plus the raw code. The briefing's enum order (which would make
  5 = ANALYZE and 6 = BULK) does not match the electrical values, so it is
  not the ordinal order.
- `error_critical` / `error_recoverable` are booleans (`false`).
- `time_remaining` is an integer; unit still unknown (`2` at 90 % SoC in
  what is probably absorption, so likely hours).

## Open questions

1. Does the websocket keep sending while the charger is idle, and how often?
2. Which of the remaining `charger_state` codes map to which phase (compare with the app while a charge runs through bulk).
3. Unit of `time_remaining`.
4. Does `PUT /device/{id}/charge-program` accept the same names on Gen 2, and
   is `ActiveChargeProgram` (numeric) the read side of it?

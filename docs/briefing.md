# Briefing: Home-Assistant-Integration für CTEK-Ladegeräte

Dieses Dokument ist die Übergabe an Claude Code. Es enthält alles, was bisher aus der CTEK-Android-App (Paket `se.ctek.ctekapp`, jadx-dekompiliert, nicht obfuskiert) rekonstruiert wurde, und beschreibt den Bauplan für die Integration.

**Wichtig:** Alle API-Angaben stammen aus dem App-Code und sind noch nicht live verifiziert. Schritt 1 ist daher immer ein Test gegen das echte Backend, bevor Code darauf aufbaut.

---

## 0. Ziel

Custom Integration `ctek` für Home Assistant (HACS-fähig), die CTEK-Geräte aus dem CTEK-Cloud-Account einbindet. Erstes Zielgerät: **CS ONE Gen 2** (WLAN + BLE, `device_type = CSONE`, Hardware `CS_ONE_2_PROD`). Njord Go und Nanogrid Air sind über dieselbe API erreichbar, aber erst mal nachrangig.

Testgerät des Nutzers: ein CS ONE Gen 2, Firmware 5.6.5.

---

## 1. Backend & Authentifizierung

| | |
|---|---|
| Base-URL (Prod) | `https://iot.ctek.com` |
| Client-ID | `android_nS865khcg3ZWiBWF` |
| Client-Secret | `secret_@PhIL@gBdV<tpqBW7^2tQR8Yrq8;mvm_` |
| Login | `POST /oauth/token`, JSON-Body, OAuth2 Password Grant |
| Refresh | `POST /oauth/token`, `grant_type=refresh_token` |
| Logout | `POST /oauth/revoke` |
| Auth-Header | `Authorization: Bearer <access_token>` |

Login-Request:
```json
{
  "grant_type": "password",
  "client_id": "android_nS865khcg3ZWiBWF",
  "client_secret": "secret_@PhIL@gBdV<tpqBW7^2tQR8Yrq8;mvm_",
  "username": "<E-Mail>",
  "password": "<Passwort>"
}
```
Login-Response: `access_token`, `refresh_token`, `expires_in` (Sekunden), `token_type` ("Bearer"), `scope`.

Refresh-Request: `grant_type`, `refresh_token`, `client_id`, `client_secret`.

Zusätzliche Header der App (übernehmen, um nicht aufzufallen): `Accept-Language` (z. B. `de`), ggf. ein User-Agent der App.

### Response-Envelope
Alle `/api/v3/...`-Antworten sind verpackt:
```json
{ "status_code": 200, "status_message": "...", "message": "...", "error": null, "timestamp": "...", "data": <Nutzdaten> }
```
Fehler: `{ "error", "error_description", "message", "status_message" }`.

---

## 2. REST-Endpunkte

Alle relativ zu `https://iot.ctek.com`. `deviceId` = Seriennummer.

### Für die Integration relevant
| Zweck | Methode & Pfad | Parameter / Body |
|---|---|---|
| Geräteliste | `GET /api/v3/device/list` | – |
| Gerät online? | `GET /api/v3/device/status` | `?deviceId=` → `{connected, device_id, device_type, firmware_id, hardware_id, model}` |
| Konfigurationen lesen | `GET /api/v3/device/configurations` | `?deviceId=` → `{configurations: [{id, device_id, key, value, read_only}], unknown_keys: []}` |
| Eine Konfiguration setzen | `POST /api/v3/device/configuration` | `?deviceId=&pushToDevice=true&key=&value=` |
| Mehrere setzen | `POST /api/v3/device/configurations` | `?deviceId=&pushToDevice=true`, Body: JSON-Objekt key→value |
| Ladeprogramme abrufen | `GET /api/v3/device/charge-option` | `?deviceId=&firmwareId=` → Liste `{id, name, firmwareVersion}` |
| Ladeprogramm starten | `PUT /api/v3/device/{deviceId}/charge-program` | Body `{"charge_program": "APTO"}` |
| Gerät umbenennen / Connector / Leistung | `PATCH /api/v3/device/personalisation` | `?deviceId=&pushToDevice=true`, Body `{device_name, device_type, connector, output_power}` |
| Ladehistorie (Tag) | `GET /api/v3/device/history/day` | `?deviceId=&fromDate=` |
| Ladehistorie (Monat) | `GET /api/v3/device/history/month` | `?deviceId=&fromDate=` |
| Aktivitätslog | `GET /api/v3/activity-logs` | `?devices=<id>&days=10` |
| Firmware-Update läuft? | `GET /api/v3/device/update/ongoing` | `?deviceId=` |
| Nutzerprofil | `GET /api/v3/user/profile` | – |
| Geteilte Geräte | `GET /api/v3/user/shared_devices` | – |

### Nur für andere Gerätetypen (später)
- `POST /api/v3/device/control` – Njord Go Start/Stop: Body `{device_id, instruction ("START_CHARGING"/"STOP_CHARGING"/"SET_MAX_CHARGE_CURRENT"/"SET_LED_INTENSITY"...), connector_id, info: {firmware, value}}`
- `GET /api/v3/device/nga/metervalue` – Nanogrid Air Zählerwerte
- `/api/v3/schedule/...` – Ladepläne Njord Go
- Nanogrid Air hat zusätzlich eine lokale API unter `http://192.168.4.1` (AP-Modus)

### Programmnamen (CS ONE)
`APTO` (Standard, adaptiv), `RECOND`, `SUPPLY`, `WAKE UP` (mit Leerzeichen!).

### Bekannte Konfigurationsschlüssel (vermutlich identisch mit BLE-Characteristic-Namen – **beim Test verifizieren**)
`LED_INTENSITY`, `WIFI_ENABLE`, `ACTIVE_CHARGE_PROGRAM`, `CONNECTOR_TYPE`, `AUTO_START`, `MAX_CHARGING_CURRENT`.

### Felder in `/device/list` (pro Gerät)
`id`, `device_id`, `device_alias`, `device_type` (`CSONE` | `NJORD_GO` | `NANOGRID_AIR` | `BATTERY_SENSE`), `model`, `standardized_model`, `hardware_id`, `firmware_id`, `firmware_version`, `state_of_charge`, `battery_capacity`, `owner` (bool), `last_updated_timestamp`,
`device_status: {connected, connectors[], load_balancing_onboarded, third_party_ocpp_status}`,
`firmware_update: {update_available, firmware_version, firmware_id, is_mandatory, release_notes, download_url, file_format}`,
`device_info: {id, bluetooth_name, mac_address, passkey, model, device_type, firmware_id, hardware_id, number_of_connectors}`,
`user_device: {brand, connector, output_power}`.

Ladehistorie-Antwort: `{beginning_of_history, end_of_history, total_duration, total_energy, users_in_sessions[], charging_history_records[]}`.

---

## 3. Live-Daten per WebSocket (Kernstück)

Spannung, Strom, SoC und Ladephase kommen über WLAN **nicht** per REST, sondern per WebSocket:

```
wss://iot.ctek.com/api/v1/socket/devices/transaction/<deviceId>
Header: Authorization: Bearer <access_token>
```

Die App sendet nach dem Connect nichts (kein Subscribe-Frame gefunden); der Server pusht JSON-Nachrichten. Typ-Feld `type = "lvAppDeviceState"`. Felder:

| Feld | Typ | Bedeutung |
|---|---|---|
| `type` | string | `lvAppDeviceState` |
| `device_id` | string | Seriennummer |
| `session_started` | bool | Ladesitzung aktiv |
| `program` | string | `APTO`, `RECOND`, `SUPPLY`, `WAKE UP` |
| `charger_state` | string | Phase, s. u. |
| `sampled_voltage` | int | **Millivolt** (→ /1000 = V) |
| `sampled_current` | int | **Milliampere** (→ /1000 = A) |
| `state_of_charge` | int | Prozent |
| `time_remaining` | int/string | Restzeit (Einheit beim Test prüfen) |
| `error_critical` | string/int | kritischer Fehlercode |
| `error_recoverable` | string/int | behebbarer Fehler |
| `timestamp` | string | Zeitstempel |

`charger_state`-Werte: `DISCONNECTED, IDLE, START, PAIR, CHECK, ANALYZE, BULK, ABS, FLOAT, PULSE, CARE, CHARGE, WAIT, WAKE_UP, ERROR, RECOVERY_MODE, UPGRADING_FIRMWARE, STOPPED_OTA`.

Verhalten der App: Reconnect mit Exponential-Backoff (max. Versuche, dann Aufgabe), Pause bei App-Hintergrund, Neuaufbau bei Netzwechsel, Token-Refresh vor Reconnect.

**Hinweis:** Wenn die App gleichzeitig per Bluetooth verbunden ist, liest sie die Werte per BLE statt WebSocket. Ob der Server bei aktiver BLE-Verbindung weiterhin WS-Nachrichten schickt, ist unbekannt – beim Test die App schließen.

---

## 4. Vorgehen (in dieser Reihenfolge)

### Schritt 1: Live-Test (bevor Code entsteht)
Kleines Python-Skript `scripts/probe.py` (aiohttp):
1. Login → Token
2. `GET /api/v3/device/list` → komplette Antwort als JSON speichern (`fixtures/device_list.json`)
3. `GET /api/v3/device/status`, `/configurations`, `/charge-option` für das Testgerät → als Fixtures speichern
4. WebSocket öffnen, 2–3 Minuten mitschreiben (Ladegerät angeschlossen) → `fixtures/ws_messages.jsonl`
5. Envelope-Struktur und Feldnamen mit Abschnitt 1–3 abgleichen, Abweichungen in diesem Dokument korrigieren.

Credentials nie ins Repo: `.env` + `.gitignore`.

### Schritt 2: Python-Bibliothek `pyctek` (eigenes Paket, Async)
- `CtekAuth`: Login, automatischer Refresh vor Ablauf, Token-Persistenz-Hook
- `CtekClient`: alle REST-Calls aus Abschnitt 2, Envelope entpacken, Fehler → Exceptions
- `CtekDeviceStream`: WebSocket pro Gerät, Callback bei Nachricht, Reconnect mit Backoff, Token-Refresh
- Datenklassen: `Device`, `DeviceState` (aus WS), `ChargeOption`, `Configuration`
- Tests mit den Fixtures aus Schritt 1

### Schritt 3: HA-Integration `custom_components/ctek`
- `config_flow.py`: E-Mail + Passwort, Login testen, Refresh-Token in Entry speichern
- `coordinator.py`: `DataUpdateCoordinator`; REST-Polling (z. B. alle 5 min für Liste/Konfig) **plus** WebSocket-Push via `async_set_updated_data`
- Ein HA-Device pro CTEK-Gerät (Identifier = Seriennummer, Modell, Firmware, `sw_version`)
- Entities für CS ONE Gen 2:
  - `sensor`: Spannung (V, `voltage`), Strom (A, `current`), SoC (%, `battery`), Ladephase (enum), Programm, Restzeit, letzter Fehler
  - `binary_sensor`: online (`connectivity`), Sitzung aktiv (`running`)
  - `select`: Ladeprogramm → `PUT .../charge-program`
  - `number`: LED-Intensität (0–100) → `/device/configuration`
  - `update`: Firmware verfügbar (aus `firmware_update`)
  - `button`: WAKE UP / RECOND starten (optional)
- `diagnostics.py` mit Token-Redaction
- HACS: `hacs.json`, `manifest.json` (`iot_class: cloud_push`, `requirements: ["pyctek==x.y.z"]`)

### Schritt 4: Robustheit
- 401 → Refresh → Retry, bei erneutem 401 `ConfigEntryAuthFailed` (Reauth-Flow)
- WS-Abbrüche nicht als Fehler loggen, sondern Entities auf `unavailable`
- Ratenlimits: keine Polling-Intervalle unter 60 s

---

## 5. Offene Fragen (beim Live-Test klären)
1. Exakter Envelope – ist es wirklich `data`?
2. Kommen WS-Nachrichten kontinuierlich oder nur bei Änderung? Wie oft?
3. Welche Keys liefert `/device/configurations` wirklich, und wie heißt LED-Intensität dort?
4. Einheit von `time_remaining`.
5. Bringt `PUT .../charge-program` das Gerät auch aus `IDLE` heraus zum Laden, oder nur Programmwechsel?
6. Gibt es ein Rate-Limit / mehrere parallele WS-Sessions pro Account erlaubt?

---

## 6. Rahmenbedingungen
- Inoffizielle API, kann sich mit App-Updates ändern → defensive JSON-Verarbeitung, unbekannte Felder ignorieren.
- Nur eigene Geräte des Accounts nutzen.
- Sprache im Repo: Code/Kommentare Englisch, README zweisprachig ist okay.

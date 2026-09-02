# CTEK for Home Assistant

Custom integration that shows CTEK battery chargers from your CTEK cloud
account in Home Assistant. Built against the unofficial API used by the CTEK
app; see `docs/api-findings.md` for what was verified and `docs/briefing.md`
for the original reverse-engineering notes.

Supported today: **CS ONE Gen 2** (Wi-Fi). Gen 1 devices are Bluetooth-only
and appear in the account but deliver no cloud data, so they are skipped.

## Entities per charger

| Entity | Source |
|---|---|
| Voltage (V), Current (A), State of charge (%) | websocket, live |
| Charger state (enum), Charge program, Time remaining | websocket, live |
| Charging session, Critical error, Recoverable error | websocket, live |
| Cloud connection | device list, polled every 5 min |
| Firmware (update entity) | device list |
| Last update, Connector status, Live stream (diagnostic) | websocket / device list |

## Install

Copy `custom_components/ctek` into your Home Assistant `config/custom_components/`
(or add this repository as a custom repository in HACS), restart, then add the
integration **CTEK** and sign in with your CTEK app account.

Your password is stored in the config entry because the CTEK backend only
offers an OAuth password grant. Tokens are refreshed automatically.

## Development

```
cp .env.example .env         # your CTEK account, for the live probe only
uv sync --group dev
uv run pytest                # offline tests against a fake backend
uv run scripts/probe.py      # live probe, writes fixtures/ (git-ignored)
```

Tests run without Home Assistant installed; they exercise the `api`
subpackage only.

## Notes

- Unofficial API. Any CTEK app update may change it.
- The app's client id/secret are embedded because the backend accepts no
  other client. CTEK can rotate them at any time.

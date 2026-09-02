"""Live probe against the CTEK cloud backend (iot.ctek.com).

Step 1 of the briefing: verify every assumption from the decompiled app
against the real backend BEFORE any library code is written.

Usage:
    uv run scripts/probe.py                 # full run: REST + websocket
    uv run scripts/probe.py --no-ws         # REST only
    uv run scripts/probe.py --ws-seconds 600
    uv run scripts/probe.py --set-program APTO     # try PUT charge-program
    uv run scripts/probe.py --set-config LED_INTENSITY=50

Credentials come from .env (CTEK_EMAIL, CTEK_PASSWORD). Optionally
CTEK_DEVICE_ID to pin the device; otherwise the first CSONE in the list
is used.

Everything the backend returns is written to fixtures/ as-is (tokens
redacted) so the library and its tests can be built from real data.
"""

from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

BASE_URL = "https://iot.ctek.com"
CLIENT_ID = "android_nS865khcg3ZWiBWF"
CLIENT_SECRET = "secret_@PhIL@gBdV<tpqBW7^2tQR8Yrq8;mvm_"
WS_PATH = "/api/v1/socket/devices/transaction/{device_id}"

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de",
    "User-Agent": "okhttp/4.12.0",
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def redact(obj: Any) -> Any:
    """Recursively mask token-like fields before writing fixtures."""
    secret_keys = {"access_token", "refresh_token", "passkey", "password"}
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if k in secret_keys and v else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def save_fixture(name: str, payload: Any) -> None:
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / name
    path.write_text(json.dumps(redact(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"  -> saved {path.relative_to(ROOT)}")


async def read_body(resp: aiohttp.ClientResponse) -> Any:
    text = await resp.text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw_text": text}


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """The app sends the password as a lowercase SHA-256 hex digest, not plaintext.

    Verified against the live backend on 2026-09-02: plaintext -> invalid_grant,
    sha256 hex -> 200 with a valid access_token.
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


async def login(session: aiohttp.ClientSession, email: str, password: str) -> dict:
    """Try the JSON body first (as the briefing says), then form-encoded.

    Password is SHA-256 hex-encoded before sending (see hash_password).
    """
    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": email,
        "password": hash_password(password),
    }

    log("POST /oauth/token (JSON body)")
    async with session.post(f"{BASE_URL}/oauth/token", json=payload) as resp:
        body = await read_body(resp)
        log(f"  status {resp.status}, content-type {resp.headers.get('Content-Type')}")
        if resp.status == 200 and "access_token" in body:
            save_fixture("oauth_token.json", {"_variant": "json", "_status": resp.status, **body})
            return body
        log(f"  JSON variant failed: {json.dumps(body)[:300]}")

    log("POST /oauth/token (form-encoded body)")
    async with session.post(f"{BASE_URL}/oauth/token", data=payload) as resp:
        body = await read_body(resp)
        log(f"  status {resp.status}, content-type {resp.headers.get('Content-Type')}")
        if resp.status == 200 and "access_token" in body:
            save_fixture("oauth_token.json", {"_variant": "form", "_status": resp.status, **body})
            return body
        save_fixture("oauth_token_error.json", {"_status": resp.status, **body})
        raise SystemExit(f"Login failed with both variants: {json.dumps(body)[:500]}")


async def refresh(session: aiohttp.ClientSession, refresh_token: str, variant: str) -> dict:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    kwargs = {"json": payload} if variant == "json" else {"data": payload}
    log(f"POST /oauth/token grant_type=refresh_token ({variant})")
    async with session.post(f"{BASE_URL}/oauth/token", **kwargs) as resp:
        body = await read_body(resp)
        log(f"  status {resp.status}")
        save_fixture("oauth_refresh.json", {"_status": resp.status, **body})
        return body


# --------------------------------------------------------------------------
# REST
# --------------------------------------------------------------------------

async def get(session: aiohttp.ClientSession, path: str, fixture: str, **params: Any) -> Any:
    log(f"GET {path} {params if params else ''}")
    async with session.get(f"{BASE_URL}{path}", params=params) as resp:
        body = await read_body(resp)
        log(f"  status {resp.status}")
        save_fixture(fixture, {"_status": resp.status, "_url": str(resp.url), "_body": body})
        return body


async def call(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    fixture: str,
    params: dict | None = None,
    json_body: Any = None,
) -> Any:
    log(f"{method} {path} params={params} body={json_body}")
    async with session.request(method, f"{BASE_URL}{path}", params=params, json=json_body) as resp:
        body = await read_body(resp)
        log(f"  status {resp.status}")
        save_fixture(fixture, {"_status": resp.status, "_url": str(resp.url), "_body": body})
        return body


def unwrap(body: Any) -> Any:
    """Return the `data` payload if the envelope looks like the briefing says."""
    if isinstance(body, dict) and "data" in body and "status_code" in body:
        return body["data"]
    return body


def pick_device(device_list: Any, wanted: str | None) -> dict | None:
    data = unwrap(device_list)
    devices = data if isinstance(data, list) else (data or {}).get("devices") if isinstance(data, dict) else None
    if not isinstance(devices, list):
        log(f"  !! device list has unexpected shape: {type(data).__name__}")
        return None
    log(f"  {len(devices)} device(s):")
    for d in devices:
        log(f"     {d.get('device_id')}  {d.get('device_type')}  {d.get('model')}  alias={d.get('device_alias')}  fw={d.get('firmware_version')}")
    if wanted:
        for d in devices:
            if d.get("device_id") == wanted:
                return d
        log(f"  !! CTEK_DEVICE_ID={wanted} not in list, falling back")
    for d in devices:
        if d.get("device_type") == "CSONE":
            return d
    return devices[0] if devices else None


# --------------------------------------------------------------------------
# WebSocket
# --------------------------------------------------------------------------

async def stream_ws(session: aiohttp.ClientSession, device_id: str, seconds: int) -> None:
    url = f"wss://iot.ctek.com{WS_PATH.format(device_id=device_id)}"
    out = FIXTURES / "ws_messages.jsonl"
    FIXTURES.mkdir(exist_ok=True)
    log(f"WS connect {url} for {seconds}s (close the CTEK app on your phone!)")

    count = 0
    last_state: dict | None = None
    started = time.monotonic()
    try:
        async with session.ws_connect(url, heartbeat=None, autoping=True) as ws:
            log("  connected")
            with out.open("a", encoding="utf-8") as fh:
                while time.monotonic() - started < seconds:
                    remaining = seconds - (time.monotonic() - started)
                    try:
                        msg = await ws.receive(timeout=min(remaining, 30))
                    except asyncio.TimeoutError:
                        log("  (no message for 30s)")
                        continue

                    now = datetime.now(timezone.utc).isoformat()
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        count += 1
                        try:
                            payload = json.loads(msg.data)
                        except json.JSONDecodeError:
                            payload = {"_raw_text": msg.data}
                        fh.write(json.dumps({"_received": now, "payload": payload}, ensure_ascii=False) + "\n")
                        fh.flush()
                        summary = summarize_state(payload)
                        if summary != last_state:
                            log(f"  #{count} {summary}")
                            last_state = summary
                        elif count % 20 == 0:
                            log(f"  #{count} (unchanged)")
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        count += 1
                        fh.write(json.dumps({"_received": now, "binary_len": len(msg.data)}) + "\n")
                        log(f"  #{count} binary frame {len(msg.data)} bytes")
                    elif msg.type == aiohttp.WSMsgType.PING:
                        log("  server PING")
                    elif msg.type == aiohttp.WSMsgType.PONG:
                        log("  server PONG")
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                        log(f"  server closed: code={ws.close_code} data={msg.data!r}")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        log(f"  ws error: {ws.exception()!r}")
                        break
    except aiohttp.WSServerHandshakeError as exc:
        log(f"  !! handshake failed: {exc.status} {exc.message}")
        log("     headers: " + json.dumps(dict(exc.headers or {})))
        return
    elapsed = time.monotonic() - started
    log(f"WS done: {count} messages in {elapsed:.0f}s "
        f"({count / elapsed * 60:.1f}/min)" if elapsed else "WS done")


def summarize_state(payload: Any) -> dict | None:
    if not isinstance(payload, dict):
        return None
    keys = ("type", "charger_state", "program", "session_started", "sampled_voltage",
            "sampled_current", "state_of_charge", "time_remaining", "error_critical", "error_recoverable")
    return {k: payload.get(k) for k in keys if k in payload}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")
    email = os.environ.get("CTEK_EMAIL")
    password = os.environ.get("CTEK_PASSWORD")
    wanted_id = os.environ.get("CTEK_DEVICE_ID") or None
    if not email or not password:
        raise SystemExit("Set CTEK_EMAIL and CTEK_PASSWORD in .env (see .env.example)")

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        token = await login(session, email, password)
        variant = json.loads((FIXTURES / "oauth_token.json").read_text(encoding="utf-8"))["_variant"]
        log(f"  token_type={token.get('token_type')} expires_in={token.get('expires_in')} scope={token.get('scope')}")
        session.headers["Authorization"] = f"Bearer {token['access_token']}"

        if args.test_refresh and token.get("refresh_token"):
            new = await refresh(session, token["refresh_token"], variant)
            if new.get("access_token"):
                session.headers["Authorization"] = f"Bearer {new['access_token']}"
                log("  refresh OK, using new access token")

        await get(session, "/api/v3/user/profile", "user_profile.json")
        device_list = await get(session, "/api/v3/device/list", "device_list.json")
        await get(session, "/api/v3/user/shared_devices", "shared_devices.json")

        device = pick_device(device_list, wanted_id)
        if not device:
            raise SystemExit("No device found, stopping.")
        device_id = device["device_id"]
        firmware_id = device.get("firmware_id")
        log(f"Using device {device_id} (firmware_id={firmware_id})")

        await get(session, "/api/v3/device/status", "device_status.json", deviceId=device_id)
        await get(session, "/api/v3/device/configurations", "device_configurations.json", deviceId=device_id)
        if firmware_id is not None:
            await get(session, "/api/v3/device/charge-option", "charge_option.json",
                      deviceId=device_id, firmwareId=firmware_id)
        else:
            await get(session, "/api/v3/device/charge-option", "charge_option.json", deviceId=device_id)
        await get(session, "/api/v3/device/update/ongoing", "update_ongoing.json", deviceId=device_id)
        today = datetime.now().strftime("%Y-%m-%d")
        await get(session, "/api/v3/device/history/day", "history_day.json", deviceId=device_id, fromDate=today)
        await get(session, "/api/v3/device/history/month", "history_month.json", deviceId=device_id, fromDate=today[:7] + "-01")
        await get(session, "/api/v3/activity-logs", "activity_logs.json", devices=device_id, days=10)

        if args.set_program:
            await call(session, "PUT", f"/api/v3/device/{device_id}/charge-program",
                       f"set_program_{args.set_program.replace(' ', '_')}.json",
                       json_body={"charge_program": args.set_program})

        if args.set_config:
            key, _, value = args.set_config.partition("=")
            await call(session, "POST", "/api/v3/device/configuration",
                       f"set_config_{key}.json",
                       params={"deviceId": device_id, "pushToDevice": "true", "key": key, "value": value})
            await get(session, "/api/v3/device/configurations", "device_configurations_after_set.json", deviceId=device_id)

        if not args.no_ws:
            await stream_ws(session, device_id, args.ws_seconds)

    log("Done. Compare fixtures/ against docs/briefing.md sections 1-3.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-ws", action="store_true", help="skip the websocket capture")
    p.add_argument("--ws-seconds", type=int, default=180, help="how long to listen on the websocket")
    p.add_argument("--test-refresh", action="store_true", help="exercise the refresh_token grant")
    p.add_argument("--set-program", metavar="NAME", help="PUT charge-program, e.g. APTO or 'WAKE UP'")
    p.add_argument("--set-config", metavar="KEY=VALUE", help="POST a single configuration key")
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        sys.exit(130)

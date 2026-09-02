"""Shared fixtures: a fake iot.ctek.com served by aiohttp on localhost."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from api import const as api_const

FIXTURES = Path(__file__).parent / "fixtures"

EMAIL = "user@example.com"
PASSWORD = "secret#1"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeCtek:
    """Records requests and serves canned responses."""

    def __init__(self) -> None:
        self.token_requests: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, dict[str, str], str | None]] = []
        self.access_tokens_issued = 0
        self.reject_next_api_call = False
        self.ws_messages: list[dict[str, Any]] = load_fixture("ws_messages.json")
        self.ws_connections = 0
        self.app = web.Application()
        self.app.router.add_post("/oauth/token", self.oauth_token)
        self.app.router.add_get("/api/v3/device/list", self.device_list)
        self.app.router.add_get("/api/v3/device/charge-option", self.charge_option)
        self.app.router.add_get("/api/v3/device/configurations", self.configurations)
        self.app.router.add_get("/api/v1/socket/devices/transaction/{device_id}", self.websocket)

    # -- auth ----------------------------------------------------------------
    async def oauth_token(self, request: web.Request) -> web.Response:
        if request.content_type == "application/json":
            body = await request.json()
            body["_content_type"] = "json"
        else:
            body = dict(await request.post())
            body["_content_type"] = "form"
        self.token_requests.append(body)
        if body.get("client_id") != api_const.CLIENT_ID or body.get("client_secret") != api_const.CLIENT_SECRET:
            return web.json_response({"error": "invalid_client"}, status=401)
        if body.get("grant_type") == "password":
            if body.get("password") != hashlib.sha256(PASSWORD.encode()).hexdigest():
                return web.json_response(
                    {"error": "invalid_grant", "error_description": "Invalid credentials."}, status=400
                )
        elif body.get("grant_type") == "refresh_token":
            if body["_content_type"] != "form":
                return web.json_response({"error": "invalid_client"}, status=400)
            if body.get("refresh_token") != "refresh-1":
                return web.json_response({"error": "invalid_grant"}, status=400)
        else:
            return web.json_response({"error": "unsupported_grant_type"}, status=400)
        self.access_tokens_issued += 1
        return web.json_response(
            {
                "access_token": f"access-{self.access_tokens_issued}",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 86399,
            }
        )

    def _check_auth(self, request: web.Request) -> web.Response | None:
        self.requests.append((request.method, request.path, dict(request.query), request.headers.get("Authorization")))
        if self.reject_next_api_call:
            self.reject_next_api_call = False
            return web.Response(status=401)
        if not (request.headers.get("Authorization") or "").startswith("Bearer access-"):
            return web.Response(status=401)
        return None

    # -- rest ----------------------------------------------------------------
    async def device_list(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err
        return web.json_response(load_fixture("device_list.json"))

    async def charge_option(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err
        return web.json_response(load_fixture("error_envelope.json"), status=400)

    async def configurations(self, request: web.Request) -> web.Response:
        if err := self._check_auth(request):
            return err
        return web.json_response(
            {
                "data": {"configurations": [{"key": "LightIntensity", "value": "50", "read_only": False}]},
                "status_code": 200,
                "status_message": "Success",
            }
        )

    # -- websocket -----------------------------------------------------------
    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        if not (request.headers.get("Authorization") or "").startswith("Bearer access-"):
            raise web.HTTPUnauthorized()
        self.ws_connections += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        for message in self.ws_messages:
            await ws.send_json(message)
        await ws.send_str("not json")
        await ws.close()
        return ws


@pytest.fixture
async def fake_ctek(monkeypatch: pytest.MonkeyPatch):
    fake = FakeCtek()
    server = TestServer(fake.app)
    await server.start_server()
    base = f"http://{server.host}:{server.port}"
    monkeypatch.setattr(api_const, "BASE_URL", base)
    # modules import the constants by name, so patch them there as well
    from api import auth, client, stream

    monkeypatch.setattr(auth, "BASE_URL", base)
    monkeypatch.setattr(client, "BASE_URL", base)
    monkeypatch.setattr(stream, "WS_URL", f"ws://{server.host}:{server.port}/api/v1/socket/devices/transaction/{{device_id}}")
    try:
        yield fake
    finally:
        await server.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s

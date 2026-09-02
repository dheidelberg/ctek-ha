"""Auth, REST client and websocket stream against the fake backend."""

import asyncio
import hashlib

import pytest

from api import (
    CtekApiError,
    CtekAuth,
    CtekAuthError,
    CtekClient,
    CtekDeviceStream,
    Token,
)

from .conftest import EMAIL, PASSWORD


async def test_login_hashes_password_and_uses_json(fake_ctek, session) -> None:
    auth = CtekAuth(session, EMAIL, PASSWORD)
    token = await auth.async_login()
    assert token.access_token == "access-1"
    req = fake_ctek.token_requests[-1]
    assert req["_content_type"] == "json"
    assert req["password"] == hashlib.sha256(PASSWORD.encode()).hexdigest()
    assert req["username"] == EMAIL


async def test_wrong_password_raises(fake_ctek, session) -> None:
    auth = CtekAuth(session, EMAIL, "nope")
    with pytest.raises(CtekAuthError):
        await auth.async_login()


async def test_refresh_is_form_encoded_and_persisted(fake_ctek, session) -> None:
    seen: list[Token] = []
    expired = Token(access_token="access-old", refresh_token="refresh-1", expires_at=0)
    auth = CtekAuth(session, EMAIL, PASSWORD, token=expired, token_listener=seen.append)
    token = await auth.async_get_access_token()
    assert token == "access-1"
    assert fake_ctek.token_requests[-1]["grant_type"] == "refresh_token"
    assert fake_ctek.token_requests[-1]["_content_type"] == "form"
    assert seen and seen[-1].access_token == "access-1"


async def test_refresh_failure_falls_back_to_login(fake_ctek, session) -> None:
    expired = Token(access_token="x", refresh_token="stale", expires_at=0)
    auth = CtekAuth(session, EMAIL, PASSWORD, token=expired)
    assert await auth.async_get_access_token() == "access-1"
    grants = [r["grant_type"] for r in fake_ctek.token_requests]
    assert grants == ["refresh_token", "password"]


async def test_get_devices_unwraps_envelope(fake_ctek, session) -> None:
    client = CtekClient(session, CtekAuth(session, EMAIL, PASSWORD))
    devices = await client.async_get_devices()
    assert {d.device_id for d in devices} == {"TESTSERIAL0001", "TESTSERIAL0002"}
    assert fake_ctek.requests[-1][3] == "Bearer access-1"


async def test_401_triggers_one_retry_with_fresh_token(fake_ctek, session) -> None:
    client = CtekClient(session, CtekAuth(session, EMAIL, PASSWORD))
    await client.async_get_devices()
    fake_ctek.reject_next_api_call = True
    await client.async_get_devices()
    assert fake_ctek.access_tokens_issued == 2
    assert fake_ctek.requests[-1][3] == "Bearer access-2"


async def test_error_envelope_becomes_api_error(fake_ctek, session) -> None:
    client = CtekClient(session, CtekAuth(session, EMAIL, PASSWORD))
    with pytest.raises(CtekApiError) as excinfo:
        await client._request("GET", "/api/v3/device/charge-option", params={"deviceId": "TESTSERIAL0001"})
    assert excinfo.value.status == 400
    assert "not CS One Gen 1" in excinfo.value.message


async def test_configurations_flattened(fake_ctek, session) -> None:
    client = CtekClient(session, CtekAuth(session, EMAIL, PASSWORD))
    assert await client.async_get_configurations("TESTSERIAL0001") == {"LightIntensity": "50"}


async def test_stream_delivers_states_and_reconnects(fake_ctek, session, monkeypatch) -> None:
    from api import stream as stream_mod

    monkeypatch.setattr(stream_mod, "BACKOFF_INITIAL", 0.05)
    monkeypatch.setattr(stream_mod, "BACKOFF_MAX", 0.05)

    states = []
    connections = []
    auth = CtekAuth(session, EMAIL, PASSWORD)
    stream = CtekDeviceStream(session, auth, "TESTSERIAL0001", states.append, connections.append)
    stream.start()
    try:
        for _ in range(100):
            if fake_ctek.ws_connections >= 2:
                break
            await asyncio.sleep(0.05)
    finally:
        await stream.async_stop()

    assert fake_ctek.ws_connections >= 2, "stream should reconnect after the server closes"
    assert len(states) >= len(fake_ctek.ws_messages)
    assert states[1].voltage == 14.183
    assert states[1].device_id == "TESTSERIAL0001"
    assert connections[:2] == [True, False]
    assert stream.connected is False

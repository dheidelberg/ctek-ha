"""The CTEK integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CtekAuth, CtekAuthError, CtekClient, CtekConnectionError, Token
from .const import CONF_TOKEN, PLATFORMS
from .coordinator import CtekConfigEntry, CtekCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: CtekConfigEntry) -> bool:
    """Set up CTEK from a config entry."""
    session = async_get_clientsession(hass)

    stored = entry.data.get(CONF_TOKEN)
    token = None
    if isinstance(stored, dict) and stored.get("access_token"):
        token = Token(
            access_token=stored["access_token"],
            refresh_token=stored.get("refresh_token"),
            expires_at=float(stored.get("expires_at", 0)),
        )

    def _persist_token(new_token: Token) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TOKEN: {
                    "access_token": new_token.access_token,
                    "refresh_token": new_token.refresh_token,
                    "expires_at": new_token.expires_at,
                },
            },
        )

    auth = CtekAuth(
        session,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        token=token,
        token_listener=_persist_token,
    )
    client = CtekClient(session, auth)

    try:
        await auth.async_get_access_token()
    except CtekAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CtekConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = CtekCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_shutdown_streams)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CtekConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

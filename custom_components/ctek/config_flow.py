"""Config flow for CTEK."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CtekAuth, CtekAuthError, CtekClient, CtekConnectionError, CtekError
from .const import CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    }
)
STEP_REAUTH_SCHEMA = vol.Schema(
    {vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


class CtekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CTEK."""

    VERSION = 1

    async def _async_validate(self, email: str, password: str) -> dict[str, Any]:
        """Log in and fetch the device list. Returns the entry data."""
        session = async_get_clientsession(self.hass)
        auth = CtekAuth(session, email, password)
        token = await auth.async_login()
        client = CtekClient(session, auth)
        devices = await client.async_get_devices()
        _LOGGER.debug("CTEK login ok, %d device(s)", len(devices))
        return {
            CONF_EMAIL: email,
            CONF_PASSWORD: password,
            CONF_TOKEN: {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
            },
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            try:
                data = await self._async_validate(email, user_input[CONF_PASSWORD])
            except CtekAuthError:
                errors["base"] = "invalid_auth"
            except CtekConnectionError:
                errors["base"] = "cannot_connect"
            except CtekError:
                _LOGGER.exception("Unexpected error validating CTEK login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=email, data=data)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                data = await self._async_validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            except CtekAuthError:
                errors["base"] = "invalid_auth"
            except CtekConnectionError:
                errors["base"] = "cannot_connect"
            except CtekError:
                _LOGGER.exception("Unexpected error during CTEK reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )

"""Config flow: host + credenziali, reauth, opzioni."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WaxAuthError, WaxClient, WaxError
from .const import (
    CONF_TRACK_CLIENTS,
    CONF_WEAK_RSSI,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACK_CLIENTS,
    DEFAULT_WEAK_RSSI,
    DEFAULT_USERNAME,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)


class WaxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Aggiunta di un WAX214 da interfaccia."""

    VERSION = 1

    async def _probe(self, data: Mapping[str, Any]) -> dict[str, str | None]:
        client = WaxClient(
            async_get_clientsession(self.hass, verify_ssl=False),
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data.get(CONF_PORT, DEFAULT_PORT),
        )
        try:
            await client.login()
            return await client.get_device_info()
        finally:
            await client.logout()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self._probe(user_input)
            except WaxAuthError:
                errors["base"] = "invalid_auth"
            except WaxError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.get("serial") or info.get("mac_lan") or user_input[CONF_HOST])
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                title = f"{info.get('model') or 'WAX214'} ({info.get('name') or user_input[CONF_HOST]})"
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await self._probe(data)
            except WaxAuthError:
                errors["base"] = "invalid_auth"
            except WaxError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> WaxOptionsFlow:
        return WaxOptionsFlow()


class WaxOptionsFlow(OptionsFlow):
    """Intervallo di aggiornamento e device tracker dei client."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=600)),
                    vol.Required(
                        CONF_TRACK_CLIENTS, default=opts.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS)
                    ): bool,
                    vol.Required(
                        CONF_WEAK_RSSI, default=opts.get(CONF_WEAK_RSSI, DEFAULT_WEAK_RSSI)
                    ): vol.All(vol.Coerce(int), vol.Range(min=-95, max=-40)),
                }
            ),
        )

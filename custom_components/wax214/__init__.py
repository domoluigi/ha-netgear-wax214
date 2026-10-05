"""Integrazione Netgear WAX214 (access point con interfaccia LuCI)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WaxAuthError, WaxClient, WaxError
from .const import (
    CONF_TRACK_CLIENTS,
    CONF_WEAK_RSSI,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRACK_CLIENTS,
    DEFAULT_WEAK_RSSI,
    DOMAIN,
)
from .coordinator import WaxCoordinator

BASE_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

type WaxConfigEntry = ConfigEntry[WaxCoordinator]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if entry.options.get(CONF_TRACK_CLIENTS, DEFAULT_TRACK_CLIENTS):
        return [*BASE_PLATFORMS, Platform.DEVICE_TRACKER]
    return BASE_PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: WaxConfigEntry) -> bool:
    client = WaxClient(
        async_get_clientsession(hass, verify_ssl=False),
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    try:
        await client.login()
        device_info = await client.get_device_info()
    except WaxAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except WaxError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = WaxCoordinator(
        hass,
        entry,
        client,
        device_info,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        entry.options.get(CONF_WEAK_RSSI, DEFAULT_WEAK_RSSI),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    platforms = _platforms(entry)
    coordinator.platforms = platforms
    if Platform.DEVICE_TRACKER not in platforms:
        # opzione spenta: via i tracker creati in precedenza
        registry = er.async_get(hass)
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg.domain == Platform.DEVICE_TRACKER:
                registry.async_remove(reg.entity_id)
        # e i dispositivi creati per quei tracker (solo se appartengono unicamente a questa voce)
        dev_reg = dr.async_get(hass)
        still_used = {
            reg.device_id for reg in er.async_entries_for_config_entry(registry, entry.entry_id) if reg.device_id
        }
        for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
            if (
                (DOMAIN, entry.unique_id) not in device.identifiers
                and device.id not in still_used
                and device.config_entries == {entry.entry_id}
            ):
                dev_reg.async_remove_device(device.id)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: WaxConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: WaxConfigEntry) -> bool:
    # le piattaforme caricate all'avvio, non quelle delle opzioni appena cambiate
    unloaded = await hass.config_entries.async_unload_platforms(entry, entry.runtime_data.platforms)
    if unloaded:
        await entry.runtime_data.client.logout()
    return unloaded

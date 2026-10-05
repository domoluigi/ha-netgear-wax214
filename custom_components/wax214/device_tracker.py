"""Device tracker per i client Wi-Fi (creati disattivati: si abilitano quelli che servono)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WaxConfigEntry
from .coordinator import WaxCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: WaxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    tracked: set[str] = set()

    # client già registrati in passato: ricreati subito, così risultano "fuori casa" se assenti
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_client_"
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg.domain == "device_tracker" and reg.unique_id.startswith(prefix):
            tracked.add(reg.unique_id.removeprefix(prefix))

    @callback
    def add_new() -> None:
        new = [mac for mac in coordinator.known_clients if mac not in tracked]
        if new:
            tracked.update(new)
            async_add_entities(WaxClientTracker(coordinator, mac) for mac in new)

    async_add_entities(WaxClientTracker(coordinator, mac) for mac in tracked)
    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class WaxClientTracker(CoordinatorEntity[WaxCoordinator], ScannerEntity):
    """Un client associato all'access point."""

    _attr_entity_registry_enabled_default = False
    _unrecorded_attributes = frozenset({"rssi", "mode"})

    def __init__(self, coordinator: WaxCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_client_{mac}"

    @property
    def _client(self) -> dict[str, Any]:
        return self.coordinator.data.clients.get(self._mac) or self.coordinator.known_clients.get(self._mac) or {}

    @property
    def name(self) -> str:
        return self._client.get("hostname") or self._mac

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def is_connected(self) -> bool:
        return self._mac in self.coordinator.data.clients

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        return self._client.get("ip")

    @property
    def hostname(self) -> str | None:
        return self._client.get("hostname")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator.data.clients.get(self._mac)
        if not c:
            return {}
        return {"ssid": c["ssid"], "band": c["band"], "rssi": c["rssi"], "mode": c["mode"]}

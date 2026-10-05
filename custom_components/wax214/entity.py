"""Entità base legata al dispositivo access point."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WaxCoordinator


class WaxEntity(CoordinatorEntity[WaxCoordinator]):
    """Entità del WAX214."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WaxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.device_info
        self._serial = coordinator.config_entry.unique_id
        self._attr_unique_id = f"{self._serial}_{key}"
        connections = {(CONNECTION_NETWORK_MAC, info["mac_lan"].lower())} if info.get("mac_lan") else set()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            connections=connections,
            manufacturer=MANUFACTURER,
            model=info.get("model"),
            name=info.get("name") or info.get("model"),
            serial_number=info.get("serial"),
            sw_version=info.get("firmware"),
            configuration_url=f"https://{coordinator.config_entry.data[CONF_HOST]}/cgi-bin/luci",
        )

"""Binary sensor: radio e SSID attivi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaxConfigEntry
from .coordinator import WaxCoordinator
from .entity import WaxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: WaxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        WaxRadioBinarySensor(coordinator, dev, radio["band"]) for dev, radio in coordinator.data.radios.items()
    ]
    entities.extend(WaxSsidBinarySensor(coordinator, key, s["name"]) for key, s in coordinator.data.ssids.items())
    async_add_entities(entities)


class WaxRadioBinarySensor(WaxEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "radio_up"

    def __init__(self, coordinator: WaxCoordinator, dev: str, band: str) -> None:
        super().__init__(coordinator, f"{dev}_up")
        self._dev = dev
        self._attr_translation_placeholders = {"band": band}

    @property
    def is_on(self) -> bool | None:
        radio = self.coordinator.data.radios.get(self._dev)
        return radio["up"] if radio else None


class WaxSsidBinarySensor(WaxEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "ssid_up"

    def __init__(self, coordinator: WaxCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator, f"{key}_up")
        self._key = key
        self._attr_translation_placeholders = {"ssid": name}

    @property
    def is_on(self) -> bool:
        ssid = self.coordinator.data.ssids.get(self._key)
        return bool(ssid and ssid["up"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ssid = self.coordinator.data.ssids.get(self._key) or {}
        return {"ssid": ssid.get("name"), "bands": ssid.get("bands", []), "vlan": ssid.get("vlan")}

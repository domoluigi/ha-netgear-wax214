"""Interruttori per accendere/spegnere gli SSID.

Ogni cambio riavvia TUTTE le radio dell'access point: ~35 s senza Wi-Fi per tutti gli SSID.
Un interruttore esiste solo per gli SSID scelti nelle opzioni (predefinito: solo la rete ospiti,
ssid_2): sono azioni che scrivono sull'access point, quindi si attivano su richiesta. L'interruttore
della rete principale (ssid_1), se scelto, è creato disattivato.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaxConfigEntry
from .api import WaxError, WaxUnexpectedChanges
from .const import CONF_SWITCH_SSIDS, DEFAULT_SWITCH_SSIDS
from .coordinator import WaxCoordinator
from .entity import WaxEntity

_LOGGER = logging.getLogger(__name__)

MAIN_SSID = "ssid_1"


async def async_setup_entry(
    hass: HomeAssistant, entry: WaxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    wanted = set(entry.options.get(CONF_SWITCH_SSIDS, DEFAULT_SWITCH_SSIDS))

    # via gli interruttori degli SSID non (più) scelti, rimasti da versioni precedenti
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_"
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg.domain == "switch" and reg.unique_id.startswith(prefix) and reg.unique_id.endswith("_switch"):
            if reg.unique_id[len(prefix) : -len("_switch")] not in wanted:
                registry.async_remove(reg.entity_id)

    known = set(coordinator.data.ssids)
    async_add_entities(
        WaxSsidSwitch(coordinator, key, s["name"]) for key, s in coordinator.data.ssids.items() if key in wanted
    )

    @callback
    def add_new_ssids() -> None:
        """Un SSID creato sull'access point dopo l'avvio ottiene le sue entità senza riavvio."""
        ssids = coordinator.data.ssids if coordinator.data else {}
        new = {k: s for k, s in ssids.items() if k not in known}
        if new:
            known.update(new)
            async_add_entities(WaxSsidSwitch(coordinator, k, s["name"]) for k, s in new.items() if k in wanted)

    entry.async_on_unload(coordinator.async_add_listener(add_new_ssids))


class WaxSsidSwitch(WaxEntity, SwitchEntity):
    _attr_translation_key = "ssid"

    def __init__(self, coordinator: WaxCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator, f"{key}_switch")
        self._key = key
        self._busy = False
        self._attr_translation_placeholders = {"ssid": name}
        self._attr_entity_registry_enabled_default = key != MAIN_SSID

    @property
    def is_on(self) -> bool:
        ssid = self.coordinator.data.ssids.get(self._key)
        return bool(ssid and ssid["up"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"in_corso": self._busy, "nota": "ogni cambio riavvia tutto il Wi-Fi (~35 s)"}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enable: bool) -> None:
        if self._busy:
            raise HomeAssistantError("Cambio SSID già in corso")
        self._busy = True
        self.async_write_ha_state()
        try:
            await self.coordinator.client.set_ssid_enabled(
                self._key, enable, self.coordinator.device_info.get("name") or ""
            )
        except WaxUnexpectedChanges as err:
            _LOGGER.warning("SSID %s non cambiato: %s", self._key, err)
            raise HomeAssistantError(
                "L'access point ha proposto modifiche diverse da quelle attese: annullate, "
                "niente è stato applicato. Controlla l'interfaccia web."
            ) from err
        except WaxError as err:
            raise HomeAssistantError(f"Cambio SSID fallito: {err}") from err
        finally:
            self._busy = False
            await self.coordinator.async_request_refresh()

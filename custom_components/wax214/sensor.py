"""Sensori del WAX214: sistema, radio, SSID e traffico."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaxConfigEntry
from .coordinator import WaxCoordinator, WaxData
from .entity import WaxEntity


@dataclass(frozen=True, kw_only=True)
class WaxSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WaxData], Any]
    placeholders: dict[str, str] | None = None
    attrs_fn: Callable[[WaxData], dict[str, Any]] | None = None


def _mem_used_pct(d: WaxData) -> float | None:
    m = d.memory
    if not m.get("memtotal"):
        return None
    used = m["memtotal"] - m["memfree"] - m["membuffers"] - m["memcached"]
    return round(used * 100 / m["memtotal"], 1)


def _client_list(d: WaxData, pred: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    return [
        {
            "name": c["hostname"] or c["mac"],
            "mac": c["mac"],
            "ip": c["ip"],
            "ssid": c["ssid"],
            "band": c["band"],
            "rssi": c["rssi"],
        }
        for c in sorted(d.clients.values(), key=lambda c: (c["hostname"] or c["mac"]).lower())
        if pred(c)
    ]


SYSTEM_SENSORS: tuple[WaxSensorDescription, ...] = (
    WaxSensorDescription(
        key="clients",
        translation_key="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.clients),
        attrs_fn=lambda d: {"clients": _client_list(d, lambda c: True)},
    ),
    WaxSensorDescription(
        key="boot_time",
        translation_key="boot_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.boot_time,
    ),
    WaxSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_mem_used_pct,
    ),
    WaxSensorDescription(
        key="lan_port_speed",
        translation_key="lan_port_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.lan.get("port_speed"),
    ),
    WaxSensorDescription(
        key="lan_rx",
        translation_key="lan_rx",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.lan.get("rx_bytes"),
    ),
    WaxSensorDescription(
        key="lan_tx",
        translation_key="lan_tx",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.lan.get("tx_bytes"),
    ),
    WaxSensorDescription(
        key="lan_rx_rate",
        translation_key="lan_rx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.rates.get("lan_rx"),
    ),
    WaxSensorDescription(
        key="lan_tx_rate",
        translation_key="lan_tx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.rates.get("lan_tx"),
    ),
    WaxSensorDescription(
        key="weak_clients",
        translation_key="weak_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.weak),
        attrs_fn=lambda d: {
            "soglia": f"{d.weak_threshold} dBm",
            "clients": [
                {"name": c["hostname"] or c["mac"], "mac": c["mac"], "rssi": c["rssi"], "band": c["band"], "ssid": c["ssid"]}
                for c in d.weak
            ],
        },
    ),
)


def _radio_sensors(dev: str, band: str) -> tuple[WaxSensorDescription, ...]:
    def get(field: str) -> Callable[[WaxData], Any]:
        return lambda d: (d.radios.get(dev) or {}).get(field)

    p = {"band": band}
    return (
        WaxSensorDescription(
            key=f"{dev}_clients",
            translation_key="radio_clients",
            placeholders=p,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=get("clients"),
            attrs_fn=lambda d: {"clients": _client_list(d, lambda c: c["band"] == band)},
        ),
        WaxSensorDescription(
            key=f"{dev}_channel",
            translation_key="radio_channel",
            placeholders=p,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=get("channel"),
            attrs_fn=lambda d: {
                k: (d.radios.get(dev) or {}).get(k) for k in ("frequency", "htmode", "hwmode", "bitrate")
            },
        ),
        WaxSensorDescription(
            key=f"{dev}_txpower",
            translation_key="radio_txpower",
            placeholders=p,
            native_unit_of_measurement="dBm",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=get("txpower"),
        ),
        WaxSensorDescription(
            key=f"{dev}_rx_rate",
            translation_key="radio_rx_rate",
            placeholders=p,
            device_class=SensorDeviceClass.DATA_RATE,
            native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            value_fn=lambda d: d.rates.get(f"{dev}_rx"),
        ),
        WaxSensorDescription(
            key=f"{dev}_tx_rate",
            translation_key="radio_tx_rate",
            placeholders=p,
            device_class=SensorDeviceClass.DATA_RATE,
            native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            value_fn=lambda d: d.rates.get(f"{dev}_tx"),
        ),
    )


def _ssid_sensor(key: str, name: str) -> WaxSensorDescription:
    return WaxSensorDescription(
        key=f"{key}_clients",
        translation_key="ssid_clients",
        placeholders={"ssid": name},
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.ssids.get(key) or {}).get("clients", 0),
        attrs_fn=lambda d: {
            "ssid": (d.ssids.get(key) or {}).get("name"),
            "clients": _client_list(d, lambda c: c["ssid"] == (d.ssids.get(key) or {}).get("name")),
        },
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: WaxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    descriptions: list[WaxSensorDescription] = list(SYSTEM_SENSORS)
    for dev, radio in data.radios.items():
        descriptions.extend(_radio_sensors(dev, radio["band"]))
    for key, ssid in data.ssids.items():
        descriptions.append(_ssid_sensor(key, ssid["name"]))
    async_add_entities(WaxSensor(coordinator, d) for d in descriptions)


class WaxSensor(WaxEntity, SensorEntity):
    entity_description: WaxSensorDescription
    # la lista client cambia a ogni ciclo (RSSI): non va nel database
    _unrecorded_attributes = frozenset({"clients"})

    def __init__(self, coordinator: WaxCoordinator, description: WaxSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.placeholders:
            self._attr_translation_placeholders = description.placeholders

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None

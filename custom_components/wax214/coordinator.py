"""Coordinator: una lettura dell'access point per ciclo, dati già normalizzati."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import WaxAuthError, WaxClient, WaxError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

EMPTY_MAC = "00:00:00:00:00:00"
DEFAULT_SSID_RE = re.compile(r"^NETGEAR[0-9A-F]{6}_\d+$")
RADIO_IF_RE = re.compile(r"^ath([01])\d?$")  # ath0, ath01..: wifi0 · ath1, ath11..: wifi1
SSID_KEY_RE = re.compile(r"^ssid_\d+$")  # wds, mesh, guest, mgmt sono reti interne del firmware


@dataclass
class WaxData:
    """Istantanea dello stato dell'AP."""

    uptime: int | None = None
    boot_time: datetime | None = None
    memory: dict[str, int] = field(default_factory=dict)
    radios: dict[str, dict[str, Any]] = field(default_factory=dict)
    ssids: dict[str, dict[str, Any]] = field(default_factory=dict)
    clients: dict[str, dict[str, Any]] = field(default_factory=dict)
    lan: dict[str, Any] = field(default_factory=dict)
    rates: dict[str, float | None] = field(default_factory=dict)  # Mbit/s
    weak: list[dict[str, Any]] = field(default_factory=list)
    weak_threshold: int = -75


def _band(radio: dict[str, Any]) -> str:
    hw = str(radio.get("hwmode", ""))
    if hw.endswith("g") or radio.get("device") == "wifi0":
        return "2.4GHz"
    return "5GHz"


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _kb(value: Any) -> int | None:
    """'10210Kb' -> 10210 (kilobyte come li riporta il firmware)."""
    return _int(str(value or "").rstrip("Kb").strip())


class WaxCoordinator(DataUpdateCoordinator[WaxData]):
    """Legge overview, client e LAN dal WAX214."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: WaxClient,
        device_info: dict[str, str | None],
        scan_interval: int,
        weak_rssi: int = -75,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.device_info = device_info
        self.weak_rssi = weak_rssi
        # ultimo valore dei contatori di byte e istante della lettura, per la velocità
        self._prev: dict[str, tuple[int, float]] = {}
        # client visti almeno una volta: restano come entità "not_home" quando escono
        self.known_clients: dict[str, dict[str, Any]] = {}
        self.platforms: list[str] = []

    async def _async_update_data(self) -> WaxData:
        try:
            wireless = await self.client.get_overview(1)
            system = await self.client.get_overview(2)
            names = await self.client.get_client_names()
            lan = await self.client.get_lan_status()
            port_speed = await self.client.get_lan_port_speed()
        except WaxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WaxError as err:
            raise UpdateFailed(str(err)) from err

        data = WaxData()
        data.uptime = _int(system.get("uptime"))
        if data.uptime is not None:
            boot = (dt_util.utcnow() - timedelta(seconds=data.uptime)).replace(second=0, microsecond=0)
            previous = self.data.boot_time if self.data else None
            # l'uptime arriva con qualche secondo di scarto: non far "saltare" il timestamp
            data.boot_time = previous if previous and abs((boot - previous).total_seconds()) < 120 else boot
        data.memory = {k: _int(system.get(k)) or 0 for k in ("memtotal", "memfree", "membuffers", "memcached")}

        for radio in wireless.get("wifinets", []):
            if radio.get("opmode") == "mon" or not radio.get("device"):
                continue
            band = _band(radio)
            dev = radio["device"]
            r = {
                "band": band,
                "up": bool(radio.get("up")),
                "channel": _int(radio.get("channel")),
                "frequency": radio.get("frequency"),
                "htmode": radio.get("htmode"),
                "hwmode": radio.get("hwmode"),
                "txpower": None,
                "bitrate": None,
                "clients": 0,
            }
            for net in radio.get("networks", []):
                if net.get("mode") != "Master":
                    continue
                key = str(net.get("networkname", "")).split("_", 1)[-1]  # wifi0_ssid_2 -> ssid_2
                active = bool(net.get("up")) and net.get("bssid") not in (None, "", EMPTY_MAC)
                assoc = net.get("assoclist") or {}
                if active and r["txpower"] is None:
                    r["txpower"] = _int(net.get("txpower"))
                    rate = str(net.get("bitrate", "")).strip()
                    unit = str(net.get("bitrate_unit", "")).strip()
                    r["bitrate"] = f"{rate} {unit}".strip() or None
                s = data.ssids.setdefault(
                    key,
                    {"name": net.get("ssid"), "up": False, "clients": 0, "bands": [], "vlan": net.get("vlan_id")},
                )
                if active:
                    s["up"] = True
                    s["bands"].append(band)
                s["clients"] += len(assoc)
                r["clients"] += len(assoc)
                for mac, info in assoc.items():
                    mac = mac.lower()
                    extra = names.get(mac, {})
                    data.clients[mac] = {
                        "mac": mac,
                        "ip": extra.get("ip") if extra.get("ip") not in ("", "0.0.0.0") else None,
                        "hostname": extra.get("hostname") if extra.get("hostname") != "Unknown client" else None,
                        "ssid": net.get("ssid"),
                        "band": band,
                        "rssi": _int(info.get("rssi")),
                        "mode": info.get("MODE"),
                        "idle": _int(info.get("idle")),
                        "rx_kb": _kb(info.get("rx_bytes")),
                        "tx_kb": _kb(info.get("tx_bytes")),
                    }
            data.radios[dev] = r

        # gli slot mai configurati hanno il nome di fabbrica (NETGEARxxxxxx_3...): non interessano.
        # Gli SSID configurati restano anche da spenti, così l'interruttore esiste comunque.
        data.ssids = {
            k: v
            for k, v in data.ssids.items()
            if SSID_KEY_RE.match(k)
            and (v["up"] or v["clients"] or not DEFAULT_SSID_RE.match(str(v["name"] or "")))
        }

        eth = next((d for d in lan.get("subdevices", []) if d.get("ifname") == "eth0"), {})
        data.lan = {
            "rx_bytes": _int(eth.get("rx_bytes")),
            "tx_bytes": _int(eth.get("tx_bytes")),
            "port_speed": port_speed,
            "ip": next((a.get("addr") for a in lan.get("ipaddrs", [])), None),
            "gateway": lan.get("gwaddr"),
        }

        # le interfacce della rete ospiti (ath01, ath11...) stanno su br-guest, non su br-lan
        try:
            guest = await self.client.get_bridge_status("guest")
        except WaxError:
            guest = {}
        subs = {d.get("ifname"): d for d in [*lan.get("subdevices", []), *guest.get("subdevices", [])]}
        data.rates = self._rates(eth, list(subs.values()))
        data.weak_threshold = self.weak_rssi
        data.weak = sorted(
            (c for c in data.clients.values() if c["rssi"] is not None and c["rssi"] < self.weak_rssi),
            key=lambda c: c["rssi"],
        )

        for mac, c in data.clients.items():
            self.known_clients[mac] = c
        return data

    def _rates(self, eth: dict[str, Any], subdevices: list[dict[str, Any]]) -> dict[str, float | None]:
        """Mbit/s dalla differenza dei contatori fra due letture. Alla prima lettura, o se un
        contatore riparte da zero (riavvio del Wi-Fi), il valore è None per un ciclo."""
        counters: dict[str, int | None] = {"lan_rx": _int(eth.get("rx_bytes")), "lan_tx": _int(eth.get("tx_bytes"))}
        for dev in subdevices:
            m = RADIO_IF_RE.match(str(dev.get("ifname", "")))
            if not m:
                continue
            radio = f"wifi{m.group(1)}"
            for d in ("rx", "tx"):
                v = _int(dev.get(f"{d}_bytes"))
                if v is not None:
                    counters[f"{radio}_{d}"] = (counters.get(f"{radio}_{d}") or 0) + v
        now = time.monotonic()
        rates: dict[str, float | None] = {}
        for key, value in counters.items():
            prev = self._prev.get(key)
            rate = None
            if value is not None and prev and value >= prev[0] and now > prev[1]:
                rate = round((value - prev[0]) * 8 / (now - prev[1]) / 1_000_000, 1)
            if value is not None:
                self._prev[key] = (value, now)
            rates[key] = rate
        return rates

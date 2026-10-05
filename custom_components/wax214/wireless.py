"""Costruzione del Save della pagina Wireless per accendere/spegnere un SSID.

Il modulo è quello che il browser invia davvero (catturato il 05/10/2026, firmware 2.1.1.3,
83 campi). Il server tratta i campi mancanti come "spento"/predefinito, quindi si manda
sempre il modulo intero. Le parti che dipendono dallo stato (SSID attivi, nomi, modalità
radio) si ricalcolano; le impostazioni radio fisse vengono dal modello. Se il modello non
corrisponde più alla configurazione, uci/changes mostra modifiche in più e il chiamante
annulla: vedi WaxClient.set_ssid_enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RADIOS = ("wifi0", "wifi1")
EMPTY_MAC = "00:00:00:00:00:00"

# SSID che usano la rete ospiti (dhcp.guest): il DHCP ospiti è attivo se almeno uno è acceso
GUEST_KEYS = frozenset({"ssid_2"})


@dataclass
class WirelessState:
    """Stato attuale letto da overview?status=1."""

    enabled: dict[str, set[str]] = field(default_factory=dict)  # radio -> {"ssid_1", ...}
    names: dict[str, str] = field(default_factory=dict)  # "ssid_1" -> "Rete di casa"
    hwmode: dict[str, str] = field(default_factory=dict)  # radio -> "11axg"
    htmode: dict[str, str] = field(default_factory=dict)  # radio -> "HT20"

    @classmethod
    def from_overview(cls, overview: dict[str, Any]) -> WirelessState:
        st = cls()
        for radio in overview.get("wifinets", []):
            dev = radio.get("device")
            if dev not in RADIOS:
                continue
            st.enabled[dev] = set()
            st.hwmode[dev] = str(radio.get("hwmode", ""))
            st.htmode[dev] = str(radio.get("htmode", ""))
            for net in radio.get("networks", []):
                if net.get("mode") != "Master":
                    continue
                key = str(net.get("networkname", "")).split("_", 1)[-1]
                st.names.setdefault(key, str(net.get("ssid", "")))
                if net.get("up") and net.get("bssid") not in (None, "", EMPTY_MAC):
                    st.enabled[dev].add(key)
        return st

    def with_ssid(self, key: str, enable: bool) -> WirelessState:
        new = WirelessState(
            enabled={r: set(s) for r, s in self.enabled.items()},
            names=dict(self.names),
            hwmode=dict(self.hwmode),
            htmode=dict(self.htmode),
        )
        for r in RADIOS:
            (new.enabled[r].add if enable else new.enabled[r].discard)(key)
        return new

    def is_on(self, key: str) -> bool:
        return any(key in self.enabled.get(r, ()) for r in RADIOS)


def _guest_ignore(st: WirelessState) -> str:
    return "0" if any(st.is_on(k) for k in GUEST_KEYS) else "1"


def build_fields(current: WirelessState, target: WirelessState, system_name: str) -> list[tuple[str, str]]:
    """Il modulo intero, nell'ordine del browser: le caselle per SSID descrivono `target`,
    i campi cbid.wireless.wifiN_ssid_M riportano lo stato di partenza (come fa la pagina)."""
    f: list[tuple[str, str]] = [
        ("wireless.wifi_mgmt.key", ""),
        ("cbid.dhcp.guest.ignore", _guest_ignore(target)),
        ("autoRF", "0"),
        ("wifijet", "0"),
        ("mesh_point_to_ap", "0"),
        ("bs_check_wifi0", "1"),
        ("bs_check_wifi1", "1"),
        ("bs_check_wifi2", "1"),
        ("save_auto_chan", "0"),
        ("country_change_chan", "1"),
        ("disable_radio2G", ""),
        ("iface_status2G", ""),
        ("wireless.wifi0.channel_config_enable", "0"),
        ("wireless.wifi0.channel", "auto"),
        ("wireless.wifi0.channel_config_list", "1,6,11"),
        ("wireless.wifi0.channel_config_status", "1"),
        ("wireless.wifi0.channel_config_group", ""),
        ("disable_radio5G", ""),
        ("iface_status5G", ""),
        ("wireless.wifi1.channel_config_enable", "0"),
        ("wireless.wifi1.channel", "auto"),
        ("wireless.wifi1.channel_config_list", ""),
        ("wireless.wifi1.channel_config_status", "1"),
        ("wireless.wifi1.channel_config_group", ""),
        ("cbid.wireless.wifi1.nochannel", "0"),
        ("cbid.system.system.SystemName", system_name),
        ("cbid.wireless.wifi0.country", "380"),
        ("cbid.wireless.wifi0.opmode", "ap"),
        ("cbi.cbe.wireless.wifi0.obeyregpower", "1"),
        ("cbid.wireless.wifi0.obeyregpower", "1"),
        ("cbid.wireless.wifi1.opmode", "ap"),
        ("cbi.cbe.wireless.wifi1.obeyregpower", "1"),
        ("cbid.wireless.wifi1.obeyregpower", "1"),
        ("cbid.wireless.wifi0.hwmode", current.hwmode.get("wifi0", "11axg")),
        ("cbid.wireless.wifi1.hwmode", current.hwmode.get("wifi1", "11axa")),
        ("cbid.wireless.wifi0.htmode", current.htmode.get("wifi0", "HT20")),
        ("cbid.wireless.wifi1.htmode", current.htmode.get("wifi1", "HT80")),
        ("cbid.wireless.wifi0.tpscale", "0"),
        ("cbid.wireless.wifi1.tpscale", "0"),
        ("cbid.wireless.wifi0.clientlimits_enable", "1"),
        ("cbid.wireless.wifi0.clientlimits_number", "64"),
        ("cbid.wireless.wifi1.clientlimits_enable", "1"),
        ("cbid.wireless.wifi1.clientlimits_number", "64"),
        ("cbid.wireless.wifi0.aggregation_enable", "1"),
        ("cbid.wireless.wifi0.aggregation_frame", "255"),
        ("cbid.wireless.wifi0.aggregation_byte", "50000"),
        ("mcastenhance", "6"),
        ("hwmode_11ax", "1" if current.hwmode.get("wifi0", "11axg").startswith("11ax") else "0"),
    ]
    for n in range(1, 5):
        key = f"ssid_{n}"
        on = target.is_on(key)
        f.append((f"cbid.wireless.wifix_{key}.disabled", "0" if on else "1"))
        if on:
            f.append((f"cbid.wireless.wifix_{key}.ssid", target.names.get(key, "")))
            for r in RADIOS:
                if key in target.enabled.get(r, ()):
                    f.append((f"wireless.{r}_{key}.disabled", "0"))
            f.append((f"cbid.wireless.wifix_{key}.guest_network", "1" if key in GUEST_KEYS else "0"))
    for r in RADIOS:
        for n in range(1, 9):
            key = f"ssid_{n}"
            on = key in current.enabled.get(r, ())
            f.append((f"cbid.wireless.{r}_{key}.disabled", "0" if on else "1"))
            if on:
                f.append((f"cbid.wireless.{r}_{key}.ssid", current.names.get(key, "")))
    f += [
        ("cbid.wireless.wifix_ssid_management_1.disabled", "1"),
        ("cbid.wireless.wifi0.fasthandover_status", "0"),
        ("cbid.wireless.wifi1.fasthandover_status", "0"),
        ("cbid.network.sys.WLANVLANEnable", "0"),
        ("submitType", "0"),
        ("cbid.wireless.wifi0.ath_count", str(len(target.enabled.get("wifi0", ())))),
        ("cbid.wireless.wifi1.ath_count", str(len(target.enabled.get("wifi1", ())))),
    ]
    return f


def expected_changes(current: WirelessState, target: WirelessState) -> dict[str, str]:
    """Le sole righe che uci/changes deve mostrare dopo il Save."""
    exp: dict[str, str] = {}
    for r in RADIOS:
        for key in set(current.enabled.get(r, ())) ^ set(target.enabled.get(r, ())):
            exp[f"wireless.{r}_{key}.disabled"] = "0" if key in target.enabled[r] else "1"
        if len(current.enabled.get(r, ())) != len(target.enabled.get(r, ())):
            exp[f"wireless.{r}.ath_count"] = str(len(target.enabled[r]))
    if _guest_ignore(current) != _guest_ignore(target):
        exp["dhcp.guest.ignore"] = _guest_ignore(target)
    return exp

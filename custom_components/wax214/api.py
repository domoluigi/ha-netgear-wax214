"""Client asincrono per l'interfaccia web LuCI del Netgear WAX214 (firmware 2.1.x).

Login: POST /cgi-bin/luci con username, md5(password + "\\n") e agree=1, più il
cookie is_login=1 che la pagina imposta via JavaScript. La risposta contiene il
token di sessione ;stok=... e il cookie sysauth. Tutte le letture sono GET su
/cgi-bin/luci/;stok=<stok>/admin/...
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import aiohttp

from .wireless import WirelessState, build_fields, expected_changes

LOGIN_PATH = "/cgi-bin/luci"
STOK_RE = re.compile(r";stok=([0-9a-f]{8,})")
MYID_RE = r'myid="{}"[^>]*>\s*([^<]*?)\s*<'
SERVICECTL_RE = re.compile(r"servicectl/restart/([\w,\-]+)'")


class WaxError(Exception):
    """Errore generico del client."""


class WaxAuthError(WaxError):
    """Credenziali rifiutate dall'access point."""


class WaxConnectionError(WaxError):
    """Access point non raggiungibile o risposta inattesa."""


class WaxUnexpectedChanges(WaxError):
    """Le modifiche in sospeso non sono quelle attese: niente è stato applicato."""

    def __init__(self, message: str, got: dict, expected: dict) -> None:
        super().__init__(f"{message} (trovate {got}, attese {expected})")
        self.got = got
        self.expected = expected


def hash_password(password: str) -> str:
    """Come md5.js della pagina (chrsz=8): conta solo il byte basso di ogni carattere."""
    return hashlib.md5(bytes(ord(c) & 0xFF for c in password + "\n")).hexdigest()


class WaxClient:
    """Sessione autenticata verso un WAX214."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        timeout: float = 20,
    ) -> None:
        self._session = session
        self._base = f"https://{host}" + ("" if port == 443 else f":{port}")
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._stok: str | None = None
        self._cookies: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- sessione

    async def login(self) -> None:
        """Apre una sessione nuova. Solleva WaxAuthError se la password è errata."""
        self._stok = None
        self._cookies = {"is_login": "1"}
        headers = {"Referer": self._base + LOGIN_PATH, "Origin": self._base}
        data = {
            "username": self._username,
            "password": hash_password(self._password),
            "agree": "1",
        }
        try:
            async with self._session.post(
                self._base + LOGIN_PATH,
                data=data,
                headers=headers,
                cookies=self._cookies,
                allow_redirects=False,
                ssl=False,
                timeout=self._timeout,
            ) as resp:
                body = await resp.text(errors="replace")
                for name, morsel in resp.cookies.items():
                    self._cookies[name] = morsel.value
                location = resp.headers.get("Location", "")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise WaxConnectionError(f"Connessione fallita: {err}") from err

        if "Invalid password" in body:
            raise WaxAuthError("Password errata")
        match = STOK_RE.search(location) or STOK_RE.search(body)
        if not match or "sysauth" not in self._cookies:
            raise WaxConnectionError("Login senza token di sessione (pagina inattesa)")
        self._stok = match.group(1)

    async def logout(self) -> None:
        """Chiude la sessione sul dispositivo (il WAX ha poche sessioni disponibili)."""
        if not self._stok:
            return
        try:
            await self._raw_get("logout", None)
        except WaxError:
            pass
        self._stok = None

    async def _raw_get(
        self, path: str, params: dict[str, Any] | None, root: str = "admin"
    ) -> tuple[int, str, str]:
        url = f"{self._base}/cgi-bin/luci/;stok={self._stok}/{root}/{path}"
        try:
            async with self._session.get(
                url,
                params=params,
                cookies=self._cookies,
                allow_redirects=False,
                ssl=False,
                timeout=self._timeout,
            ) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise WaxConnectionError(f"GET {path} fallito: {err}") from err

    @staticmethod
    def _is_login_page(status: int, body: str) -> bool:
        return status in (401, 403) or 'name="formname"' in body and 'id="password_plain_text"' in body

    async def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        """GET autenticato; se la sessione è scaduta rifà il login una volta."""
        async with self._lock:
            if not self._stok:
                await self.login()
            status, _ctype, body = await self._raw_get(path, params)
            if self._is_login_page(status, body):
                await self.login()
                status, _ctype, body = await self._raw_get(path, params)
                if self._is_login_page(status, body):
                    raise WaxAuthError("Sessione rifiutata dopo un nuovo login")
            if status != 200:
                raise WaxConnectionError(f"GET {path}: HTTP {status}")
            return body

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        body = await self.get_text(path, params)
        try:
            return json.loads(body)
        except ValueError as err:
            raise WaxConnectionError(f"GET {path}: risposta non JSON") from err

    # ---------------------------------------------------------------- letture

    async def get_device_info(self) -> dict[str, str | None]:
        """Nome, seriale, MAC, paese e firmware dalla pagina Panoramica."""
        html = await self.get_text("status/overview")

        def myid(name: str) -> str | None:
            m = re.search(MYID_RE.format(re.escape(name)), html)
            return m.group(1).strip() if m and m.group(1).strip() else None

        name = re.search(r'SystemName = repSpecHTML\("([^"]*)"\)', html)
        fw = re.search(r"var firmwareVersion = '([^']*)'", html)
        model = re.search(r"var model_name = '([^']*)'", html)
        return {
            "name": name.group(1) if name else None,
            "serial": myid("Device_Serial_Number_text"),
            "mac_lan": myid("lan_mac_text"),
            "mac_24g": myid("wifi24_bssid1_text"),
            "mac_5g": myid("wifi5_bssid1_text"),
            "country": myid("wifi_country_text"),
            "firmware": fw.group(1) if fw else None,
            "model": model.group(1) if model else "WAX214",
        }

    async def get_overview(self, status: int) -> Any:
        """overview?status=1 (reti e client), 2 (sistema), 3 (canali)."""
        params: dict[str, Any] = {"status": status}
        if status == 2:
            params["ipv6"] = 1
        return await self.get_json("status/overview", params)

    async def get_client_names(self) -> dict[str, dict[str, str]]:
        """clientInfo: 'mac|ip|os|hostname' -> {mac: {ip, os, hostname}}."""
        data = await self.get_json("status/clientInfo")
        out: dict[str, dict[str, str]] = {}
        for row in data.get("info", []):
            parts = (row or "").split("|")
            if len(parts) >= 4 and parts[0]:
                out[parts[0].lower()] = {"ip": parts[1], "os": parts[2], "hostname": parts[3]}
        return out

    async def get_lan_status(self) -> dict[str, Any]:
        """iface_status/lan: traffico del bridge, uptime, porta eth0 e SSID come subdevices."""
        data = await self.get_json("network/iface_status/lan")
        return data[0] if isinstance(data, list) and data else {}

    async def get_lan_port_speed(self) -> int | None:
        body = (await self.get_text("status/lan_port_speed")).strip()
        return int(body) if body.isdigit() else None

    # ---------------------------------------------------------------- scritture (UCI)
    #
    # Le modifiche passano da LuCI in due tempi: il POST del modulo le mette "in sospeso"
    # (uci/changes), saveapply le rende effettive riavviando il Wi-Fi (~35 s, tutti gli SSID).
    # Prima di applicare si confronta l'elenco in sospeso con quello atteso: se c'è altro
    # si annulla tutto con revert.

    async def post_form(self, path: str, fields: list[tuple[str, str]]) -> None:
        async with self._lock:
            if not self._stok:
                await self.login()
            url = f"{self._base}/cgi-bin/luci/;stok={self._stok}/admin/{path}"
            try:
                async with self._session.post(
                    url,
                    data=fields,
                    cookies=self._cookies,
                    headers={"Referer": url, "Origin": self._base},
                    allow_redirects=False,
                    ssl=False,
                    timeout=self._timeout,
                ) as resp:
                    body = await resp.text(errors="replace")
                    status = resp.status
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise WaxConnectionError(f"POST {path} fallito: {err}") from err
        if self._is_login_page(status, body):
            raise WaxAuthError("Sessione scaduta durante il salvataggio")
        if status not in (200, 302):
            raise WaxConnectionError(f"POST {path}: HTTP {status}")

    async def get_pending_changes(self) -> dict[str, str | None]:
        """uci/changes -> {'wireless.wifi0_ssid_2.disabled': '0', ...}; le opzioni rimosse valgono None."""
        html = await self.get_text("uci/changes")
        start = html.find('class="uci-change-list"')
        if start < 0:
            return {}
        block = html[start : html.find("</div>", start)]
        out: dict[str, str | None] = {}
        for tag, name, value in re.findall(r"<(ins|del)>([\w.@\-\[\]]+)=<strong>(.*?)</strong>", block):
            out[name] = value if tag == "ins" else None
        return out

    async def _action(self, path: str) -> str:
        """GET di un comando (revert/saveapply): accetta anche il redirect finale."""
        await self.get_text("system/ajax_setCsrf")
        async with self._lock:
            status, _ctype, body = await self._raw_get(path, {"redir": ""})
        if self._is_login_page(status, body):
            raise WaxAuthError(f"Sessione scaduta durante {path}")
        if status not in (200, 302):
            raise WaxConnectionError(f"GET {path}: HTTP {status}")
        return body

    async def revert_changes(self) -> None:
        await self._action("uci/revert")

    async def apply_changes(self, timeout: float = 120) -> list[str]:
        """saveapply registra le modifiche; il riavvio dei servizi lo lancia il JavaScript della
        pagina (servicectl/restart/<config>), poi si attende che servicectl/status dica 'finish'."""
        body = await self._action("uci/saveapply")
        match = SERVICECTL_RE.search(body)
        if not match:
            return []
        configs = match.group(1)
        async with self._lock:
            await self._raw_get(f"restart/{configs}", None, root="servicectl")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            await asyncio.sleep(3)
            try:
                async with self._lock:
                    _s, _c, status = await self._raw_get("status", None, root="servicectl")
            except WaxConnectionError:
                continue  # durante il riavvio l'AP può non rispondere
            if status.strip() == "finish":
                return configs.split(",")
        raise WaxConnectionError(f"Riavvio di {configs} non terminato entro {timeout:.0f} s")

    async def set_ssid_enabled(self, key: str, enable: bool, system_name: str, apply: bool = True) -> dict[str, str]:
        """Accende/spegne un SSID (es. 'ssid_2') su entrambe le radio.

        Salva il modulo intero, poi applica solo se uci/changes contiene esattamente le
        modifiche attese; altrimenti annulla e solleva WaxUnexpectedChanges. Con apply=False
        annulla sempre (prova a secco). Restituisce le modifiche in sospeso viste dopo il Save.
        """
        current = WirelessState.from_overview(await self.get_overview(1))
        if current.is_on(key) == enable:
            return {}
        target = current.with_ssid(key, enable)
        expected = expected_changes(current, target)
        # le righe "disabled" dell'SSID devono comparire; ath_count e dhcp.guest.ignore possono
        # mancare se la configurazione ha già quel valore. Nient'altro è ammesso.
        required = {k: v for k, v in expected.items() if k.endswith(f"_{key}.disabled")}

        def matches(changes: dict[str, str | None]) -> bool:
            return all(changes.get(k) == v for k, v in required.items()) and all(
                expected.get(k) == v for k, v in changes.items()
            )

        pending = await self.get_pending_changes()
        if pending and not matches(pending):
            # modifiche altrui (es. dall'interfaccia web): non si toccano
            raise WaxUnexpectedChanges("Ci sono già altre modifiche in sospeso sull'access point", pending, expected)
        if not pending:
            await self.post_form("network/wireless_device", build_fields(current, target, system_name))
        got = await self.get_pending_changes()
        if not matches(got):
            await self.revert_changes()
            raise WaxUnexpectedChanges("Il Save ha prodotto modifiche diverse dall'atteso: annullate", got, expected)
        if apply:
            await self.apply_changes()
            # la conferma del riavvio non basta: si guarda lo stato reale delle radio
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 90
            while True:
                try:
                    now = WirelessState.from_overview(await self.get_overview(1))
                    if now.is_on(key) == enable:
                        break
                except WaxConnectionError:
                    pass
                if loop.time() > deadline:
                    raise WaxConnectionError(f"{key}: applicato ma lo stato non è cambiato entro 90 s")
                await asyncio.sleep(5)
        elif not pending:
            # prova a secco: si annulla solo ciò che ha salvato questa chiamata
            await self.revert_changes()
        return got

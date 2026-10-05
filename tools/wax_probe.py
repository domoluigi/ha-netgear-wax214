"""Prova del client api.py fuori da HA: scarica le letture e le salva in ../discovery/probe_*.json.

Verifica anche il ri-login automatico: dopo la prima lettura invalida il token
e controlla che la lettura successiva riesca comunque.
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "custom_components" / "wax214"))
sys.path.insert(0, str(HERE))

from api import WaxAuthError, WaxClient  # noqa: E402
from wax_discovery import SECRET_JSON, ask_password  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else sys.exit("indica l'IP dell'access point come primo argomento")
OUT = HERE.parent / "discovery"


def save(name: str, data) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    (OUT / f"probe_{name}.json").write_text(SECRET_JSON.sub(r"\1***\3", text), encoding="utf-8")


async def main() -> None:
    pwd = ask_password(f"Password di admin@{HOST}")
    print(f"(ricevuti {len(pwd)} caratteri)")
    async with aiohttp.ClientSession() as session:
        client = WaxClient(session, HOST, "admin", pwd)
        try:
            await client.login()
        except WaxAuthError:
            print("Password errata")
            return
        print("login ok")
        save("device_info", await client.get_device_info())
        for n in (1, 2, 3):
            save(f"overview_{n}", await client.get_overview(n))
        save("clients", await client.get_client_names())
        save("lan", await client.get_lan_status())
        save("port_speed", await client.get_lan_port_speed())

        client._stok = "0" * 32  # token non valido: deve scattare il ri-login
        data = await client.get_overview(2)
        print("ri-login:", "OK" if isinstance(data, dict) and client._stok != "0" * 32 else "FALLITO")
        await client.logout()
    print("salvato in", OUT)


asyncio.run(main())

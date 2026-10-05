"""Prova di WaxClient.set_ssid_enabled fuori da HA.

Uso: python wax_ssid_test.py [host] [ssid_n] [on|off] [dry|apply]
  dry   (predefinito): salva, confronta uci/changes con l'atteso e annulla sempre.
  apply: se il confronto è identico applica davvero (il Wi-Fi si riavvia, ~35 s).
"""

import asyncio
import sys
import types
from pathlib import Path

import aiohttp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# pacchetto wax214 senza il suo __init__ (che importa Home Assistant)
pkg = types.ModuleType("wax214")
pkg.__path__ = [str(HERE.parent / "custom_components" / "wax214")]
sys.modules["wax214"] = pkg

from wax214.api import WaxClient, WaxUnexpectedChanges  # noqa: E402
from wax_discovery import ask_password  # noqa: E402

HOST = sys.argv[1] if len(sys.argv) > 1 else sys.exit("indica l'IP dell'access point come primo argomento")
KEY = f"ssid_{sys.argv[2] if len(sys.argv) > 2 else '2'}"
ON = (sys.argv[3] if len(sys.argv) > 3 else "on") == "on"
APPLY = (sys.argv[4] if len(sys.argv) > 4 else "dry") == "apply"


async def main() -> None:
    pwd = ask_password(f"Password di admin@{HOST}")
    print(f"(ricevuti {len(pwd)} caratteri)")
    async with aiohttp.ClientSession() as session:
        c = WaxClient(session, HOST, "admin", pwd)
        await c.login()
        info = await c.get_device_info()
        print(f"login ok - {KEY} -> {'ON' if ON else 'OFF'} - {'APPLICA' if APPLY else 'prova a secco'}")
        try:
            got = await c.set_ssid_enabled(KEY, ON, info["name"], apply=APPLY)
        except WaxUnexpectedChanges as err:
            print("RIFIUTATO, niente applicato:", err)
        else:
            if not got:
                print("SSID già nello stato richiesto: nessuna modifica")
            else:
                print("modifiche in sospeso = attese:", got)
                print("APPLICATE" if APPLY else "annullate (prova a secco)")
        print("in sospeso ora:", await c.get_pending_changes())
        await c.logout()


asyncio.run(main())

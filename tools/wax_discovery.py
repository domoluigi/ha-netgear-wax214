"""Esplorazione in sola lettura dell'interfaccia web del Netgear WAX214.

Fa il login come la pagina web (md5(password + "\n")), visita in GET le pagine
admin raggiungibili dal menu e salva l'HTML/JSON in ./discovery/ con token
di sessione e campi segreti oscurati. Non esegue azioni: gli URL che sembrano
comandi (reboot, apply, save, logout, ...) vengono saltati.

Uso:  .venv\\Scripts\\python.exe netgear_wax214\\tools\\wax_discovery.py [host] [utente]
La password viene chiesta a terminale e non viene salvata.
"""

import getpass
import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOST = sys.argv[1] if len(sys.argv) > 1 else sys.exit("indica l'IP dell'access point come primo argomento")
USER = sys.argv[2] if len(sys.argv) > 2 else "admin"
BASE = f"https://{HOST}"
OUT = Path(__file__).resolve().parent.parent / "discovery"
MAX_PAGES = 200

UNSAFE = re.compile(
    r"logout|reboot|restart|reset|factory|upgrade|flash|firmware_up|apply|commit|"
    r"save|delete|remove|restore|backup|revert|kick|disconnect|deauth|block|"
    r"set_|change|ping|traceroute|nslookup|diag|locate|led|scan|format|import|"
    r"upload|download|export|cert|wps|reconnect|renew|release|clear|erase",
    re.I,
)
SECRET_INPUT = re.compile(
    r'(<input[^>]*(?:name|id)="[^"]*(?:key|pass|psk|secret|radius|token)[^"]*"[^>]*value=")([^"]*)(")',
    re.I,
)
SECRET_JSON = re.compile(
    r'("(?:[a-z_]*key|[a-z_]*pass[a-z_]*|psk|secret|wpa_passphrase)"\s*:\s*")([^"]*)(")',
    re.I,
)


def redact(text: str, stok: str | None) -> str:
    if stok:
        text = text.replace(stok, "STOK")
    text = SECRET_INPUT.sub(r"\1***\3", text)
    text = SECRET_JSON.sub(r"\1***\3", text)
    return text


def safe_name(url: str) -> str:
    path = urlparse(url).path.split("/admin", 1)[-1] or "root"
    q = urlparse(url).query
    name = ("admin" + path + ("_" + q if q else "")).strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150]


def ask_password(prompt: str) -> str:
    """Finestra con campo mascherato: getpass nel terminale integrato legge un solo tasto."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        pwd = simpledialog.askstring("WAX214", prompt + ":", show="*", parent=root)
        root.destroy()
        return pwd or ""
    except Exception:  # noqa: BLE001 - senza GUI si ripiega sul terminale
        return getpass.getpass(prompt + ": ")


def main() -> None:
    pwd = ask_password(f"Password di {USER}@{HOST}")
    print(f"(ricevuti {len(pwd)} caratteri)")
    if not pwd:
        print("Nessuna password inserita.")
        return
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = "Mozilla/5.0 wax-discovery"

    s.get(f"{BASE}/cgi-bin/luci", timeout=15)
    # la pagina di login imposta questo cookie via JS prima del submit
    s.cookies.set("is_login", "1", domain=HOST, path="/")
    s.headers["Referer"] = f"{BASE}/cgi-bin/luci"
    s.headers["Origin"] = BASE
    r = s.post(
        f"{BASE}/cgi-bin/luci",
        data={
            "username": USER,
            # md5.js della pagina (chrsz=8) tiene solo il byte basso di ogni carattere
            "password": hashlib.md5(bytes(ord(c) & 0xFF for c in pwd + "\n")).hexdigest(),
            "agree": "1",
        },
        allow_redirects=False,
        timeout=15,
    )
    del pwd
    OUT.mkdir(parents=True, exist_ok=True)
    loc = r.headers.get("Location", "")
    m = re.search(r";stok=([0-9a-f]+)", loc + r.text)
    stok = m.group(1) if m else None
    login_info = {
        "status": r.status_code,
        "location": redact(loc, stok),
        "cookies": sorted(s.cookies.keys()),
        "stok_found": bool(stok),
        "headers": {k: redact(v, stok) for k, v in r.headers.items() if k.lower() != "set-cookie"},
    }
    (OUT / "_login.json").write_text(json.dumps(login_info, indent=2), encoding="utf-8")
    (OUT / "_login_body.html").write_text(redact(r.text, stok), encoding="utf-8")
    print("login:", login_info["status"], "stok:", login_info["stok_found"], "cookie:", login_info["cookies"])
    if not stok:
        why = "password errata" if "Invalid password" in r.text else "motivo sconosciuto"
        print(f"Login non riuscito ({why}). Vedi discovery/_login_body.html")
        return

    root = f"{BASE}/cgi-bin/luci/;stok={stok}/admin"
    start = urljoin(BASE, loc) if loc else root
    queue = deque([start, root])
    seen: set[str] = set()
    skipped: list[str] = []
    index = []
    assets: set[str] = set()

    while queue and len(seen) < MAX_PAGES:
        url = queue.popleft().split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        rel = url.replace(stok, "STOK")
        if UNSAFE.search(urlparse(url).path + "?" + urlparse(url).query):
            skipped.append(rel)
            continue
        try:
            resp = s.get(url, timeout=20, allow_redirects=False)
        except requests.RequestException as e:
            index.append({"url": rel, "error": str(e)})
            continue
        ctype = resp.headers.get("Content-Type", "")
        body = resp.text
        name = safe_name(url) + (".json" if "json" in ctype else ".html")
        (OUT / name).write_text(redact(body, stok), encoding="utf-8")
        index.append({"url": rel, "status": resp.status_code, "type": ctype, "bytes": len(body), "file": name})
        if resp.status_code in (301, 302) and "Location" in resp.headers:
            queue.append(urljoin(url, resp.headers["Location"]))
        for link in re.findall(r"""['"](/cgi-bin/luci/;stok=[0-9a-f]+/[^'"\s<>]*)['"]""", body):
            queue.append(urljoin(BASE, link.replace("&amp;", "&")))
        for link in re.findall(r"""['"](/luci-static/[^'"\s<>]+\.js)['"]""", body):
            assets.add(link)

    for a in sorted(assets):
        if "jquery" in a.lower():
            continue
        try:
            resp = s.get(urljoin(BASE, a), timeout=20)
            (OUT / ("static_" + re.sub(r"[^A-Za-z0-9._-]+", "_", a))).write_text(resp.text, encoding="utf-8")
        except requests.RequestException:
            pass

    (OUT / "_index.json").write_text(
        json.dumps({"pages": index, "skipped": skipped, "assets": sorted(assets)}, indent=2), encoding="utf-8"
    )
    try:
        s.get(f"{root}/logout", timeout=10, allow_redirects=False)
    except requests.RequestException:
        pass
    print(f"Pagine salvate: {len(index)}  saltate: {len(skipped)}  js: {len(assets)}  -> {OUT}")


if __name__ == "__main__":
    main()

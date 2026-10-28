# Netgear WAX214 per Home Assistant

Integrazione locale (niente cloud) per l'access point **Netgear WAX214**, firmware 2.1.x con interfaccia web LuCI.
Integrazione **di sola lettura**: mostra lo stato dell'AP e non scrive mai nulla sulla sua configurazione.

> Integrazione non ufficiale, non affiliata a NETGEAR. Provata su WAX214 firmware 2.1.1.3 con Home Assistant 2026.9.

## Installazione

**HACS** → menu ⋮ → *Repository personalizzati* → URL `https://github.com/domoluigi/ha-netgear-wax214`, tipo *Integrazione* → installa → riavvia Home Assistant.

**Manuale**: copiare `custom_components/wax214` in `/config/custom_components/` e riavviare.

Poi *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Netgear WAX214*: indirizzo IP, utente `admin`, password dell'interfaccia web dell'AP.

Richiede Home Assistant **2026.3** o successivo.

## Entità

| Tipo | Entità |
|---|---|
| Sensori | Client connessi (totale, per banda, per SSID; elenco dei client negli attributi), client con segnale debole (sotto la soglia RSSI, con l'elenco), canale 2.4/5 GHz, velocità in tempo reale (Mbit/s) della LAN e di ogni radio in ricezione/trasmissione, ultimo avvio, memoria usata, velocità porta LAN, traffico LAN ricevuto/trasmesso, potenza TX (disattivata) |
| Binary sensor | Radio 2.4/5 GHz attiva, SSID attivo. Gli SSID creati sull'access point dopo l'installazione ottengono da soli i loro sensori e binary sensor, entro un ciclo di aggiornamento |
| Device tracker | Opzionale: uno per ogni client Wi-Fi visto (creati disattivati) |

**Opzioni** (*Configura*): intervallo di aggiornamento (predefinito 30 s), creazione dei device tracker (predefinito: no; spegnendola i tracker già creati vengono rimossi) e soglia del segnale debole (predefinita −75 dBm).

Per non riempire il database di Home Assistant: i contatori del traffico LAN avanzano a passi di 100 MB, la memoria usata è un numero intero, le velocità hanno un decimale e l'elenco dei client negli attributi non include il segnale (cambierebbe a ogni ciclo). Le velocità sono la media fra due letture consecutive (quindi sull'intervallo di aggiornamento); dopo un riavvio di Home Assistant o del Wi-Fi restano vuote per un ciclo. Quelle delle radio sommano le interfacce di tutti gli SSID, rete ospiti compresa.

## Sola lettura

L'integrazione non ha interruttori e non invia moduli all'access point: legge e basta. Chi aveva installato una versione precedente (fino alla 0.4.x) trova gli interruttori SSID rimossi dal registro delle entità al primo avvio della 0.5.0.

## Come parla con l'AP

- Login: `POST /cgi-bin/luci` con `username`, `password = md5(password + "\n")`, `agree=1` e cookie `is_login=1`. La sessione è il token `;stok=…` nell'URL più il cookie `sysauth`; se scade, il client rifà il login.
- Letture: `admin/status/overview?status=1` (radio, SSID, client associati), `?status=2` (uptime, memoria), `admin/status/clientInfo` (nomi e IP), `admin/network/iface_status/lan` (traffico), `admin/status/lan_port_speed`, pagina `admin/status/overview` (modello, seriale, firmware).

## Strumenti

`tools/` contiene gli script usati per ricavare l'API (richiedono `requests`/`aiohttp`; la password viene chiesta in una finestra e non viene salvata):

- `wax_discovery.py <ip>`: visita in sola lettura le pagine dell'interfaccia e le salva in `discovery/` (con token e campi segreti oscurati);
- `wax_probe.py <ip>`: prova le letture del client;
- `make_brand.py`: rigenera le icone in `brand/`.

## Licenza

MIT

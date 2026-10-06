# Netgear WAX214 per Home Assistant

Integrazione locale (niente cloud) per l'access point **Netgear WAX214**, firmware 2.1.x con interfaccia web LuCI.
Legge lo stato dell'AP e permette di accendere/spegnere gli SSID.

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
| Binary sensor | Radio 2.4/5 GHz attiva, SSID attivo |
| Switch | Un interruttore per ogni SSID configurato. Quello del primo SSID (la rete principale) è creato **disattivato** |
| Device tracker | Opzionale: uno per ogni client Wi-Fi visto (creati disattivati) |

**Opzioni** (*Configura*): intervallo di aggiornamento (predefinito 30 s), creazione dei device tracker (predefinito: no; spegnendola i tracker già creati vengono rimossi) e soglia del segnale debole (predefinita −75 dBm).

Per non riempire il database di Home Assistant: i contatori del traffico LAN avanzano a passi di 100 MB, la memoria usata è un numero intero, le velocità hanno un decimale e l'elenco dei client negli attributi non include il segnale (cambierebbe a ogni ciclo). Le velocità sono la media fra due letture consecutive (quindi sull'intervallo di aggiornamento); dopo un riavvio di Home Assistant o del Wi-Fi restano vuote per un ciclo. Quelle delle radio sommano le interfacce di tutti gli SSID, rete ospiti compresa.

## Accendere/spegnere un SSID: cosa sapere

- **Ogni cambio riavvia tutte le radio**: il Wi-Fi cade per circa 30–35 secondi su **tutti** gli SSID, non solo su quello cambiato. È il comportamento del firmware, identico all'*Apply* dell'interfaccia web.
- L'operazione dura circa un minuto: l'interruttore risponde quando l'AP conferma il nuovo stato.
- **Protezione**: l'integrazione invia il modulo *Wireless* completo come farebbe il browser, poi legge l'elenco delle modifiche in sospeso (`uci/changes`). Applica **solo** se contiene esattamente il cambio dell'SSID richiesto; qualsiasi altra modifica viene annullata (*Revert*) e l'interruttore restituisce un errore, senza toccare la configurazione.
- Il modello del modulo è stato ricavato da un WAX214 con due SSID (rete principale + ospiti su `ssid_2`), 2.4 GHz in 11ax/HT20, 5 GHz in 11ax/HT80, canale automatico. Con configurazioni diverse la protezione può rifiutare il cambio: in quel caso apri una issue.

## Come parla con l'AP

- Login: `POST /cgi-bin/luci` con `username`, `password = md5(password + "\n")`, `agree=1` e cookie `is_login=1`. La sessione è il token `;stok=…` nell'URL più il cookie `sysauth`; se scade, il client rifà il login.
- Letture: `admin/status/overview?status=1` (radio, SSID, client associati), `?status=2` (uptime, memoria), `admin/status/clientInfo` (nomi e IP), `admin/network/iface_status/lan` (traffico), `admin/status/lan_port_speed`, pagina `admin/status/overview` (modello, seriale, firmware).
- Scrittura SSID: `POST admin/network/wireless_device` → controllo di `admin/uci/changes` → `admin/uci/saveapply` (registra) → `servicectl/restart/<config>` (riavvia i servizi) → attesa di `servicectl/status` = `finish` → rilettura dello stato.
- Le modifiche in sospeso sono condivise fra tutte le sessioni: se qualcuno ha modifiche non applicate nell'interfaccia web, l'interruttore si rifiuta di procedere.

## Strumenti

`tools/` contiene gli script usati per ricavare l'API (richiedono `requests`/`aiohttp`; la password viene chiesta in una finestra e non viene salvata):

- `wax_discovery.py <ip>`: visita in sola lettura le pagine dell'interfaccia e le salva in `discovery/` (con token e campi segreti oscurati);
- `wax_probe.py <ip>`: prova le letture del client;
- `wax_ssid_test.py <ip> <n> on|off [dry|apply]`: prova il cambio di un SSID (`dry` salva, controlla e annulla sempre);
- `make_brand.py`: rigenera le icone in `brand/`.

## Licenza

MIT

# DB-OPT-01 — dokončené produkční přebalení databáze stínového doplňku
**17. listopadu 2026, Home Assistant Raspberry Pi, add-on 0.6.36**

Rozsah: pouze interní `/data/evidence/evidence.sqlite` addonu `local_energy_priority_shadow`. Hlavní Home Assistant `home-assistant_v2.db`, SolaX Modbus, Tesla/EV, tarif, HA automatizace ani HEC LIVE nebyly změněny.

## Rozsah a měření

| Kontrola | Před | Po |
|---|---:|---:|
| Interní živá evidence SQLite | 429 359 104 B | 410 025 984 B |
| Ušetřené bajty | — | 19 333 120 B (4,50 %) |
| Ověřené tabulky | 47 | 47 |
| Ověřené jednotlivé řádky | 290 119 | 290 119 |
| Interní `rowid`, BLOB, schéma, ACK/sekvence | výchozí neměnné | přesně shodné |
| SQLite quick_check a foreign_key_check | PASS | PASS |

Přípravná read-only zkouška na šestihodinové přenosné kopii `/share/home-energy-priority-shadow/evidence.sqlite` vyšla 429 359 104 → 409 526 272 B; 47 tabulek a 289 566 řádků shodných. Rozdíl proti skutečné produkční kopii vznikl časovým odstupem: skutečný live snapshot měl v době cutoveru **290 119 řádků**, takže ušetřil 19,33 MB, nikoliv 19,83 MB. Obě hodnoty jsou pravdivé, **produkční výsledek je 410,03 MB**.

## Provedení a zálohy

- [PR #55](https://github.com/inenger/home-energy-coordinator-ha/pull/55) merge `39ed0c236fa05904db3b5a605efec3e41abf46ed`, PR CI i main CI obě joby PASS.
- Před změnou nativní Supervisor partial backup addonu 0.6.35, zkontrolované integrální informace a verze; interní identifikátory zůstaly výhradně na RPi. Starý zdroj 0.6.35 odložen v /share na RPi.
- `priority_shadow` bezpečně zastaven mimo noční okno, instalován ARM image 0.6.36, operátorský request `repack_lossless` + `observe_only` zapsán na RPi a při startu vykonán **před startem workerů**.
- SQLite vytvořila další úplný originální snapshot `/share/hec-db-repack-20261117/full-original.sqlite` (429 359 104 B), `VACUUM INTO` candidate (410 025 984 B). Všechny 47 tabulek a 290 119 řádků včetně rowid a úplných BLOBů porovnány, trvalé počty, sekvence, cursor maxima a schema shodné. Před atomickým swapem ověřena nezměněná transakční hranice živé DB; po výměně znovu SQLite integrity i count. Operace trvala 93,7 s a dosáhla stavu `COMPLETED.json / status=completed`.
- Request byl jednorázově archivován do `REQUEST.completed.json`, následný start tedy neprovede další automatické VACUUM. Plný originál /share a nativní backup jsou zachovány. Neúplná noc 30.10. a její původní vzorky jsou zachovány.
- Zvolená již nasazená retence zůstala 14denní pro dokončené raw evidence, 90denní pro SOC observations, přičemž přístup k historii, permanentní souhrny, SOC rozhodnutí, ACK/receipt a hash verifikace zůstávají. Žádná ztrátová deduplikace nebo zkracování historie.

## Health po restartu

Supervisor `started · 0.6.36 · observe_only`. Nový `sensor.nocni_stinovy_plan` z aktuálního časového okna publikuje verzi 0.6.36 a čerstvé SHA-256 validní stínové údaje; `collection_health=ok`, `monitor_publication=ok`, `evidence_pipeline=ok`, `pending_or_lost_batches=0`, `device_actions=0`. Stínová diagnostika publikuje nové vstupy. Základní SOC analytika může po startu publikační smyčky na první výpočet krátce čekat.

## Co není slibováno

Jednorázová úspora 4,50 % není důkazem trvalého růstu 0 B/den. SQLite využije uvolněné stránky při další retenci, ale samostatný 14denní interval stále generuje nová data a do budoucna bude třeba sledovat počet dní, uzavřené / neúplné noci a retenci. Rozsah úspory může být jiný při dalších verzích a různých datech. Globální Home Assistant Recorder ani jeho historie nebyly optimalizovány.

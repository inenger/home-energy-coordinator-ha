# 13.11.2026 – HEC LIVE v1, skutečné noční řízení HA

- [Živý HA package](ha_packages/night_live_coordinator.yaml) + [bezpečnost, rollback a testy](docs/LIVE_BATTERY_RESERVE_20261113.md): od 13.11. jsou tři nové HA automations ON; fyzické povely jdou přes HA, ne přes původní `priority_shadow 0.6.32`, který dál běží `observe_only`.
- 02:59:40 uložit původní `number.solax_backup_discharge_min_soc` a `number.solax_api_max_charge_current_setting` do perzistentních helperů; při FVE<=15 kWh reserve 100 %, >=50 kWh 25 %, mezihodnoty lineární. EV nejprve max12 A, 03–05 regulovat 6–16 A podle reálných L1/L2/L3; nad24,5 A emergency Stop. Změny cizího vlastníka nepřepisovat.
- 05:00 nezávislá obnovovací automatizace, retrigger každou minutu mimo okno. HA core config check a restart PASS, tři automations ON, `sensor.hec_live_skutecne_rizeni=idle` mimo noc, owner off. Přesné kontrolní limity 20 % a 16 A jsou obnovené.
- Reálné fyzické piloty 20→25→20 %; 16→15→16 A; 20→100→20 % – all readback PASS. E2E vlastní snapshot + fyzická změna 25/15 → nezávislá automatika vrací 20/16 a owner off PASS. Záloha HA config nativní `492373aa` + tar/sha v `/share/hec-live-deploy-20261113/`.
- **První skutečné automatické okno až 14.11.**, neprohlašovat energy safety/live phase protection za plně ověřené. Domácí baterii zatím nenabíjet ze sítě při EV (3 A DC/3x25A/nezvalidovaný fyzický adaptér). Stínový doplněk a data beze změn.

---

# Noční audit 0.6.32: 13. 11. 2026

- Kompletní read-only audit: [report](docs/NIGHT_AUDIT_0632_20261113.md). 1 443 pravidelných 5s vzorků, 1 444/1 444 ACK, 0 loss a 0 device actions. Preflight 02:59 valid, 5 transient invalid phase vzorků bezpečně odmítnuto.
- OPS-01: skutečná baterie 66 % → 20 % během EV nabíjení, 4,65 kWh DC; EV 15,92 kWh AC, síť 12,55 kWh za 1,8078 Kč/kWh (22,69 Kč). Přitom původní HA grid charge povolení OFF; stínový doplněk nic neovládal. AUTO-02: dvě možné duplicitní původní EV-priorita automatizace.
- SOC dedup 0.6.32: 134/134 hash PASS, 5,1455 → 3,1072 MB, 39,61 % úspora jen SOC domény. Runtime 0.6.32 se nemění; fyzické řízení stále NO-GO.

---

# Runtime 0.6.32 — optimalizace podle hodnoty dat, nikoli kvóty

- Poslední zadání **ruší plošné 7denní pravidlo**. Uchovat data 7/14/45/366
  dní podle skutečného využití. Bez umělého limitu MB/den, bez mazání.
- [Bezztrátová SOC deduplikace 0.6.32](priority_shadow/docs/STORAGE_DEDUP_0632.md)
  používá immutable `soc_decision_parts` + SHA-256 reference; původní
  `decision_hash` a payload jsou identicky rekonstruovány.
  RPi read-only data 8.11. 644/644, 11.11. 139/139: PASS.
- SOC BLOB + nové sdílené objekty: 8.11. 15,954→4,479 MB,
  11.11. 5,440→2,377 MB. To není celá databáze nebo reálné 24h I/O.
- RAM/priority duplication, outbox a šestihodinové zálohy se **nemění**
  bez nezávislého end-to-end důkazu. Otevřené RET/HIST/LIVE zůstávají.
- Downgrade na 0.6.31 *po novém kompaktovaném zápisu* vyžaduje
  izolovaný offline materializer; nikdy nevracet starý reader nad
  kompaktní rozhodnutí. 0.6.32 `observe_only`, žádné fyzické řízení.

---

# Field-level data-minimization study and new 7-day policy, 12. 11. 2026

- [New deep field-by-field report](docs/FIELD_RETENTION_DEEP_DIVE_20261112.md), [public 407-row table/field matrix](docs/FIELD_RETENTION_POLICY_MATRIX_20261112.csv). Private RPi inventory: **2,935 JSON/schema field paths**, with code-reference hints and proposed action. 43 physical tables, 384 observed top-level JSON fields. No raw state values exported to GitHub.
- **User policy: 7 days high-resolution raw, permanent *important results* (night/economic/model results, incident events, material decisions and pinned as-of versions)**. Previous 30d hot and forever raw design is superseded, not implemented.
- Measured source: 11.11 24.423MB stored, 7d avg 29.896MB/day; 6h full portable 502.485MB copy creates model ~2.01GB daily copy-write amplification. DB live 0.6.31 observe_only unchanged.
- Compression benchmark: SOC content-addressed version refs: 11.11 **5.440→2.374MB (56.4%)**, 8.11 **15.954→4.471MB (72.0%)**. RAM input_reports share all 24 fields with priority.inputs (1,440/1,440 and 1,443/1,443), ref reduces 2.607→1.580MB / 2.423→1.339MB. Random SHA object-ifying manual/owner reports **increased** storage 25–27%, rejected.
- Critical: current 14/21/45/60/90/366d analytics readers require migrated hourly/session aggregates **before any 7d purge**; preserve pending ACK and 30min issued SOC freshness. NET target **5–8MB/day** aspirational only, not achieved. RET-04 and DATA-07 documented. No SQL deletion, physical control, config or runtime edit. Audit-only no version bump.

---

# SQL evidence volume / retention study, 12. 11. 2026

- [Evidence volume and retention report](docs/STORAGE_VOLUME_ANALYSIS_20261112.md): 11 Nov 24.423 MB of stored rows, average 5–11 Nov 29.896 MB/day, trailing 24h 26.908 MB, 43 tables. Portable copy 502.485 MB at 07:24. These are logical records, not physical daily SSD writes.
- RET-02: every 6h full portable SQLite backup, estimated 2.01 GB/day of copy writes at today's DB size; preserve RPO until replacement validated.
- RET-03: all 20,154 transport chunks durable-ACKed, but retained. HIST-01 warns old Recorder days are empty; do not delete without restored archive read-through.
- DATA-05: 139 SOC decisions contain only 8 forecast_versions, plus repeated calibration and session. DATA-06: 1,440/1,440 identical cross-domain collection_snapshot.
- Propose 30d hot only after an immutable full-raw archival API, daily manifest SHA-256, tested restore/replay and offsite replication. No runtime edits, deletion or version bump.

---

# Hloubkový audit 0.6.31 – 12. 11. 2026

- [Kompletní audit k main c339139](docs/DEEP_AUDIT_0631_20261112.md): nové RET-01 (růst evidence proti 2 GiB), HIST-01 (staré SQL/ACK chunky nejsou v HA Recorder), UI-02 (RangeError na plan at), SUP-01 (watchdog=false), START-02 (02:59 session bez časované bariéry), UI-03 (nezobrazený preflight), QA-01 (RPi Node bez cs-CZ ICU).
- RPi: `0.6.31 / started / observe_only`, žádné fyzické povely; sběr/SQLite/monitor ok, ACK postupuje. Python 607 PASS za 333,5 s, JS 9 PASS + 1 lokální locale FAIL; GitHub CI PASS.
- Skutečná předchozí nativní záloha SHA-256/SQLite integrity/FK v izolovaném scratch PASS, plný Supervisor restore samostatně neověřen. Bez automatického mazání evidence; LIVE-01/02/03, N06-02, DB-01 zůstávají otevřené.
- Tento audit změnil pouze dokumentaci a reprodukční test; zdroj aplikace ani HA konfigurace se nemění a neprovádí se release bump.

---

# Aktuální vývoj 0.6.31 · 12. 11. 2026

- [Cena ČEZ INDI, audit noci a příprava 02:59](priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md).
- Běžící HA 0.6.30 absolvoval jednu úplnou noc 03–05 se zdravou evidencí; původní soukromý report je jen na RPi.
- Závazný rozsah: observe_only; pro noční audit ignorovat události po 05:00:01 jako činnost tohoto doplňku.
- Chybný audit ~185 Kč používal jiný senzor než graf. Podle uživatelského sensor.cez_indi_cenik platí obě hodiny NT 1,8078 Kč/kWh a 23,63 kWh odpovídá 42,72 Kč. Podle následného potvrzení uživatele 12. 11. 2026 byl tarifní senzor sestaven přesně podle smlouvy ČEZ a ceníku INDI a ověřen; smluvní ceník je pro tyto výpočty autoritativní.
- 1s kolektor a 5s rychlá smyčka běžely už od 02:55. 0.6.31 od 02:59 připraví analytický model a validuje aktuální fázové reporty; dvě nové sady až po 03 zůstávají povinné.
- `0.6.31` byla 12.11. nasazena na Raspberry Pi do HA, Supervisor `started/observe_only`. PR #42 a post-merge CI #106 PASS; živý ACK `committed_seq` 3→4, loss 0, monitor/evidence `ok`, 0 restartů. [Přesný důkaz](priority_shadow/docs/DEPLOYMENT_0631_20261112.md). Noc s preflightem 02:59 ještě neproběhla; N06-02, DB-01, LIVE-01/02/03 stále otevřeny.

---

# Stav 0.6.30

[Sedm oprav readiness auditu](priority_shadow/docs/READINESS_FIXES_0630.md), bez LIVE a nasazení. N06-02, DB-01 a LIVE stále otevřené. Historické auditní protipříklady zachované.

# Projektová paměť

Aktuální zdroj0.6.29, pouze observe_only.

[Kontrakt, regrese a odmítnuté varianty0.6.27](priority_shadow/docs/STANDALONE_0627.md).

[Předchozí neměnná verze tohoto dokumentu](https://github.com/inenger/home-energy-coordinator-ha/blob/2fe74836c3a87ec53184434e2c095180d48f3142/MEMORY.md); původní obsah zůstává v historii Git a není touto dodávkou přepisován zpětně.

## Aktuální pravidla

- Autoritativní nový balíček je priority_shadow; původní balíček se nekopíruje ani neaktualizuje novým runtime.
- Žádný fyzický akční adaptér. Historická měření, seed, provozní doklady a credentials zůstávají soukromé.
- DEP-01: místní kalibrace a vlastní sběr; zastavení legacy až po ověřené migraci.
- DB-04: porovnání recorder zpráv mimo gate, stabilní WAL a oddělený PASSIVE checkpoint při FULL.
- DATA-02: omezená četnost diagnostických náhledů a šestihodinové portable kopie mimo okno. Úplný journal transport zůstává.
- DB-01: příčina všech historických timeoutů není uzavřená; diagnostika SQL/commit/close a provozní ověření zůstávají nutné. N06-02 a LIVE blokátory zůstávají otevřené.
- První syntetická planner fixture neměla fit_period; druhá neobsahovala schéma priority_samples z produkčního maintenance entrypointu. Obě vyvolaly calculation_unavailable a byly opravené, nikoli potlačené.
- Vývojový baseline je veřejný strom předchozího vydání. Lokální testy, veřejná CI, merge a skutečné nasazení jsou samostatné důkazy. Nová celá noc není nahrazena syntetikou.


## Zdroj0.6.28

[Wallbox a zápisy](priority_shadow/docs/WALLBOX_WRITES_0628.md): EV-01 autorita wallboxu, PLN-01 koherentní učení rezervy, DB-05 příprava mimo gate a dávky recorder metadata. Fyzický adaptér se nepřidává. DB-01/N06-02 a LIVE zůstávají otevřené. Lokální testy, CI a nativní nasazení jsou samostatné důkazy.


## Zdroj 0.6.29

[DB-06](priority_shadow/docs/ANALYTICS_ADMISSION_0629.md): přerušitelné normální čekání pouze durable analytiky a zbývající no-op schema guardy. Skutečné SQL chyby a původní evidence zachované; DB-01 není uzavřená. První nová regrese odhalila další RAM DDL; opraveny všechny související entrypointy, nikoli oslabený test. Jen observe_only.


## Audit připravenosti 0.6.29

[Zdrojový audit](docs/READINESS_AUDIT_0629.md) má verdikt NO-GO pro fyzické řízení. Nové otevřené N06-03/N06-04/REC-02/DATA-03/DATA-04/MON-03/UI-01, explicitní LIVE-03. Counterexample PASS potvrzuje existenci vady, ne její opravu. Runtime beze změny, zdrojové a soukromé provozní doklady oddělené. DOC-01 zpřesňuje aktuální dokumentaci a verifikátor; historické texty zachované.

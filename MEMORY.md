# 22. 11. 2026 – PEAK-01 0.6.37 instalace na RPi potvrzena
- [Provozní přejímka](docs/DEPLOYMENT_PEAK_0637_20261122.md): merge PR #56 `9ad944945ee30c6518dc5a11e171b2b97d744be1`, PR CI oba joby PASS, 654 lokálních testů PASS, nativní Supervisor partial backup 0.6.36 před upgrade vytvořen a ověřen, předchozí zdroj zvlášť archivován.
- ARM image 0.6.37 postaven Supervisor, `started 0.6.37 observe_only`. `sensor.nocni_stinovy_plan` SHA PASS, health=ok, evidence_pipeline=ok, device_actions=0; `fast_loop.collection_worker.phase_peaks` reálný readback: `status=ok`, `breaker_a=25`, 3 čerstvé reporty L1/L2/L3 a správné timestampy v 8s okně, outside-window cadence 2,5s. Historie nočního nového `measured_phase_max_a` zatím neověřena, první noc 03–05 bude další validační bod; žádné HW povely.
- SolaX Modbus FAST1/MEDIUM5/DEFAULT5 ponechán. Kumulativní overrun není ekvivalentem ztráty reportu. Bez fyzického řízení.


---

# 22. 11. 2026 – PEAK-01 / Modbus 1s, zdroj 0.6.37

- Uživatel opravil předchozí překlep: **limit hlavního jističe je 3×25 A**, žádných 30 A AC; BMS baterie má samostatný DC limit, tyto veličiny nemíchat. Požadavek: zachytit krátké proudové špičky mezi 5s kroky a analyzovat přetížení 1s Modbusu.
- [Implementace a hranice](docs/PHASE_PEAK_CAPTURE_0637_20261122.md): RAM-only okno 8s nad novými `last_reported` třemi fázemi ze sekundového `SnapshotCollector`; bez diskových zápisů v collector vlákně, bez aktuačních adaptérů. Sběr → atomický snapshot → `MemoryControl.step` → `ram_control.observe` → záznam `phase_peak_window`; maximum všech fází aktualizuje `measured_phase_max_a`, >25 A nebo chybějící validační snímek virtuálně stop, nikoliv fyzický příkaz. Syntetika včetně spike mezi kroky, stale, duplicate, unavailable, reset a 25A guard.
- Read-only HA ukázal, že `overrun_count` je počet cyklů delších než jejich interval; není sám o sobě důkazem ztráty reportů. Při 1s rychlé skupině diagnostika `Healthy`, úspěšnost 100 %, 0 karanténovaných registrů; pomalejší běhy přes 1s existují. **Konfiguraci SolaXu neměnit** v tomto releasu, případný test 2s zvlášť.
- Nejnovější audit 21.–22.11. ukázal několik krátkých proudových špiček nezahrnutých v 5s highwater; privátní časové řady se do Gitu neexportují. První celá noc na reálné nové verzi potřebuje test proti historickému 1s Recorderu; předtím se nesmí tvrdit potvrzená produkční funkce.


---

# 17.11.2026 – DB-OPT-01 produkční cutover na RPi dokončen

- [Provozní evidence](docs/DEPLOYMENT_DB_OPT_0636_20261117.md): GitHub PR #55 merge `39ed0c2`, PR CI i main CI PASS; nativní partial Supervisor backup addonu v0.6.35, testovací portable preview a druhý původní snapshot /share.
- True internal addon `/data/evidence/evidence.sqlite`: **429 359 104 → 410 025 984 B**, úspora **19 333 120 B = 4,50 %**. Úplná kontrola všech **47 tabulek a 290 119 řádků** (včetně rowid, každého BLOBu, schématu, ACK cursorů), quick_check a FK PASS; operátorský request spotřebován a označen completed. Původní immutable snapshot zachován.
- Home Assistant Supervisor started 0.6.36 observe_only, čerstvý publikovaný monitor 0.6.36 SHA PASS, `collection_health=ok`, `monitor_publication=ok`, `evidence_pipeline=ok`, `pending_or_lost_batches=0`, `device_actions=0`. Další pravidelný SOC výpočet může startovat později než první publikační heartbeat.
- Zachována 14denní raw, 90denní SOC observation retence, sealed night sumáře, transportní SHA/ACK, SolaX 1s Modbus. Hlavní HA recorder a HEC LIVE nedotčeny.

---

# 17. 11. 2026 – DB-OPT-01 / 0.6.36 addon evidence.sqlite

- Výslovné zadání: optimalizovat **jen** interní stínovou DB `/data/evidence/evidence.sqlite` a její přenosný soubor, nikoliv `/homeassistant/home-assistant_v2.db`. Plný audit: [DB-OPT-01](docs/DB_OPT_0636_20261117.md).
- Snapshot 08:10 SEČ má 429 359 104 B, freelist 19 374 080 B. Read-only zkušební `VACUUM INTO` 409 526 272 B (−19 832 832 B); všech 47 tabulek a 289 566 řádků přesně shodných včetně rowid/transport BLOB/ACK. Aktuální interní live velikost určit po startu 0.6.36 zvlášť; snapshot nenahrazuje live DB.
- 14denní raw/90denní SOC observation retence už běží, nedokončenou noc 30.10. se 106,98min archivem chrání fail-closed. Deduplikace 0.6.33 už funguje; současné další rekomprese poskytují jen 0–3 % a riskují digesty. Zůstat u one-shot čistého VACUUM bez obsahu.
- Nový `offline_repack.run` se spustí pouze s přesným operator request na RPi před startem workerů; pořádné snapshot/backup/compare_all/atomic swap/rollback; fyzické HEC LIVE, SolaX/Tesla a HA recorder nedotčené.

---

# 17.11.2026 – potvrzené nasazení 0.6.35

- [Provozní evidence](docs/DEPLOYMENT_0635_20261117.md). PR #54, merge 4a9195c, PR i main CI PASS. RPi ARM64 build a aktualizace PASS, started/observe_only, device_actions=0, HEC LIVE odpojený. Před instalací nativní partial backup předchozí v0.6.34 (703 MB) a samostatné zdrojové zálohy na RPi.
- V HA nový SOC policy soc-energy-scenarios-v7-demand-adequacy-targets, winter_demand policy energy-adequacy-v2; SHA publisher PASS; active physical charge target None, live_ready=false. Pro 18.11. není ještě úplný horizont, proto se energetický 100% override správně nepoužije. Další celá noc 0.6.35 je dosud neověřená.
- Back Up Mode / 20% Min SOC / 70% backup charging ceiling / EV 16 A nezměněné. Nezapínat HEC LIVE bez nového výslovného požadavku.

---

# 17. 11. 2026 – WIN-01 energetický deficit: zdroj 0.6.35

- [Kontrakt, skutečný as-of replay a dokumentované neúspěšné testy](docs/WIN01_ENERGY_ADEQUACY_0635.md). V 0.6.34 chybně blokovala 100% desired target podmínka venkovní teploty ≤2 °C, přestože 16.–17.11. při +5 °C model hlásil net demand 14–15,3 kWh proti 8,8 kWh využitelné energie baterie.
- Nová `energy-adequacy-v2`: 100 % desired při **úplném** as-of horizontu a současně `central_net>=100 % battery usable` + `stress_net>=125 % battery usable`, **nezávisle na teplotě**, anebo při chladu ≤2 °C a stresovém deficitu ≥70 %. Jde o stínové modelové rozhodnutí, nikoli fyzickou akci. Nedostatek teploty nebrání samostatnému energetickému důvodu; nedostatek horizontu ano.
- Šest replayů 12.–17.11., archivované rozhodnutí cca 02:55 SEČ: 35,75,50,25,50,50 % původních cílů → ve všech šesti energeticky rizikových nocích desired 100 %. Původní historie není změněna. Den s dostatečnou FVE/nízkou spotřebou nesmí automaticky přejít na 100 %.
- Nový kód mění jen `priority_shadow` a dashboard, HEC LIVE stále vypnuto; 3×25 A proudové špičky, limit wallboxu, zálohy Google Drive a fyzická validace jsou jiná otevřená témata.

---

# 15.11.2026 – potvrzené nasazení 0.6.34 na RPi

- Merge `73612310f348` a CI `43746539754` PASS, RPi Supervisor aktualizoval samostatný stínový doplněk z 0.6.33 na 0.6.34, `started` a `observe_only` s `device_actions=0`. Běžné SolaX Back Up Mode/20 % rezerva, EVC16 A a HEC LIVE odpojené zůstaly beze změny.
- Před aktualizací byl vytvořen podporovaný partial native backup a záloha předchozího zdroje; soukromé identifikátory jsou pouze v provozním prostoru na RPi. Dashboard karta byla nahrazena a původní kopie zachována.
- V první přenosné databázové kopii byly skutečně vytvořeny 3 uzavřené noční souhrny (23–25.10.) s přesným SHA-256 vůči 517/517/539 původním řádkům. SQLite `quick_check=ok`, FK žádné, ACK outbox/receipts shodné, bez nepotvrzených řádků.
- Reálné smazání starších raw podléhá stále 12hodinovému časovému omezení, **zatím se neprovedlo**. Nová plná noc s 0.6.34 zatím neproběhla. Ekonomické vs zimní cíle byly v HA přeneseny v policy `soc-energy-scenarios-v6-cold-load-targets`; večerní as-of data (6,1 °C / předpověď min4°C, neúplný horizont) nevyžadují 100 %. [Provozní report](docs/DEPLOYMENT_0634_20261115.md).

---

# 15. 11. 2026 – 0.6.34: WIN-01 a RET-05 (nový zdroj)

- [Rozsah opravy a historický replay](docs/WIN_RET_RELEASE_0634.md). Nové poradní zimní cíle: při teplotě ≤2 °C a konzervativním hodinovém energetickém deficitu vůči baterii ≥70 % je `desired_target_soc_pct=100`; `economic_target_soc_pct` se uchovává odděleně, `physical_charge_target_soc_pct=None`. Hodnoty jsou shadow, **není to automatický povel**. EV priorita, 03–05 a fyzické nastavení SolaX/EV se nemění.
- BT1, záložní BT28, příkon TČ jako podpůrný signál; house profil už obsahuje TČ, žádné dvojí započtení. Causální archiv as-of i úplný horizont jsou povinné; při neplatné teplotě zůstává ekonomický model. Neimplikuje to ověřený COP či počasím řízené fyzické limity.
- RET-05: skutečná údržbová cesta nyní volá omezený `night.finalize_pending`; souhrn se zamkne jako immutable `sealed` pouze u dostatečně kompletní noci a s digestem původních řádků. `night_samples` se mažou až při souhlasném digestu. Při nesouladu/nekompletním dni fail-closed. Žádný přepis historie.
- RPi soukromý replay 15.11. (old 25 % → new desired 100 %) a 23–25.10. (517/517/539 uzavřených řádků v izolované SQLite) PASS. První falešné očekávání pokrytí 120 vs měřených 119,75 minut opraveno v testu; algoritmus se kvůli testu neměnil. Publikace/CI/nasazení jsou zvláštní akce.
- Explicitní zákaz znovu aktivovat HEC LIVE bez nového schválení. `Back Up Mode`, on-grid Min SOC 20 %, EVC podle uživatele, bez automatického prodloužení EV nabíjení mimo 03–05.

---

# 15.11.2026 — WIN-01: oprava zimního energetického zadání (bez runtime změny)

- [Zimní provozní kontrakt](docs/WINTER_OPERATION_POLICY_20261115.md); [Issue #52](https://github.com/inenger/home-energy-coordinator-ha/issues/52). Uživatel potvrdil správný režim SolaX Back Up Mode se základním 20% discharge Min SOC a dvouhodinové EV okno 03–05; nedosažení EV 80 % není chyba.
- Při mrazu / okolí 0 °C, FVE ~15 kWh a značném odběru TČ má být **požadovaný** cíl nabití domácí baterie až 100 %. Je oddělen od skutečně dosažitelného SOC, od fyzického setpointu a od nastavení on-grid Min SOC. WIN-01 zatím není implementováno.
- RPi 15.11.: BT1 −1,8 °C, BT28 −3,3 °C; čidlo TČ dostupné. Shadow `instant_fill` 100 % je pouze maximální modelový stínový cíl, nikoliv potvrzený fyzický příkaz ani důvod ke kritickému alarmu. Ekonomický `soc_planner` vracel 30 % a zkouší max 95 %, což nezohledňuje potvrzený zimní požadavek. Vzorky 03–05 ~1443, EV ~22,33 kWh, baterie 19 % bez nabíjení, 0 device actions.
- Aktuální `number.solax_backup_nightcharge_upper_soc=70 %` je jiný parametr než `number.solax_backup_discharge_min_soc=20 %`. Pro případnou budoucí live akci vyžaduje oddělenou validaci a obnovu. HEC LIVE nadále odpojen, doplněk v `observe_only`, bez automatické reaktivace.

---

# 13.11.2026 – DB 0.6.33: zpětná SOC/priority kompakce a retence

- Nový runtime 0.6.33 zachovává observe_only; dokument
  [DB optimalizace](docs/DB_OPTIMIZATION_RELEASE_0633.md).
  Nikdy automaticky nepřepnout HEC LIVE.
- 14 dnů detail priority/nočních/ram vzorků a potvrzeného přenosového
  deníku; 90 dnů SOC observation; denní souhrny, SOC rozhodnutí,
  důkazní data, revize a bezpečnostní události bez omezení.
- Migrace aktuálního souboru jen po stopu writerů. Kontrola
  plných SOC a priority hodnot, záloha a fail-closed rollback.
- Původní offline měření 529,08→409,63 MB je stará SOC pouze
  offline analýza, nikoliv nový produkční výsledek.
- Plná sada 621 testů skončila PASS ve 13:44; 7 cílených
  syntetických testů 0.6.33 PASS. Stav po nasazení ověřit
  samostatně.

---

# 13.11.2026 09:10 – LIVE pozastaven / noc 13.–14.11. observe_only

Po výslovném požadavku uživatele všechny tři nové HA automation OFF a odpojeny z aktivní konfigurace. Core check a restart PASS, automation entity unavailable, SolaX reserve 20 %, EV16 A. Shadow addon 0.6.32 started observe_only. Bez automatického re-enable bez nového schválení. Viz [provozní stav](docs/LIVE_BATTERY_RESERVE_20261113.md).

---

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

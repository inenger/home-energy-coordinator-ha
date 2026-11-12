## 0.6.30 · readiness opravy, 11. 11. 2026

Vstupní commit `dee01fc`. Sedm softwarových counterexample reprodukcí převedeno na akceptaci; originály uchovány jako readiness_counterexamples_0629.py/mjs. SOC první kandidát neuložil revokaci kvůli rollback při výjimce v SQLite transakci, poté opraven commit a pozdější raise. Asynchronní REST první varianta vyžadovala upravit staré testy závislé na synchronní odpovědi. Další kandidát pickle fingerprint selhal na determinismu po multiprocessing a watchdog chybně zahrnoval již potvrzené seq; obojí napraveno, skutečné spawn replay regrese po opravě PASS. Komplexní RPi testovací průchod přerušen kvůli ochraně HA hostitele, nenárokovat PASS. [Podrobný report](../../priority_shadow/docs/READINESS_FIXES_0630.md).

# Dohledatelná historie vývoje

Aktuální zdroj0.6.27, pouze observe_only.

[Kontrakt, regrese a odmítnuté varianty0.6.27](../../priority_shadow/docs/STANDALONE_0627.md).

[Předchozí neměnná verze tohoto dokumentu](https://github.com/inenger/home-energy-coordinator-ha/blob/2fe74836c3a87ec53184434e2c095180d48f3142/docs/history/DEVELOPMENT_HISTORY.md); původní obsah zůstává v historii Git a není touto dodávkou přepisován zpětně.

## Aktuální pravidla

- Autoritativní nový balíček je priority_shadow; původní balíček se nekopíruje ani neaktualizuje novým runtime.
- Žádný fyzický akční adaptér. Historická měření, seed, provozní doklady a credentials zůstávají soukromé.
- DEP-01: místní kalibrace a vlastní sběr; zastavení legacy až po ověřené migraci.
- DB-04: porovnání recorder zpráv mimo gate, stabilní WAL a oddělený PASSIVE checkpoint při FULL.
- DATA-02: omezená četnost diagnostických náhledů a šestihodinové portable kopie mimo okno. Úplný journal transport zůstává.
- DB-01: příčina všech historických timeoutů není uzavřená; diagnostika SQL/commit/close a provozní ověření zůstávají nutné. N06-02 a LIVE blokátory zůstávají otevřené.
- První syntetická planner fixture neměla fit_period; druhá neobsahovala schéma priority_samples z produkčního maintenance entrypointu. Obě vyvolaly calculation_unavailable a byly opravené, nikoli potlačené.
- Vývojový baseline je veřejný strom předchozího vydání. Lokální testy, veřejná CI, merge a skutečné nasazení jsou samostatné důkazy. Nová celá noc není nahrazena syntetikou.


##0.6.28 · wallbox and bounded write follow-up

Baseline0.6.27, synthetic PLN-01 counterexample in [issue36](https://github.com/inenger/home-energy-coordinator-ha/issues/36) confirmed the old defect. [Final source contract](../../priority_shadow/docs/WALLBOX_WRITES_0628.md) records source authority, transition uncertainty, bounded writer changes and acceptance boundaries. Private historical traces remain on RPi. New failures/adjustments must be appended, not silently removed.


## 0.6.29 · background admission

Baseline source79d3f6d/treecde4d286. [Contract and retained failed candidate](../../priority_shadow/docs/ANALYTICS_ADMISSION_0629.md). First new schema regression failed on remaining RAM DDL; production RAM/control/priority/audit/SOC/batch entrypoints fixed, regression unchanged. Reject increasing fast evidence TTL/SQLite timeout, resetting counters or claiming background waiting eliminated physical I/O. Older analytics timeout test adapted to cancellation/FIFO; actual SQL/partial failure tests retained. RPi lacks rg, source inventory used Python. Source, CI, native deployment and whole-night evidence are distinct.


## Audit připravenosti 0.6.29

Vstupní veřejný merge2b83d779fcf416b72a8827adde1aa7fdd37b7953, runtime beze změny. [Nálezy, odmítnuté hypotézy a kritéria](../READINESS_AUDIT_0629.md). První suite5PASS/1FAIL: audit očekával sémantickou zprávu, která se v produkci ztrácí; vznikl MON-03 a přesná kontrola source location. První rozšířená worker fixture použila e.sqlite místo požadovaného evidence.sqlite; opravena fixture, nikoli recovery aserce. Hypotéza backdating nového počasí vyvrácena skutečným timestampem po převzetí odpovědi. Původní pokusy uchované. Nová sada dokládá vady, neopravuje je. DOC-01 opravuje aktuální rozcestník, verzi registru a rozpadlou tabulku; historické dokumenty nemazat. Soukromé provozní důkazy zůstávají na RPi.

Předpublikační diff check ještě odmítl prázdný řádek na konci přeskládaného registru. Whitespace normalizován před commitem; žádná vzdálená publikace v neúspěšném pokusu neproběhla.


## 12. 11. 2026 – PRICE-01 a START-01, 0.6.31

Vstup main 5360c73d593b80b85d0e972ed828935ffd6ebe34, běžící RPi 0.6.30.
Původní automatický audit zaměnil senzor current_buy_electricity_price (7,7080 /
7,9089 Kč/kWh) za uživatelem používaný cez_indi_cenik (1,8078 Kč/kWh).
Uvedených ~185 Kč je chybný ekvivalent pro uživatelův ceník; oprava 23,63 ×
1,8078 = 42,72 Kč. Není ověřená smluvní fakturovaná částka.

Vyvrácena hypotéza, že sběr začne až ve 03. Produkční noční window zrychluje
collector na 1 s a RAM smyčku na 5 s již v 02:55. Skutečný nedostatek byl
předsestavení session/modelu a předběžná kontrola fáze.
Přidán read-only preflight od 02:59; před 03 žádné RAM sessions / events /
commands / lease, dvě nové sady po 03 povinné, DST dvojitá hodina ošetřena.

První syntetický test neplatné fáze FAIL: fixture měnila výkon L2 na identickou
výchozí hodnotu, takže nevytvořila rozpor. Opravena pouze fixture na fyzicky
nekoherentní proud L2 0,1 A; produkční ochrana nebyla oslabena. Následná
přímá nová sada PASS. CI, merge a nasazení jsou samostatné důkazy.
Původní soukromá data zůstávají na RPi, nikoli ve veřejném GitHubu.

[Plný kontext](../../priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md).


## 12.11.2026 – dodatečné potvrzení autority ceníku ČEZ INDI

Uživatel výslovně opravil předchozí tvrzení asistenta, že ceník nebyl nezávisle
ověřen: tarifní čidlo `sensor.cez_indi_cenik` bylo již sestaveno **dle
skutečné smlouvy ČEZ a ceníku INDI**, doloženo a ověřeno. Původní zdokumentovaná
pochybnost je proto zastaralá a nesmí se dál citovat jako otevřené riziko.
Měřený nákup 03:00–05:00 dne 12.11 se oceňuje **1,8078 Kč/kWh**; 23,63 kWh
odpovídá **42,72 Kč**. Předchozí chybný audit ~185 Kč používal nesouvisející
cenový senzor. Žádná změna ceníku, stávajících automatizací či fyzické akce
z tohoto opravení nevyplývá. Původní text chybného předpokladu zůstává výše
v chronologii zachovaný, novější autorita je tento opravený záznam.


## 12. 11. 2026 – instalace 0.6.31 po cenové korekci

Veřejný základ `7b38dc7216ce23b98cda82217addb7163103d312`,
PR #42, CI PR #105 a main #106: dvě job sady každé PASS.
Aktivní HA byl 0.6.30 / `started` / `observe_only`. Před stopem pořízena
nová nativní Supervisor partial záloha 0.6.30 a ověřena identita doplňku;
odděleně zachován zdrojový rollback, kontrolní součet a lokální log.
Instalátor zastavil pouze stínový doplněk, nahradil jeho Docker context,
provedl `store reload` / `apps update` a ověřil 3× nové `started` 0.6.31.
Build na RPi byl pomalejší, ale neselhal; nezaměňovat trvající build s výpadkem.

Přímý post-start první monitor vykazoval krátce `starting` a `committed_seq=0`,
což samo nebylo označeno za PASS. Následující dva čerstvé odečty prokázaly
`committed_seq` 3→4, `collection_health=ok`, `evidence_pipeline=ok`,
`monitor_publication=ok`, `journal_transport=ok`, 0 ztrát/worker restartů,
`device_actions=0` a zachování uzavřeného 12.11. v history. Jde o důkaz
skutečného dne po deploy, nikoli o důkaz reálného 02:59 preflightu 13.11.
Při tomto kroku nebyla žádná chybná hypotéza potlačena ani mazána historie.
[Provozní report](../../priority_shadow/docs/DEPLOYMENT_0631_20261112.md).

Celé identifikátory backupu, živé JSON a logy zůstaly pouze na Raspberry Pi.


## 12. 11. 2026 – nezávislý audit main c339139 / 0.6.31

[Celý evidence-based report](../DEEP_AUDIT_0631_20261112.md).
RPi started/observe_only, durable ACK roste, 0 aktuální loss/restart.
Python 607 PASS (333,487 s). JS 9 PASS; původní FAIL
`test_deep_fixes_0613.mjs` `'2.5' !== '2,5'` vysvětlen
lokálním Node bez cs-CZ ICU; neoslaben produkční kód ani test.
UI-02 nový kontrapříklad reprodukoval RangeError při třech
vadných datumech přes celý card.render.
SQL dbstat doložilo RET-01 (479,2 MiB a 2 GiB budget).
Dva staré dny mají 1441/1439 potvrzených SQL chunků,
ale HA Recorder 0: HIST-01. Pozor: větší GET na novější den
zastavil jen 4MB limit **auditního helperu**, ne produkční HTTP.
SUP-01 watchdog=false, START-02 scheduling mezera, UI-03
bez preflight labelu. Plná ZIP→SQLite izolovaná záloha
SHA, quick/integrity_check, FK PASS; ne celý Supervisor restore.
Rizika N06-02/DB-01/LIVE ponechána otevřená. Privátní podklady RPi.

## 12.11.2026 – precise daily SQL evidence and storage churn

Source: main c9f9a1f3fbda94f2b2a4cbe0496e8a6fe17ed8d4,
HA priority_shadow 0.6.31, read-only portable SQLite copy made 07:24.
43 tables counted through SQLite dbstat/length aggregates; 11.11
24.423 MB logical row bytes (23.636MB compressed blobs), 12,743 rows.
7 full days mean 29.896MB, rolling 24h 26.908MB; DB btree
502.485MB, sum logical all rows 452.472MB, index pages 15.385MB.
Planning extrapolation roughly 33.2MB of B-tree capacity growth/day is
NOT measured 24h physical disk I/O: no equivalent prior-day snapshot,
because previous Supervisor backups were removed from /backup.
That rejected assumption is preserved, not presented as measurement.

Separate backup churn from DB net growth: actual configured
portable_backup_interval_s=21600s, each full SQLite copy currently
502.485MB, 4 per day would copy 2.01GB/day (model, not observed IO count).
Forecast_versions from 139 SOC decision rows contain only 8 unique payloads,
independent compressed-field 2.726MB repeated versus 0.156MB unique;
calibration_summary 3 unique, session 2 unique across 1440 rows;
cross-table collection_snapshot identical 1440/1440. 20154 outbox
rows and 20154 ACK receipts, all 11.11 rows acknowledged.
Explicit warnings: no blanket delete of durable outbox because
HIST-01 established Recorder purge; don't remove historical SOC data
before hash-equivalent replay and archive restore are proven.

The archive policy remains design-only. 6h RPO and live addon untouched.
Raw private measurements retained only on Raspberry Pi; public
GitHub has redacted aggregate statistics and acceptance requirements.
[Full design and distribution](../STORAGE_VOLUME_ANALYSIS_20261112.md).

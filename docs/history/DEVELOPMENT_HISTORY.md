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


## 12.11.2026 – per-field retention deep dive, decision history and rejected variants

Entry commit 3e188301ab4cf37ee31746e2d8d92f6464f310e7;
actual HA remains priority_shadow 0.6.31, started, observe_only.
User rejected storing ~30 MB daily and proposed 7-day raw retention with
permanent important results, replacing previous 30-day hot/forever raw
recommendation at *design* level only.

A read-only RPi SQLite scan produced 2,935 path-level metrics, 384
top-level JSON fields across 43 SQL table schemas; public report shares
only aggregate/schema, private nested paths stay on RPi. The first
field-inventory attempt used a slow literal regex per field; changed to
precomputed token occurrence counts. This source-literal count is a heuristic,
not proof of usage/absence. Counterfactual nested test initially used
Counter.update(dict of payload values) and raised TypeError; corrected
to update(keys); final benchmark/replay measurements completed and original
failed attempt was not mistaken for a runtime error.

Measured: SOC full BLOBs 11.11 5.440→2.374 MB (56.4% savings)
and 8.11 15.954→4.471MB (72.0%) by version content refs.
RAM input_reports exactly match priority inputs for all 24 common keys
at all 1,440/1,440 and 1,443/1,443 sampled frames; RAM BLOB
11.11 2.607→1.580MB, 8.11 2.423→1.339MB.
Rejected: wrapping manual_control and owner_reports each in SHA objects
caused **25–27% increase**, not savings; their timestamps vary. Shared
common variants saved only 0.119 MB 11.11 / 0.048MB 8.11, not worth
prioritizing. Reduced priority input projection 5.577→3.212MB 11.11,
but incompatible with all 24 RAM reads until canonical input layer exists:
the savings were not double-counted. Rough SOC signatures
8.11 644/23 and 11.11 139/28 are NOT equivalent full decisions;
30min issued_at validity and revocations must remain.

7d raw would currently break existing 14/21/45/60/90/366d readers;
RET-04/DATA-07 marked OPEN. Proposed warm aggregates for required
lookbacks and permanent important summaries, not permanent full raw.
New field-policy CSV is proposal only; no SQL deletion, database compact,
new HA version, physical action, tariff or automation modification.
[Full documented findings](../FIELD_RETENTION_DEEP_DIVE_20261112.md).


## 12.11.2026 – kandidát 0.6.32, SHA immutable SOC dedup

Base `7c2ee620c46e97f7c9e1f5c7c33e79f6d3413f39`,
RPi HA 0.6.31 started/observe_only. Uživatel odvolal pevný 7d RAW
interval a 5–8 MB/den jako limit; dle účelu ponechat 14/45/366d
i déle bez omezování. Implementace: `soc_decision_parts`
obsahově adresované verze a obal v `soc_decisions`,
plná původní evidence rekonstruována přes SHA.
Reálný read-only snapshot 8.11. 644/644 originální pack SHA,
15,9543→4,4791 MB; 11.11. 139/139, 5,4401→2,3770 MB.
Nejde o měření celé SQLite, WAL ani fyzického 24h I/O.

Negativní pokusy a výsledky: první test očekával rollback vnější
SQLite context přes vnořené `record_decision` a FAIL (1 row persisted),
původní API to také negarantovalo. Test upraven na reálný fault mezi
objekty a rozhodnutím uvnitř vlastní transakce, rollback PASS.
Legacy `test_F07_full_runtime_metadata` přímo rozbaloval raw BLOB
jako původní JSON a FAIL `KeyError: decision_hash`.
Nový test ověřuje plnou hydrataci a stejný SHA, PASS.
Přístup naivních SHA objektů pro RAM owner/manual byl v předchozím
auditu odmítnut, jelikož zvýšil data o 25–27 %.
Nevypínat 6h backup ani nemazat ACKed journal záznamy.
Přidán pouze offline materializer pro downgrade 0.6.31,
který nemodifikuje vstupní databázi.
Bez změny nočního algoritmu a reálného nabíjení.

## 13.11.2026 – post-release real night audit 0.6.32

[Evidence, exceptions and limitations](../NIGHT_AUDIT_0632_20261113.md). RPi SQLite portable snapshot + HA read-only Recorder + automation YAML: 1 443 priority and 1 443 RAM frames, 1 444/1 444 durable ACK, no loss/restart/device actions. Original suspicion of energy model error was rejected: 18,37 kWh is counterfactual grid scenario, actual 12,55 kWh measured at meter. EV 15,92 kWh AC, battery 4,65 kWh DC discharge and SOC 66→20 %. Source ceník stable 1,8078 Kč/kWh, total ~22,69 Kč. Flag for original cheap battery charging was OFF; physical discharge is NOT caused by this observe-only addon. Ops OPS-01 and AUTO-02 remain open. Five phase invalid samples safely rejected near transitions. SOC new shared-part path: 134/134 cryptographic verification, original equivalent 5,1455 MB vs compact + unique 3,1072 MB; 39,61 % SOC-domain saving only, not full DB. No source, physical, price, automation, or retention changes. No raw private time series in Git.


## 13.11.2026 – skutečné HEC LIVE řízení v samostatné HA package

[Plná dokumentace](../LIVE_BATTERY_RESERVE_20261113.md).
Po výslovném povolení fyzického řízení uživatelem bylo pro
stávající SolaX X3 Hybrid G4 / EVC 11 kW instalováno omezené
skutečné řízení `number.solax_backup_discharge_min_soc` a
`number.solax_api_max_charge_current_setting` přímo přes tři
HA automations. Stínový add-on 0.6.32 se neměnil.
Před první změnou snapshot, vlastnictví a compare-and-swap
po 05:00. 3x25 A ochrana 20/22 A phase target + emergency stop
≥24,5 A. Neprovádělo se grid Force Charge ani přepnutí
inverter Work Mode či VPP přímé registry. Nativní config záloha
`492373aa` a samostatný tar. Ověřen `ha core check` PASS,
Core restart PASS, entity HEC Live a 3 automations ON.
Fyzické body write/readback reserve20→25→20 a
20→100→20, EV16→15→16, **automatický recovery**
od 25/15 do 20/16 PASS s uvolněním owner state.
První noční uplatnění teprve 14.11; současná shoda
povel/readback neprokazuje hard-real-time ochranu jističe.

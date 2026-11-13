# Aktuální stav a rozcestník projektu

<!-- shadow-version: 0.6.32 -->

Stav zdrojového kandidáta k 12. 11. 2026. Historické poznámky v MEMORY a starších
auditech popisují tehdejší stav; pro současné otevřené položky použijte tento
rozcestník a [registr nálezů](KNOWN_ISSUES.md).

| Oblast | Autoritativní zdroj |
|---|---|
| Stínový doplněk 0.6.31, pouze observe_only | [config](../priority_shadow/config.yaml), [runtime](../priority_shadow/energy/core.py), [metadata](../priority_shadow/pyproject.toml) |
| Původní koordinátor, samostatný balíček | [config](../energy_coordinator/config.yaml) |
| Známé chyby, nejistoty a podmínky uzavření | [KNOWN_ISSUES](KNOWN_ISSUES.md) |
| Chyba → regresní test → rozsah důkazu | [TEST_MATRIX](TEST_MATRIX.md) |
| Vydání, diagnostika, záloha a obnova | [RELEASE_RUNBOOK](RELEASE_RUNBOOK.md) |
| Chronologie pokusů včetně FAIL a slepých cest | [DEVELOPMENT_HISTORY](history/DEVELOPMENT_HISTORY.md) |
| Doplnění veřejné historie a dokumentace | [Uzávěrka dokumentace](history/DOCUMENTATION_CLOSEOUT_20261106.md) |
| Dřívější regresní mapování | [FIX_HISTORY](../priority_shadow/docs/FIX_HISTORY.md) |
| Architektura a energetické principy | [ARCHITECTURE](../priority_shadow/docs/ARCHITECTURE.md), [ALGORITHM](../priority_shadow/docs/ALGORITHM.md), [DATA](../priority_shadow/docs/DATA.md) |

## Zveřejněné opravy a důkazy

Veřejný kód 0.6.24 je v [PR #28](https://github.com/inenger/home-energy-coordinator-ha/pull/28).
Jeho merge je `02de19a4022678ec3e36b936dbe8544873450487`.
[PR CI](https://github.com/inenger/home-energy-coordinator-ha/actions/runs/42261940030)
i [CI tohoto merge](https://github.com/inenger/home-energy-coordinator-ha/actions/runs/42265690022)
prošly. Jsou to důkazy přesného veřejného zdroje, nikoli trvalé sledování HA.
Dokumentační změna nad tímto základem nemění runtime verzi ani nasazení.

| Verze / nález | Popis a odmítnuté varianty |
|---|---|
| 0.6.18 | [Perioda sběru, čas rozhodnutí, oddělení pomalé práce](../priority_shadow/docs/COLLECTION_FIXES_0618.md) |
| 0.6.19 | [SQLite koordinace a rozlišení lokálního timeoutu od BUSY/I/O](../priority_shadow/docs/SQLITE_FIXES_0619.md) |
| 0.6.20 | [RAM regulátor, spawn procesy, omezené fronty a trvalá evidence](../priority_shadow/docs/CONTROL_ISOLATION_0620.md) |
| 0.6.21 | [Pracovní režim a uložený ruční podrežim](../priority_shadow/docs/MANUAL_MODE_FIX_0621.md) |
| 0.6.22 | [Generace poruch, obnova pomocných procesů, neměnné uzavření](../priority_shadow/docs/RECOVERY_FIXES_0622.md) |
| 0.6.23 | [EV rozběh, overflow, trvalá analytika, dohled a souběžné reap](../priority_shadow/docs/NIGHT_FIXES_0623.md) |
| 0.6.24 | [Hot záloha, konzistentní snímek, sentinel a obnova](../priority_shadow/docs/HOT_BACKUP_0624.md) |

Předchozí audity se opravami nepřepisují:
[readiness 0.6.21](../priority_shadow/docs/READINESS_AUDIT_0621.md),
[audit 0.6.22](NIGHT_AUDIT_0622_20261105.md),
[následný audit dostupnosti](NIGHT_AUDIT_20261106.md).
Historický reproduktor může úspěšným návratovým kódem potvrdit **existenci
staré vady**. Pro novou verzi je rozhodující odpovídající regresní test.

## Co nelze zaměnit

- Lokální commit, GitHub větev, merge, CI a skutečná instalace jsou různé stavy.
- Soukromé provozní protokoly, databáze a měřené řady zůstávají na RPi.
  Veřejný registr obsahuje obecný problém, postup, kód a syntetické regrese.
- Pozorovaný stav HA není fyzický heartbeat zařízení.
- Modelová AC/DC energie, SOC a syntetická noc nejsou skutečné nabíjení.
- Zelené testy nedokazují nepřítomnost všech chyb. Otevřené položky níže
  nesmějí zmizet změnou označení vydání nebo smazáním chybové historie.

## Připravený zdroj 0.6.25

[Deník a SQLite](../priority_shadow/docs/JOURNAL_SQLITE_0625.md) opravují DB-02/MON-02. DB-01 a N06-02 nejsou tímto uzavřené. Publikace, CI a instalace se dokládají samostatně.

## Připravená oprava 0.6.26

[Stabilní nativní archiv a nečinné DB čtení](../priority_shadow/docs/BACKUP_IDLE_0626.md). BACKUP-02 má opravu v kódu; uzavření vyžaduje skutečný Supervisor archiv a oddělenou obnovu. DB-03 opravuje no-op DDL, nikoli všechny příčiny DB-01.

[Historie vývoje 0.6.26](history/BACKUP_IDLE_0626.md) obsahuje i odmítnuté varianty a první neúspěšný kandidát.


## Připravený zdroj0.6.27

[Samostatný kontext a omezená disková práce](../priority_shadow/docs/STANDALONE_0627.md). DEP-01 vyžaduje ověřenou migraci; DB-04 odstraňuje další konkrétní writer mechanismy. Historická příčina všech DB-01 a N06-02 není uzavřená. Pouze observe_only.


## Zdroj0.6.28

[Wallbox a omezené zápisy](../priority_shadow/docs/WALLBOX_WRITES_0628.md). EV-01/PLN-01/DB-05 mají zdroj a syntetické regrese. Provozní nasazení a nová noc se dokládají odděleně. Staré důkazy ani otevřené blokátory fyzického řízení se nepřepisují.


## Zdroj 0.6.29

[Čekání analytiky a zbývající no-op DDL](../priority_shadow/docs/ANALYTICS_ADMISSION_0629.md). DB-06: pomocná analytika má přerušitelnou normální FIFO frontu, rychlá evidence zachovává krátkou mez; skutečné SQLite chyby zůstávají chybami. DB-01/N06-02/LIVE zůstávají otevřené. Nová celá noc se ověřuje odděleně.


## Audit připravenosti současného zdroje

[Úplný audit 0.6.29](READINESS_AUDIT_0629.md): NO-GO pro fyzické řízení, chybějící adaptér a ověřený hardwarový timeout. Nové protipříklady sběru, ACK dohledu, integrity a UI jsou otevřené nálezy; zelený counterexample test není oprava. Tato dokumentační/testovací změna nemění runtime ani instalaci.

## Opravy v 0.6.30

[Kontrakt oprav sedmi softwarových nálezů](../priority_shadow/docs/READINESS_FIXES_0630.md). Opraveno v izolovaném zdroji, bez hardwarové certifikace, provozního nasazení či změny observe_only. Historický audit 0.6.29 a N06-02, DB-01 a LIVE blokátory zůstávají zachované.


## 0.6.31 – korekce auditu noci a příprava 02:59

[Kontrakt ceny a preflightu](../priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md):
0.6.30 v RPi absolvovala novou noc 03–05. Uživatelský ceník 1,8078 Kč/kWh je
odlišný od jiného tržního senzoru. Nový zdroj 0.6.31 kontroluje model/fáze
již 02:59, ale ještě není doložená jeho skutečná noc. Žádné live řízení.


## Produkční instalace 0.6.31 – 12. 11. 2026

[Čerstvá Supervisor záloha, podpis zdrojového commitu, HA version/mode,
skutečný post-install ACK 3→4, monitor/storage health a meze důkazu](../priority_shadow/docs/DEPLOYMENT_0631_20261112.md).
PR #42 a Actions #105/#106 PASS, nový runtime `started` výhradně `observe_only`,
nulové povely, nulová ztráta a restarty v aktuálním ověřeném úseku.
Noc následující po nasazení není nahrazena tímto denním testem.
Smluvní cena 1,8078 Kč/kWh byla dle uživatele již ověřena proti smlouvě ČEZ INDI.


## Nezávislý deep audit 0.6.31 — 12. 11. 2026

[Kompletní výsledky a podmínky uzavření](DEEP_AUDIT_0631_20261112.md):
`0.6.31 / started / observe_only`; 607 Python PASS, 9 JS PASS,
1 JS locale-only FAIL na RPi Node bez cs-CZ; reálný immutable backup
ověřen v izolovaném SQL (SHA, integrity, FK). Nové RET-01/HIST-01 (vysoké),
UI-02 (střední), SUP-01/START-02/UI-03 a QA-01. Zůstává NO-GO pro LIVE.
Žádná runtime změna, žádný version bump.

## 12.11.2026 – SQL data volume, duplication, retention design

[Detailed read-only measurements and retention proposal](STORAGE_VOLUME_ANALYSIS_20261112.md).
Consistent portable snapshot of 07:24 contains 43 SQL tables / 502.485 MB;
2026-11-11 stored rows 24.423 MB in 12,743 records; seven completed days
average 29.896 MB/day; rolling 24h 26.908 MB.
New RET-02 (6h full SQLite portable copy, model 2.01GB/day copy writes),
RET-03 (20,154 ACKed outbox chunks still in live SQL),
DATA-05 (duplicate forecast, calibration and session fields),
DATA-06 (1,440/1,440 identical collection_snapshot pairs).
Existing RET-01 and HIST-01 still open. Hot 30d retention is
conditional on immutable all-raw archive, hash/restore, and real
card read-through after Recorder purge. No data deleted, no runtime change.


## 12.11.2026 – Field-by-field audit and 7-day raw policy proposal

[Detailed report](FIELD_RETENTION_DEEP_DIVE_20261112.md);
[filterable policy matrix for 43 SQL tables and 384 observed top-level JSON fields](FIELD_RETENTION_POLICY_MATRIX_20261112.csv).
Private RPi audit classified 2,935 nested/source paths, without publishing actual
HA state values. New user target is 7 days high-res raw; permanent meaningful
night/energy/financial summaries, calibrated model versions, original selected
SOC evidence and material incidents. Source readers with 14–366d lookbacks
must change **before** any purge. RET-04 and DATA-07 stay OPEN.
Measured SOC reference delta 56–72% per SOC BLOB table, RAM 24 input
keys identical at all matched 1,440 pairs and ~1MB/day potential;
naive manual/owner SHA refs rejected (+25–27%).
5–8 MB/day is a target requiring full replay, not a confirmed result.
No source runtime or live HA change.


## Zdroj 0.6.32 – úzká SOC optimalizace bez retenčního limitu

[Implementace a read-only benchmark](../priority_shadow/docs/STORAGE_DEDUP_0632.md).
Velká SOC rozhodnutí používají immutable SHA-256 shared objects;
read path rekonstruuje přesný originální JSON/hash. 783/783 historických
rozhodnutí 8. a 11.11. má stejný packed payload i původní hash.
Plošná 7d retence už není požadována; 7/14/45/366d horizonty a
ostatní analytické čtečky zůstávají beze změny. Žádné úpravy
raw sampling, journal ACK, 6h backupu ani fyzického řízení.

## 13.11.2026 – kompletní noc 0.6.32

[Čerstvý read-only audit](NIGHT_AUDIT_0632_20261113.md): 1 443 prioritních/RAM snímků, 1 444 ACK, 0 loss/action, čerstvý 02:59 preflight PASS. Skutečné EV 15,92 kWh AC, domácí baterie vybití 4,65 kWh DC a SOC 66→20 %, síť 12,55 kWh, cena ČEZ 1,8078 Kč/kWh. OPS-01 je koordinace původního HA a měniče, nikoli aktuační selhání stínového doplňku. Pět fázově neplatných rámců fail-closed. SOC lossless storage pro 134 rozhodnutí 39,61 % méně v této doméně. Bez změny kódu, retence a fyzického řízení.

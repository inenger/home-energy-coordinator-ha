# Registr známých problémů a neověřených podmínek

Platí pro veřejný zdroj 0.6.30. Každý další nález dostane stabilní ID.
OPRAVENO označuje opravený mechanismus s regresí; není zárukou všech
budoucích běhů. OTEVŘENO znamená nevyřešenou příčinu nebo chybějící důkaz.
OMEZENÍ je výslovná hranice návrhu. Podrobné provozní podklady nejsou veřejné.

| ID | Stav | Problém / dopad | Důkaz a další nutný krok |
|---|---|---|---|
| N06-01 | OPRAVENO V KÓDU | Cold záloha zastavila celý primární doplněk; obnova pomocného procesu to neřeší. | [Hot-backup kontrakt](../priority_shadow/docs/HOT_BACKUP_0624.md), [regrese](../priority_shadow/tests/test_native_backup_0624.py). U každého nasazení ověřit skutečný native archiv, stejný runtime a postup commitů během zálohy, obnovu pouze odděleně. |
| N06-02 | OTEVŘENO | Kolektor může nedodat novou sadu před expirací cache. Přesný mechanismus konkrétního zpoždění není prokázaný. | [Audit](NIGHT_AUDIT_20261106.md), [kolektor](../priority_shadow/energy/priority_collection.py). Zachytit začátek i průběh aktuálního requestu, doručení, pořadí a monotónní stáří cache, plánování/CPU/I/O. Ukončit až po reprodukci a regresi přes produkční smyčku. Neprodlužovat TTL a nevymýšlet heartbeat. |
| DB-01 | OTEVŘENO — DIAGNOSTIKA | Lokální writer contention může vyvolat retry analytiky. Samotný kumulativní počet retry neurčuje aktuální zdraví ani příčinu čekání. | [FIFO a retry](../priority_shadow/docs/NIGHT_FIXES_0623.md), [SQLite](../priority_shadow/docs/SQLITE_FIXES_0619.md), [testy](../priority_shadow/tests/test_night_fixes_0623.py). Rozlišit local_writer, SQLITE_BUSY/LOCKED a I/O. Pro konkrétní příčinu doložit držitele a délku čekání bez blokování regulátoru. |
| DB-02 | OPRAVENO V KÓDU | Komprese transportu držela writer gate a blokovala FIFO analytiku. | [Kontrakt 0.6.25](../priority_shadow/docs/JOURNAL_SQLITE_0625.md), [regrese](../priority_shadow/tests/test_monitor_sqlite_0625.py): blokovaná komprese, souběžné kurzory, rollback a idempotentní retry. Neuzavírá neprokázané příčiny DB-01. |
| MON-02 | OPRAVENO V KÓDU | Velké duplicitní recent previews přetekly monitor; failure plán kopíroval celý deník. | [Projekce a úplný stream](../priority_shadow/docs/JOURNAL_SQLITE_0625.md), [Python regrese](../priority_shadow/tests/test_monitor_sqlite_0625.py), [skutečný JS loader](../scripts/test_journal_transport.mjs). Session a transport zůstávají, detaily přes stream, jiné overflow má původní explicitní fallback. |
| DB-03 | OPRAVENO V KÓDU | Opakované no-op DDL při otevření Store a nečinném čtení získávalo writer gate. | [0.6.26](../priority_shadow/docs/BACKUP_IDLE_0626.md), [regrese](../priority_shadow/tests/test_backup_idle_0626.py): existující schéma/idle workery pod obsazeným gate, chybějící index a skutečný write timeout. Neuzavírá všechny příčiny DB-01. |
| BACKUP-02 | OPRAVENO V KÓDU — NUTNÉ NATIVNÍ OVĚŘENÍ | WAL může zmizet mezi enumerací a otevřením taru; platný SQLbundle sám nezaručuje addon v native katalogu. | [Issue31](https://github.com/inenger/home-energy-coordinator-ha/issues/31), [holder a meze](../priority_shadow/docs/BACKUP_IDLE_0626.md), [regrese](../priority_shadow/tests/test_backup_idle_0626.py). Uzavřít až po skutečném Supervisor archivu s metadaty a izolované obnově; zachovat unclean stopped fallback. |
| DEP-01 | OPRAVENO V KÓDU — NUTNÁ MIGRACE | Legacy EV/weather runtime dependency. | [Standalone](../priority_shadow/docs/STANDALONE_0627.md), test_standalone_0627.py; verify local context and future own collection before stopping legacy. |
| DB-04 | OPRAVENO V KÓDU | Large recorder equality held writer scope; short WAL lifecycle caused implicit checkpoint work. | [Contract](../priority_shadow/docs/STANDALONE_0627.md), receipt/gate and WAL regressions. Does not close all historical DB-01. |
| DATA-02 | OPRAVENO V KÓDU | Redundant previews and hourly portable copies generate avoidable writes. | Bounded latest-state cadence, full journal retained, six-hour copies deferred outside window. Verify native publication and recovery. |
| REC-01 | OPRAVENO V KÓDU | A short heartbeat deadline could reap a cold worker before its first readiness IPC. | [Startup contract](../priority_shadow/docs/STANDALONE_0627.md), both bridge regressions; bounded startup, immediate exit detection and unchanged post-ready deadlines. |
| DATA-01 | OMEZENÍ | Výpadek celého procesu/hostitele může ztratit nepotvrzenou RAM frontu; omezená fronta může při dlouhé poruše přetéct. | [Izolace](../priority_shadow/docs/CONTROL_ISOLATION_0620.md), [obnova](../priority_shadow/docs/RECOVERY_FIXES_0622.md). Přiznat loss/unknown, odvolat starou lease, vyžadovat nové sady. Nulový loss counter po restartu sám neprokazuje úplnou RAM historii. |
| BACKUP-01 | OMEZENÍ | Online snímek zachycuje potvrzenou DB v čase manifestu; nezaručuje nulové RPO. Opuštěný snímek může být starší. | [Kontrakt 0.6.24](../priority_shadow/docs/HOT_BACKUP_0624.md). Kontrolovat čas, hash, integritu a cestu obnovy; běžný restart nesmí přepsat živou novější DB. |
| MON-01 | OMEZENÍ | Úplný overflow monitoru není automaticky v recorderu/kartě. Soukromý archiv má omezenou kapacitu a I/O může selhat. | [Overflow](../priority_shadow/docs/NIGHT_FIXES_0623.md), [testy](../priority_shadow/tests/test_night_fixes_0623.py). Respektovat retained=false a full_payload_in_recorder=false, nevyhlazovat ztracený historický detail. |
| LIVE-01 | OTEVŘENO — BLOKUJE FYZICKÉ ŘÍZENÍ | Fyzický akční adaptér, mapování Mode8 a expirace povelu na zařízení nejsou tímto projektem potvrzené. | [RAM kontrakt](../priority_shadow/docs/RAM_CONTROL_068.md), [architektura](../priority_shadow/docs/CONTROL_ISOLATION_0620.md). Zůstat observe_only. Požadovat ověřené mapování, readback, watchdog/timeout a bezpečný návrat; nepovažovat syntetiku za hardware test. |
| LIVE-02 | OTEVŘENO — VALIDACE | Modelová účinnost, kapacita, fázové meze, reakce na špičky a souběh EV/baterie nejsou automaticky fyzicky ověřené. | [Data](../priority_shadow/docs/DATA.md), [algoritmus](../priority_shadow/docs/ALGORITHM.md), [fáze](../priority_shadow/docs/MAX_FILL_065.md). Doložit měřicí hranice AC/DC, nezávislou validaci a reálný souběh; noc bez EV není zkouškou EV startu. |
| VAL-01 | OTEVŘENO — PROVOZNÍ OVĚŘENÍ | Každá nová verze potřebuje vlastní skutečné pozorovací období; předchozí noc nebo urychlená syntetika ho nenahrazuje. | [Mapa testů](TEST_MATRIX.md), [runbook](RELEASE_RUNBOOK.md). Doložit verzi, časový rozsah, pokrytí, chybějící úseky, původ vstupů a meze závěru. |
| EV-01 | OPRAVENO V KÓDU | Cloud cable/current inputs could override wallbox planning connection/limit. | [0.6.28 contract](../priority_shadow/docs/WALLBOX_WRITES_0628.md), test_wallbox_0628.py; real fast loop, wallbox lifecycle and planner source regressions. |
| PLN-01 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Asynchronous EV startup can be learned as a house-load step. | [Issue36](https://github.com/inenger/home-energy-coordinator-ha/issues/36), [settlement contract](../priority_shadow/docs/WALLBOX_WRITES_0628.md); from_db/full planner and real house-step regressions. Unknown transition pulses remain explicit, no physical safety claim. |
| DB-05 | OPRAVENO V KÓDU | Payload preparation and per-publication commits hold/contend for writer admission. | [0.6.28](../priority_shadow/docs/WALLBOX_WRITES_0628.md), chunk-preparation, bounded commit group, durable pre-send intent and fairness regressions. Does not close all historical DB-01. |
| DB-06 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Background analytics used fast bounded admission; remaining schema calls acquired no-op writer scopes. | [0.6.29 contract](../priority_shadow/docs/ANALYTICS_ADMISSION_0629.md), test_analytics_admission_0629.py; cancellable FIFO, continuation, real SQL errors and schema repair. Does not close historical DB-01. |
| N06-03 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Pomalé REST obnovení přesunuto do asynchronního single-flight workeru; živý template snímek nečeká. Cache race se nefalšuje. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| N06-04 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Sledování thread liveness/progress, bounded 3 obnovy mrtvého vlákna/300 s; zaseknuté živé vlákno pouze fail-closed, bez neomezeného spawn. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| REC-02 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Stáří durable ACK odděleno od heartbeat, omezené zotavení při WriterTimeout a trvalá diagnostika. Plný disk vyžaduje zásah. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| DATA-03 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Durable SHA-256 receipt původního obsahu celé dávky; konfliktní a neověřitelné historické opakování se odmítne. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| DATA-04 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Konfliktní SOC hash/timestamp explicitně odmítnut, neplatná kolize revokuje dřívější platný návrh bez přepsání SQL. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| LIVE-03 | OMEZENÍ — BLOKUJE PŘÍMÉ POUŽITÍ MONITORŮ | Ideal monitor power and retained HA state are not an expiring actuation intent. | [Audit, reprodukce a podmínka uzavření](READINESS_AUDIT_0629.md). |
| MON-03 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Rozlišeny allowlisted reason_code pro známé poruchy sběru bez zveřejnění libovolné chybové zprávy. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| UI-01 | OPRAVENO V KÓDU — NUTNÉ PROVOZNÍ OVĚŘENÍ | Neplatný sunrise se zobrazí pomlčkou a neukončí celou kartu; ověřeno card.render v Node VM. | [0.6.30](../priority_shadow/docs/READINESS_FIXES_0630.md), [akceptační testy](../priority_shadow/tests/test_readiness_audit_0629.py); stará reprodukce zůstává v [auditu](READINESS_AUDIT_0629.md). |
| DOC-01 | OPRAVENO V DOKUMENTACI | Stale current-source pointers and disconnected finding-table rows. | [Audit, reprodukce a podmínka uzavření](READINESS_AUDIT_0629.md). |


## Jak posuzovat analytiku

Zdravá prázdná fronta po doloženém retry není totéž jako trvající degraded,
rostoucí backlog nebo I/O porucha. Kumulativní counter a last_failure se
po zotavení nemažou. Kontrola uzávěrky musí současně číst aktuální status,
počet čekajících úloh, postup durable ACK, loss a restartový stav.
Nesmí „opravovat“ výsledek resetem counteru. Tento rozdíl neomlouvá
neprokázanou příčinu opakovaného čekání DB-01.

## Podmínky uzavření nového nálezu

1. Původní symptom a zdrojová verze zůstaly zachované.
2. Reprodukce skutečně zachytí vadu; baseline s novým kontraktem selže.
3. Oprava projde relevantní produkční cestou, ne jen pomocnou funkcí.
4. Existuje test opačného bezpečnostního případu, aby oprava nepovolila
   staré vstupy, cizího vlastníka, přepsání historie nebo fyzické zásahy.
5. Výsledek CI a provozní ověření mají vlastní rozsah a zbývající nejistoty.
6. Stav registru je změněný s důvodem a odkazem; původní záznam se nemaže.

# Registr známých problémů a neověřených podmínek

Platí pro veřejný zdroj 0.6.24. Každý další nález dostane stabilní ID.
OPRAVENO označuje opravený mechanismus s regresí; není zárukou všech
budoucích běhů. OTEVŘENO znamená nevyřešenou příčinu nebo chybějící důkaz.
OMEZENÍ je výslovná hranice návrhu. Podrobné provozní podklady nejsou veřejné.

| ID | Stav | Problém / dopad | Důkaz a další nutný krok |
|---|---|---|---|
| N06-01 | OPRAVENO V KÓDU | Cold záloha zastavila celý primární doplněk; obnova pomocného procesu to neřeší. | [Hot-backup kontrakt](../priority_shadow/docs/HOT_BACKUP_0624.md), [regrese](../priority_shadow/tests/test_native_backup_0624.py). U každého nasazení ověřit skutečný native archiv, stejný runtime a postup commitů během zálohy, obnovu pouze odděleně. |
| N06-02 | OTEVŘENO | Kolektor může nedodat novou sadu před expirací cache. Přesný mechanismus konkrétního zpoždění není prokázaný. | [Audit](NIGHT_AUDIT_20261106.md), [kolektor](../priority_shadow/energy/priority_collection.py). Zachytit začátek i průběh aktuálního requestu, doručení, pořadí a monotónní stáří cache, plánování/CPU/I/O. Ukončit až po reprodukci a regresi přes produkční smyčku. Neprodlužovat TTL a nevymýšlet heartbeat. |
| DB-01 | OTEVŘENO — DIAGNOSTIKA | Lokální writer contention může vyvolat retry analytiky. Samotný kumulativní počet retry neurčuje aktuální zdraví ani příčinu čekání. | [FIFO a retry](../priority_shadow/docs/NIGHT_FIXES_0623.md), [SQLite](../priority_shadow/docs/SQLITE_FIXES_0619.md), [testy](../priority_shadow/tests/test_night_fixes_0623.py). Rozlišit local_writer, SQLITE_BUSY/LOCKED a I/O. Pro konkrétní příčinu doložit držitele a délku čekání bez blokování regulátoru. |
| DATA-01 | OMEZENÍ | Výpadek celého procesu/hostitele může ztratit nepotvrzenou RAM frontu; omezená fronta může při dlouhé poruše přetéct. | [Izolace](../priority_shadow/docs/CONTROL_ISOLATION_0620.md), [obnova](../priority_shadow/docs/RECOVERY_FIXES_0622.md). Přiznat loss/unknown, odvolat starou lease, vyžadovat nové sady. Nulový loss counter po restartu sám neprokazuje úplnou RAM historii. |
| BACKUP-01 | OMEZENÍ | Online snímek zachycuje potvrzenou DB v čase manifestu; nezaručuje nulové RPO. Opuštěný snímek může být starší. | [Kontrakt 0.6.24](../priority_shadow/docs/HOT_BACKUP_0624.md). Kontrolovat čas, hash, integritu a cestu obnovy; běžný restart nesmí přepsat živou novější DB. |
| MON-01 | OMEZENÍ | Úplný overflow monitoru není automaticky v recorderu/kartě. Soukromý archiv má omezenou kapacitu a I/O může selhat. | [Overflow](../priority_shadow/docs/NIGHT_FIXES_0623.md), [testy](../priority_shadow/tests/test_night_fixes_0623.py). Respektovat retained=false a full_payload_in_recorder=false, nevyhlazovat ztracený historický detail. |
| LIVE-01 | OTEVŘENO — BLOKUJE FYZICKÉ ŘÍZENÍ | Fyzický akční adaptér, mapování Mode8 a expirace povelu na zařízení nejsou tímto projektem potvrzené. | [RAM kontrakt](../priority_shadow/docs/RAM_CONTROL_068.md), [architektura](../priority_shadow/docs/CONTROL_ISOLATION_0620.md). Zůstat observe_only. Požadovat ověřené mapování, readback, watchdog/timeout a bezpečný návrat; nepovažovat syntetiku za hardware test. |
| LIVE-02 | OTEVŘENO — VALIDACE | Modelová účinnost, kapacita, fázové meze, reakce na špičky a souběh EV/baterie nejsou automaticky fyzicky ověřené. | [Data](../priority_shadow/docs/DATA.md), [algoritmus](../priority_shadow/docs/ALGORITHM.md), [fáze](../priority_shadow/docs/MAX_FILL_065.md). Doložit měřicí hranice AC/DC, nezávislou validaci a reálný souběh; noc bez EV není zkouškou EV startu. |
| VAL-01 | OTEVŘENO — PROVOZNÍ OVĚŘENÍ | Každá nová verze potřebuje vlastní skutečné pozorovací období; předchozí noc nebo urychlená syntetika ho nenahrazuje. | [Mapa testů](TEST_MATRIX.md), [runbook](RELEASE_RUNBOOK.md). Doložit verzi, časový rozsah, pokrytí, chybějící úseky, původ vstupů a meze závěru. |

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

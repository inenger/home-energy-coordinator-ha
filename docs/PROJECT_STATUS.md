# Aktuální stav a rozcestník projektu

<!-- shadow-version: 0.6.24 -->

Stav veřejného zdroje k 6. 11. 2026. Historické poznámky v MEMORY a starších
auditech popisují tehdejší stav; pro současné otevřené položky použijte tento
rozcestník a [registr nálezů](KNOWN_ISSUES.md).

| Oblast | Autoritativní zdroj |
|---|---|
| Stínový doplněk 0.6.24, pouze observe_only | [config](../priority_shadow/config.yaml), [runtime](../priority_shadow/energy/core.py), [metadata](../priority_shadow/pyproject.toml) |
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

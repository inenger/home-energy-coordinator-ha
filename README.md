**Nová verze zdroje 0.6.36 (DB-OPT-01):** [bezztrátové přebalení databáze pouze stínového doplňku](docs/DB_OPT_0636_20261117.md). Na izolované přenosné kopii ověřena úspora 19,83 MB bez změny kterýchkoliv 289 566 záznamů. Provozní migrace aktuální live DB je samostatný, výslovně vyžadovaný restart addonu. Hlavní databáze HA a fyzické řízení nedotčeny.

---

**Nasazení 0.6.35 (17.11.2026):** RPi Supervisor started/observe_only. Nová WIN-01 politika publikuje výsledky, HEC LIVE odpojeno. [Provozní evidence](docs/DEPLOYMENT_0635_20261117.md).

**Vývojové vydání 0.6.35:** [WIN-01: vysoký energetický deficit bez mrazové podmínky](docs/WIN01_ENERGY_ADEQUACY_0635.md). Zdrojová verze, CI a instalace v Home Assistantu jsou samostatně ověřované kroky. Historická instalace 0.6.34 je uvedena níže a nesmí být zaměňována za aktuální zdroj. `observe_only` a HEC LIVE odpojené zůstávají závazné.

---

**Nasazení:** 0.6.34 je od 15.11.2026 instalována na RPi v režimu `started / observe_only`; fyzické HEC LIVE zůstává odpojené. [Provozní ověření a limity](docs/DEPLOYMENT_0634_20261115.md).

## Aktuální stav – 15. 11. 2026

**Verze 0.6.34:** [WIN-01 + RET-05](docs/WIN_RET_RELEASE_0634.md) sjednocuje poradní zimní SOC potřebu s ekonomickým modelem a doplňuje ověřené uzavírání nočních souhrnů. Stínový doplněk i nadále používá `observe_only` a nevydává fyzické povely. HEC LIVE zůstává odpojený od HA a nesmí se samočinně aktivovat.

[Zimní požadavky](docs/WINTER_OPERATION_POLICY_20261115.md) · [Otevřené provozní hranice](docs/KNOWN_ISSUES.md) · [Regrese](docs/TEST_MATRIX.md). Starší verze uvedené níže jsou historické záznamy, nikoli aktuální nastavení zařízení.

---

# Home Energy Coordinator · Home Assistant

| Doplněk | Adresář | Verze |
|---|---|---|
| Původní energetický koordinátor | [`energy_coordinator`](energy_coordinator/) | 0.5.4 |
| Samostatné noční stínové priority a SOC | [`priority_shadow`](priority_shadow/) | 0.6.36 |
| **Skutečné řízení baterie a Tesly 03–05** | [HA package](ha_packages/night_live_coordinator.yaml) | LIVE v1 · 13.11.2026 |

Oba balíčky mají vlastní Docker build context. Nový stínový doplněk nemění
verzi ani provoz původního koordinátoru. Veřejné balíčky neobsahují soukromou
naměřenou historii, seed baterie ani přístupové údaje.

Před pokračováním ve vývoji číst [`MEMORY.md`](MEMORY.md) a [`AGENTS.md`](AGENTS.md).
Paměť obsahuje aktuální stav, důvody rozhodnutí, poučení z auditů, regresní
případy a dosud neověřené předpoklady. Další podrobnosti jsou v README
jednotlivých doplňků. Provoz a soukromé analýzy patří na RPi.

**Aktuální stav 13.11. v 09:10:** Ostrý HEC LIVE je odpojen od HA a deaktivován. Noc 13.–14.11. je pouze pozorovací; další reaktivace vyžaduje výslovné rozhodnutí. [Doklad o bezpečném pozastavení](docs/LIVE_BATTERY_RESERVE_20261113.md).

- [0.6.33 datová optimalizace: zpětná kompakce, diferencovaná retence, zachování historie](docs/DB_OPTIMIZATION_RELEASE_0633.md).

## Dokumentace

- [Ostré řízení: instalace, fázové limity, návrat po 05:00 a fyzické testy](docs/LIVE_BATTERY_RESERVE_20261113.md).

- [Audit noci 13.11: skutečná energie EV/baterie, cena, fáze, preflight a SOC úspora 0.6.32](docs/NIGHT_AUDIT_0632_20261113.md).

- [Korekce ceny ČEZ INDI, audit 12.11, preflight 02:59](priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md).
- [Ověřené nasazení 0.6.31 na RPi, záloha a nové ACK](priority_shadow/docs/DEPLOYMENT_0631_20261112.md).
- [Hloubkový audit 0.6.31: důkazy, rizika, priority](docs/DEEP_AUDIT_0631_20261112.md).
- [Denní objem SQL, redundantní data a návrh retence](docs/STORAGE_VOLUME_ANALYSIS_20261112.md).
- [Audit 2 935 polí: co logovat, 7denní retence, trvalé výsledky a naměřené simulace](docs/FIELD_RETENTION_DEEP_DIVE_20261112.md).
- [Filtrovací matice 407 položek / 43 tabulek – návrhové zásady pro každé pole](docs/FIELD_RETENTION_POLICY_MATRIX_20261112.csv).

**Začněte [aktuálním stavem a rozcestníkem](docs/PROJECT_STATUS.md).**
[Otevřené chyby](docs/KNOWN_ISSUES.md) · [Mapa regresí](docs/TEST_MATRIX.md) · [Postup vydání a obnovy](docs/RELEASE_RUNBOOK.md).

Starší audity a zápisy v MEMORY jsou historie k danému vydání; jejich tehdejší stav nepřebírat jako dnešní měření.

- [Přehled a architektura](priority_shadow/docs/ARCHITECTURE.md): oba doplňky, tok dat, hranice režimu pouze pozorování.
- [Rozhodovací algoritmus](priority_shadow/docs/ALGORITHM.md): SOC, počasí, sezóna, čas výroby, ceny, EV a volba cíle.
- [Provoz a obnova](priority_shadow/docs/OPERATIONS.md): konfigurace, diagnostika, zálohy, aktualizace a migrace.
- [Datový a AI kontrakt](priority_shadow/docs/DATA.md): evidence, původ dat, měřicí hranice, kalibrace a verifikace.
- [Automatizace 03–05](priority_shadow/docs/AUTOMATIONS.md): současné vazby a návrh budoucí koordinace.
- [Vývoj a vydání](priority_shadow/docs/DEVELOPMENT.md): kontroly, GitHub, paměť a otevřené úkoly.
- [Historie oprav](priority_shadow/docs/FIX_HISTORY.md) a [rozsah validace](priority_shadow/docs/VALIDATION.md).

Hlavní integrační větev je `main`. [PR #4](https://github.com/inenger/home-energy-coordinator-ha/pull/4)
obsahuje zveřejnění kompletního balíčku 0.6.3 a dokumentace. Sloučení kódu,
HA aktualizace a migrace existující lokální instalace jsou různé kroky;
podrobnosti a poslední ověřený stav jsou v [MEMORY.md](MEMORY.md).

## Vývoj včetně chyb a slepých cest

[Úplná dohledatelná historie](docs/history/DEVELOPMENT_HISTORY.md) uvádí odmítnuté varianty, chybné závěry, návaznosti auditů a oprav i manifest původních důkazů.

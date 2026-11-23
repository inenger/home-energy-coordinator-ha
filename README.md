# Home Energy Coordinator · Home Assistant

**Platný GitHub zdroj:** `priority_shadow 0.6.39` (23.11.2026),
bezpečnostní fail-closed oprava PEAK-03; fyzické zásahy = 0.
**Běžící Raspberry Pi:** poslední ověřený doplněk `0.6.38` v
`observe_only`; GitHub commit sám nemění instalaci.
Hlavní vstup pro AI a vývoj: [aktuální stav](docs/PROJECT_STATUS.md),
[pravidla](AGENTS.md), [známé limity](docs/KNOWN_ISSUES.md).

| Doplněk | Adresář | Verze |
|---|---|---|
| Původní energetický koordinátor | [`energy_coordinator`](energy_coordinator/) | 0.5.4 |
| Samostatné noční stínové priority a SOC | [`priority_shadow`](priority_shadow/) | 0.6.39 |
| Historický LIVE v1 (neaktivní, neinstalovat) | [Archiv](docs/history/retired_live_v1_20261113.yaml.txt) | 13.11.2026 · RETIRED |

Oba balíčky mají vlastní Docker build context. Nový stínový doplněk nemění
verzi ani provoz původního koordinátoru. Veřejné balíčky neobsahují soukromou
naměřenou historii, seed baterie ani přístupové údaje.

Před pokračováním ve vývoji číst [`MEMORY.md`](MEMORY.md) a [`AGENTS.md`](AGENTS.md).
Paměť obsahuje aktuální stav, důvody rozhodnutí, poučení z auditů, regresní
případy a dosud neověřené předpoklady. Další podrobnosti jsou v README
jednotlivých doplňků. Provoz a soukromé analýzy patří na RPi.

**Nasazení:** Na Raspberry Pi stále běží `0.6.38 / started / observe_only`.
Zdrojová `0.6.39` je bezpečnostní oprava virtuálního regulátoru v GitHubu;
**není tím automaticky nainstalována do HA**. Modbus FAST 1s / MEDIUM+DEFAULT 5s
a hlavní jistič **3×25 A** zůstávají beze změny.
Fyzické HEC LIVE je deaktivováno; archivní konfigurace není určená k nasazení.
Po první noci 22.–23.11. je ověřeno 1 440 kontrolních cyklů a bezpečný stop
při jednom překročení čerstvosti proudů:
[audit noci](docs/NIGHT_AUDIT_0638_20261123.md).

**Nejbližší akce:** cílený deploy/test 0.6.39 až na samostatný pokyn,
nikoliv automaticky. Ostré řízení nadále NO-GO; podmínky [LIVE-01/02](docs/KNOWN_ISSUES.md).
Historické verze a pokusy: [changelog](priority_shadow/CHANGELOG.md),
[vývojové dějiny](docs/history/DEVELOPMENT_HISTORY.md).

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

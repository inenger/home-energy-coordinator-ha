# Home Energy Coordinator · Home Assistant

| Doplněk | Adresář | Verze |
|---|---|---|
| Původní energetický koordinátor | [`energy_coordinator`](energy_coordinator/) | 0.5.4 |
| Samostatné noční stínové priority a SOC | [`priority_shadow`](priority_shadow/) | 0.6.15 |

Oba balíčky mají vlastní Docker build context. Nový stínový doplněk nemění
verzi ani provoz původního koordinátoru. Veřejné balíčky neobsahují soukromou
naměřenou historii, seed baterie ani přístupové údaje.

Před pokračováním ve vývoji číst [`MEMORY.md`](MEMORY.md) a [`AGENTS.md`](AGENTS.md).
Paměť obsahuje aktuální stav, důvody rozhodnutí, poučení z auditů, regresní
případy a dosud neověřené předpoklady. Další podrobnosti jsou v README
jednotlivých doplňků. Provoz a soukromé analýzy patří na RPi.

## Dokumentace

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

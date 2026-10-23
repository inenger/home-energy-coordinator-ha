# Home Energy Coordinator · Home Assistant

| Doplněk | Adresář | Verze |
|---|---|---|
| Původní energetický koordinátor | [`energy_coordinator`](energy_coordinator/) | 0.5.3 |
| Samostatné noční stínové priority a SOC | [`priority_shadow`](priority_shadow/) | 0.6.2 |

Oba balíčky mají vlastní Docker build context. Nový stínový doplněk nemění
verzi ani provoz původního koordinátoru. Veřejné balíčky neobsahují soukromou
naměřenou historii, seed baterie ani přístupové údaje.

Před pokračováním ve vývoji číst [`MEMORY.md`](MEMORY.md) a [`AGENTS.md`](AGENTS.md).
Paměť obsahuje aktuální stav, důvody rozhodnutí, poučení z auditů, regresní
případy a dosud neověřené předpoklady. Další podrobnosti jsou v README
jednotlivých doplňků. Provoz a soukromé analýzy patří na RPi.

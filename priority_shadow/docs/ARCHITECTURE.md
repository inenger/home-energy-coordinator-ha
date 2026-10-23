# Architektura 0.6.2

Stav popisu: 23. 10. 2026. Hlavní cíl je účelné levné nabití mezi 03:00
a 05:00 s prostorem pro pozdější FVE. Dům může v zimě spotřebovat více než
celá baterie; celodenní soběstačnost není podmínka ani slib algoritmu.

## Dva samostatné doplňky

| Část | Úloha | Poslední ověřený provoz na RPi |
|---|---|---|
| `energy_coordinator/` 0.5.3 | Původní sběr, statistiky a kontext | `6696af1a_energy_coordinator` |
| `priority_shadow/` 0.6.2 | Návrhy SOC, priority EV/baterie a jejich evidence | `local_energy_priority_shadow` |

Každý adresář má vlastní Dockerfile, zdroje, konfiguraci a testy. Shadow
startuje přímo `python3 -m energy.priority_observer`; nepoužívá bootstrap
ani historický interní runtime updater obsažený ve společných modulech.
Veřejná větev má samostatné zdroje; staré integrační pracovní větve je měly
sdílené v původním adresáři. Při vývoji rozhoduje konkrétní build context.

## Tok zpracování

1. `collector.ReadOnlyHA` čte požadované HA entity; předpovědi archivuje
   `priority_observer.archive_forecasts` s časem skutečného zachycení.
2. `soc_runtime` ukládá minutová pozorování, obnovuje kalibrační kontext
   z privátního seedu a vytváří rozhodnutí pomocí čistého `soc_planner`.
3. `priority` připojí platný návrh k noční relaci a porovnává obě priority.
   `power_allocation` sdílí rozpočet EV a baterie; `soc_energy` drží bilanci.
4. `priority_audit` zapisuje modelové povely a pozorované denní výsledky;
   `soc_runtime.review` vytváří denní vyhodnocení na společných intervalech.
5. `publish_status.publish_priority` zveřejní vyjmenované monitorovací
   senzory. Karta z nich čte přehled; plná evidence zůstává v SQLite na RPi.

Sběr běží přibližně každých 15 sekund v nočním okně, jinak po 60 sekundách.
Pozorování SOC se deduplikují na minuty. Platný plán se přepočítává po
10 minutách, neplatný po minutě; změna dne, preference a zachycení pět minut
před oknem vyvolají okamžitý přepočet. Modely se obnovují po šesti hodinách.
Tyto intervaly jsou nyní v kódu, nikoli volby `interval_seconds` starého příkladu.

## Co smí zapisovat

Runtime zapisuje vlastní soubory, vlastní evidence a monitorovací stavy HA.
Není to účet s technicky omezenými read-only právy: Supervisor credential má
širší oprávnění. Omezení je v implementaci a přesném seznamu publisheru.
Akční adaptér chybí, `device_actions=0`, `live_ready=false`.

Karta může změnit pouze `input_select.nocni_stinova_priorita` mezi
`Elektromobil` a `Baterie SolaX`. Jde o preferenci pro stínové porovnání.
Nemění měnič, EV proud, skutečné cílové nabití ani provozní automatizace.

## Závislosti a hranice

Požadované entity jsou v `night.IDS`, `priority.EXTRA`, `soc_runtime.IDS`
a `automation_context.ENTITY_IDS`; obecný `config/entities.json` sám není
úplný seznam vstupů nočního runtime. Model potřebuje místní
`/share/home-energy-priority-shadow/soc-history.json.gz`. Pro další kontext
čte původní portable DB `/share/home-energy-coordinator/evidence.sqlite`
přes SQLite `mode=ro` a vlastní archiv počasí.

Přítomnost údajů v HA nezaručuje fyzickou čerstvost zařízení. Není potvrzené
mapování fází, řízení ohřevu během budoucích zásahů ani kompletní společná
ekonomická validace auta a baterie v reálném provozu. Podrobnosti:
[algoritmus](ALGORITHM.md), [data](DATA.md), [validace](VALIDATION.md).

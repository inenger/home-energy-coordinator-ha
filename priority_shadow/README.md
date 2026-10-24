# Noční nabíjení · stínové priority 0.6.4

Samostatný Home Assistant doplněk pro Raspberry Pi. Počítá návrhy SOC baterie
a porovnává priority EV/baterie v okně 03:00–05:00 Europe/Prague. Používá
známý nákupní tarif, hodinovou FVE, profil domu bez EV a mapu energie/SOC.
Režim je výhradně `observe_only`; akční adaptér neexistuje.

Tento adresář je kompletní Docker build context: `energy/`, `config/` a `tests/`
jsou přímo uvnitř něj. Původní `energy_coordinator/` zůstává na 0.5.3.
Autoritativní kód nového doplňku je zde; při dalších úpravách nekopírovat
novější kód automaticky do původního koordinátoru.

## Evidence a uvedení do provozu

Doplněk používá vlastní `/data/evidence/evidence.sqlite`; konzistentní kopii
a privátní seed drží na RPi pod `/share/home-energy-priority-shadow`.
Seed ani naměřená historie nejsou distribuovány v tomto veřejném repozitáři.
Bez importovaného lokálního seedu se návrh zablokuje s
`SOC_HISTORY_NOT_IMPORTED`; seed se nesmí nahrazovat vymyšlenou kapacitou.

Instalace z repozitáře má jiný Supervisor slug a vlastní `/data` než stávající
lokální doplněk. Nespouštět je současně proti stejným monitorovacím entitám.
Přechod vyžaduje zálohu, kontrolovaný přenos evidence, vypnutí původního
pozorovacího procesu a ověření zachování historie. Samotný GitHub PR nic
z toho neprovádí.

Dashboard je v `dashboard/night-priority-card.js`; pomocník je pouze stínová
preference. Před změnou dashboardu načíst aktuální konfiguraci, zálohovat ji
a ověřit ostatní záložky a zdroje. Původní provozní automatizace se nemění.

## Ověření

```sh
cd priority_shadow
python3 -m unittest discover -s tests -q
node --check dashboard/night-priority-card.js
```

Testy používají syntetická data. Soukromá ověření na skutečné historii běží
pouze na RPi. Výsledek modelu není naměřená úspora ani jističová ochrana.
Před další prací číst [`../MEMORY.md`](../MEMORY.md),
[`docs/FIX_HISTORY.md`](docs/FIX_HISTORY.md) a [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Podrobná příručka

[Architektura](docs/ARCHITECTURE.md) · [Algoritmus](docs/ALGORITHM.md) ·
[Provoz a obnova](docs/OPERATIONS.md) · [Data a AI](docs/DATA.md) ·
[Automatizace 03–05](docs/AUTOMATIONS.md) · [Vývoj a vydání](docs/DEVELOPMENT.md).

Dokumentace odpovídá runtime 0.6.4. `config/settings.example.json` obsahuje
historické nastavení společných modulů; aktivní nastavení tohoto doplňku
určují výhradně volby v `config.yaml` načítané z `/data/options.json`.

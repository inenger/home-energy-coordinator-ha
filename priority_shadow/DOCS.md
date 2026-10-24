# Noční nabíjení · stínové priority

Verze 0.6.4 počítá návrh nabití SolaX pro levné okno 03:00–05:00,
porovnává preference EV/baterie a uchovává důkazy na Raspberry Pi.
Používá časový profil FVE, spotřebu domu, SOC, sezónu a již vypočtený tarif.
Fyzické řízení zařízení ani změny provozních automatizací nejsou aktivní.

## Než doplněk poprvé spustíte

Je určen pro konkrétní mapování entit tohoto projektu. Potřebuje privátní
auditovaný seed `/share/home-energy-priority-shadow/soc-history.json.gz`.
Seed a naměřená historie nejsou součástí instalace z GitHubu.

Pokud již běží `local_energy_priority_shadow`, novou repozitářovou instalaci
nespouštějte souběžně. Má vlastní `/data` a nepřebírá historii automaticky.
Nejdříve proveďte zálohu a kontrolovaný přenos podle provozní příručky.
Původní doplněk `energy_coordinator` 0.5.3 zůstává samostatný.

## Volby

- `mode: observe_only` je jediný režim.
- `planner_enabled` zapíná výpočet návrhu, nikoli nabíjení.
- `planner_approved_reserve_soc` je výslovná modelová rezerva; prázdná
  hodnota ponechá referenčních 15 %, nikoli schválenou provozní rezervu.
- `planner_inverter_ac_limit_kw` přijímá potvrzený limit v kW jako řetězec;
  prázdná hodnota zůstává neověřená.
- `storage_limit_mb` je rozpočet evidence; při překročení se sběr zastaví
  s chybou a nic se automaticky nemaže.

Po startu kontrolujte čerstvé sběry v logu a stav
`sensor.nocni_stinovy_soc_optimalizace`. Úspěšný sběr sám neznamená platný
SOC návrh. Helper `input_select.nocni_stinova_priorita` vybírá pouze
stínovou preferenci. Karta a helper se instalují zvlášť.

## Úplná dokumentace

- [Architektura](https://github.com/inenger/home-energy-coordinator-ha/blob/main/priority_shadow/docs/ARCHITECTURE.md)
- [Algoritmus a cílové SOC](https://github.com/inenger/home-energy-coordinator-ha/blob/main/priority_shadow/docs/ALGORITHM.md)
- [Provoz, zálohy a migrace](https://github.com/inenger/home-energy-coordinator-ha/blob/main/priority_shadow/docs/OPERATIONS.md)
- [Data, kalibrace a AI verifikace](https://github.com/inenger/home-energy-coordinator-ha/blob/main/priority_shadow/docs/DATA.md)
- [Automatizace mezi 03–05](https://github.com/inenger/home-energy-coordinator-ha/blob/main/priority_shadow/docs/AUTOMATIONS.md)
- [Projektová paměť](https://github.com/inenger/home-energy-coordinator-ha/blob/main/MEMORY.md)

Modelové výsledky nejsou naměřené úspory. Plán se bez samostatné
implementace a ověření fyzicky neprovádí.

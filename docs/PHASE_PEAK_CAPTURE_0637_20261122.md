# PEAK-01 / MODBUS-01 — stínové zachytávání krátkých proudových špiček

**22. 11. 2026 · zdrojová verze 0.6.37.** Platí pouze pro samostatný pozorovací doplněk `priority_shadow`, nikoli jako ochranné zařízení nebo potvrzení HEC LIVE.

## Zadání a fyzikální hranice

- Uživatel výslovně potvrdil **25 A pro každou AC fázi hlavního jističe**, nikoli 30 A. Tuto hodnotu neměnit; původní nastavení a BMS limit **30 A DC na bateriovém portu** není AC limit jističe a je jiná veličina.
- V předchozím read-only nočním auditu dokázala 1s HA historie zaznamenat krátké proudové špičky, které nebyly ve 5s `ram_control.statistics.measured_phase_max_a`. Přímou reálnou řadu s časy, skutečnými soukromými stavy či privátní SQLite nepřidávat do veřejného Gitu.
- Existující sběrný worker `SnapshotCollector` volá `ReadOnlyHA.priority_states()` každou 1 s v nočním okně, zatímco `MemoryControl.step()` vyhodnocuje řídicí RAM každých 5 s. Původně poslední kompletní cache přepisovala předchozí 1s hodnoty.

## Oprava

1. Nový malý RAM-only `PhasePeakWindow` je plněn **každým úspěšným 1s sběrem**; zpracovává výhradně přímé tři Modbus entity `sensor.solax_inverter_solax_grid_current_l1/l2/l3` s jednotkou A, konečným číslem, monotónním `last_reported` a věkem nejvýše 3,5 s. Neslouží jako umělý heartbeat. Opakovaný report timestamp není nový vzorek.
2. Uchovává nejvýše 8 s monotónně aktuálních výsledků (navíc omezení 32 rámců) v paměti. Při chybě sběru vše resetuje; nemůže prezentovat poslední dříve platné maximum jako čerstvé. Zahrnuje maximum na každé fázi, čas reportu, počet unikátních reportů, status kvality a informaci o případném překročení 25 A.
3. `SnapshotCollector.priority_states()` atomicky s přesným snímkem připojí `collection_phase_peaks`. `MemoryControl.step()` ho propaguje do `ram_control.observe`. Ve stínovém vzorku `phase_peak_window` obsahuje přesný zdroj a high-water; `measured_phase_max_a` nyní bere maximum i z 1s zpráv. `collector_peak_exceedance_intervals` a `collector_peak_unverified_intervals` jsou samostatné diagnostiky pro 5s intervaly, nikoliv počet jednotlivých fyzických špiček. Překryv osmivteřinových oken je konzervativní.
4. Při potvrzeném maximu **nad 25 A** nebo neověřeném období smyčka *jen virtuálně* zablokuje další požadavek (fail closed) a zapíše důvod `observed_phase_current_above_25a` či `fast_phase_peak_window_unverified`. Nevysílá žádný SolaX/EV povel, nemění nastavení, retenci ani původní HA Recorder.
5. Fyzická měření běží odděleně od pětisekundového výpočtu. I toto řešení může minout kratší špičky než fyzické obnovení registru nebo vzorkování HA. **Není to ochrana jističe a neuděluje souhlas s ostrým provozem.**

## MODBUS-01 — diagnostické vyhodnocení

SolaX Modbus 2026.11.04 má aktuálně `scan_interval_fast = 1`, `medium = 5`, `default = 5`. Jeho `overrun_count` se zvyšuje, pokud *délka úspěšného cyklu* ≥ nastavený interval. Je to kumulativní indikátor trvání, nikoli samostatný důkaz timeoutů nebo ztracených registrů. V aktuálním read-only auditu `communication_health=Healthy`, klouzavá `success_rate=100 %`, `quarantined_registers=0`, průměrná doba cyklu řádově 0,6–0,75 s a občasná délka přes 1,5 s.

**Rozhodnutí nyní:** interval **1 s ponechat**, protože byl uživatelem výslovně schválen a čerstvost potřebujeme k zachytávání špiček. **Žádný skrytý auto-switch na 2 s.** Další samostatný provozní krok: monitorovat rozdíl overrun counteru per-časové okno, timeouty, actual freshness a CPU; při reálném přetížení otestovat 2 s ve stejných podmínkách, případně optimalizovat FAST registry nebo použít pasivní HA websocket stream. Odezva wallboxu a SolaXu není hard real time. Změny Modbus integrace jsou mimo rozsah tohoto releasu.

## Přijetí a omezení

- [Syntetická E2E regrese](../priority_shadow/tests/test_phase_peaks_0637.py): krátký peak pouze mezi 5s tick, unikátní čas reportu, chybějící/invalidní jednotka/stale data, reset při sběrovém selhání, přenos přes kolektor a RAM, virtuální blok při >25 A; žádné fyzické akce.
- Původní testy, strict doc/version check, GitHub CI a skutečné nasazení se evidují samostatně.
- První úplnou reálnou noc po nasazení je nutné ověřit **srovnáním 1s HA historie a nového `measured_phase_max_a`**, potvrdit status ok nebo poctivě hlášené výpadky, 0 physical actions a transportní ACK.
- Syntetický test neprokazuje HW bezpečnost. Dlouhodobá rezerva fází, fyzický current limiting, reálné prodlevy a MODE8 mapování stále blokují LIVE.

# Přezkoumání noci 12. 11. 2026 · správná cena a preflight 02:59 (0.6.31)

## Závazný rozsah podle uživatele

1. **Pouze `observe_only`**, nikdy fyzické řízení. „would_set“, „would_stop“ a modelová energie jsou návrhy, nikoli provedené příkazy.
2. **Pro audit stínového doplňku hodnotit pouze 03:00:00–05:00:01 Europe/Prague.** Události po 05:00:01 do jeho odpovědnosti nepatří; předchozí report z 12.11 mylně vyzvedl externí opětovné nabíjení po 05:20. Nejde o chybu stínového runtime ani o tento audit.
3. **Cena musí mít zdroj a měřicí hranici.** Pro požadovaný náklad podle uživatelova grafu platí tarifní senzor `sensor.cez_indi_cenik`, nikoli `sensor.current_buy_electricity_price`.
4. Požadavek: validovat SOC model a fáze již od 02:59, avšak před 03:00 nepřebírat virtuálního vlastníka a po 03:00 znovu ověřit skutečně nové reporty.

## Oprava cenového vyhodnocení / PRICE-01

Pro čtvrtek **2026-11-12** má `sensor.cez_indi_cenik` v atributech `today[]` tyto hodinové řádky (lokální ČR):
- 03:00–04:00 — **NT 1,8078 Kč/kWh**
- 04:00–05:00 — **NT 1,8078 Kč/kWh**

Jde o shodu s uživatelem přiloženým grafem. Senzor hlásí `today_valid=true`, měnu Kč/kWh a složky sazeb včetně DPH. **Upřesnění uživatele 12. 11. 2026:** konfigurace `sensor.cez_indi_cenik` byla sestavena **podle skutečné smlouvy ČEZ a ceníku ČEZ INDI**; uživatel ji již doložil a ověřil. **Pro tento dům jde o autoritativní smluvní cenový zdroj**, a cena **1,8078 Kč/kWh** v čase 03:00–05:00 je tudíž správná – nikoli pouze hypotetická cenová varianta. Pole `rates.hdo_zdroj` označuje pevný rozvrh PTV3 nastavený podle uživatelem ověřených podmínek; nejde o live HDO signál. Interní senzor `sensor.current_buy_electricity_price` reprezentuje jiný cenový model a nesmí nahradit smluvní cenu. Původní poznámka o údajně neověřeném smluvním ceníku byla nesprávná.

Z uzavřené noční historie: síťový čítač zaznamenal rozdíl **23,63 kWh**, tedy orientační náklad dle tohoto konkrétního ceníku **23,63 × 1,8078 = 42,72 Kč**. Samostatný odečet wallboxu ukázal přibližně **22,67 kWh AC** (nikoli totéž co celkový odběr domu), skutečné SOC baterie domu **11 → 11 %**, její vstupní energie **0,0 kWh**. Stínový model baterie **10,76 kWh / ~94,49 %** je nerealizovaný návrh a do skutečné energie či faktury se nezapočítává.

Předchozí výpočet cca **185 Kč** použil jiný sensor `sensor.current_buy_electricity_price`: **03:00–04:00 7,7080**, **04:00–05:00 7,9089 Kč/kWh**. Jde o samostatný tržně odvozený cenový model; zaměnit jej s ceníkem `sensor.cez_indi_cenik` bez výslovné volby metodiky bylo **chybou auditního výpočtu**, nikoli prokázanou chybou samotného optimalizátoru. Optimalizátor již používá `soc_runtime.IDS['tariff'] = 'sensor.cez_indi_cenik'`. Starý chybný odhad v původním výstupu ponechán v historii s tímto opravným dodatkem.

## Provozní noční záznam / NIGHT-0630

Důkazy jsou pouze na lokálním RPi:
`/share/hec-recovery/audit-0630-20261112/` (REPORT.md, final-audit.json, monitor-health.json, journal-audit.json, nezměněné soukromé časové řady).

- Instalovaná **0.6.30**, pouze observe_only, celé 03:00–05:00; 1 442 nočních vzorků, 1 440 bez vstupní vady.
- 1 443/1 443 přenesených a SHA-256 ověřených částí journalu, 507 událostí, 0 chybějících částí.
- 230 historických stínových monitorů, všechny `ok`, 0 restartů, 0 overflow, 0 fyzických povelů.
- Stáří cache maximálně 3,023 s při TTL 7,5 s; délka report requestu max. 0,172 s; 0 nových failure generation během noci.
- Startovní blokace **03:00:04** `missing_battery_energy_model`, **03:00:14** `invalid_phase_input`; virtuální start **03:00:24**.
- Jediné `would_stop_charge` v **05:00:00** má důvod `window_end` (očekávaný koncový stav, **ne** porucha).
- Naměřené fáze maximum 17,3/20,0/16,9 A pod 3×25 A; model bez rezervy sahá téměř na 25 A. Nevypovídá o nepozorovaných špičkách ani fyzické bezpečnosti.

## Zjištěný skutečný problém / START-01

Původní hypotéza „systém začne načítat data teprve ve 03:00“ byla po přečtení produkčního kódu **vyvrácena**:

- `night.window(at)` pokrývá **02:55–05:05**, takže `SnapshotCollector` již běží v nočním pollingu 1 s a `next_wait` v rychlé smyčce 5 s před 03:00.
- `priority.observe` však sestavoval `instant_fill.session` **jen v aktivním okně 03:00–05:00** a `ram_control.observe` zahajoval stavovou relaci až při jeho začátku.
- Samotná existence čerstvé cache tedy nezajišťuje, že je před startem nachystaný session `battery_energy_model` a že proběhla předběžná kontrola koherence fází.
- Rozhodující příčina jediné konkrétní fázové nekonzistence v 03:00:14 není z pouhého důvodu `invalid_phase_input` dokázána; může jít o skutečný přechod při rozběhu EV. Přesun kontroly dříve není důkazem jejího odstranění.

## Implementace 0.6.31: diagnostický preflight

- Pouze **poslední minuta 02:59:00–03:00:00 v Europe/Prague**. Podzimní návrat hodin bere pouze *druhou* 02:59 před skutečnou 03:00.
- `priority.observe` už od 02:59 sestaví read-only `instant_fill.session` z v té chvíli dostupného historického energetického modelu. **Nevytváří** `priority_runs` ani `priority_samples` před aktivním oknem.
- RAM `startup_preflight` kontroluje aktuální timestampy a jednotky, fázovou koherenci, skutečné vlastnické/reportovací konflikty, režimy a dostupnost modelu. Potenciální aktivní alokace se jen *vyhodnocuje na blížící se časové hranici*; výsledkem je **diagnostika**, nikoli výkonový intent.
- `startup_preflight.status` = `inputs_prevalidated` nebo `waiting_for_inputs`, s `reason_codes`, původním časem snímku a hodnotami `active=false, device_actions=0, control_lease=null`.
- **Bez posunu okna**, příkazů HA, změn limitů 25 A, TTL, streamů, cen, automatizací, přidání nového fyzického adaptéru či změny původního `energy_coordinator`.
- Preflight není náhradou za post-start čerstvost: **dvě nové koherentní sady jsou povinné i po 03:00**. Ani nyní nelze garantovat první nenulový virtuální intent přesně v 03:00:00.
- **Aktuální stav 12.11.:** `0.6.31` je na Raspberry Pi v HA skutečně nasazená, `started`, pouze `observe_only`. [Provozní akceptace po nasazení](DEPLOYMENT_0631_20261112.md) potvrdila čerstvý sběr, evidenci s rostoucím ACK a nulové restarty. Úspěch mimo noc ještě neprokazuje skutečný start 02:59/03:00 příští noci.

## Akceptace a rizika

Syntetický test `priority_shadow/tests/test_preflight_0631.py` ověřuje zdroj ceníku, DST, model, vadnou fázi, vstupní kontrolu a dvě nové post-boundary reporty. Před prvním nasazením je potřeba plný `validate-distribution` PASS. Po nasazení zvlášť ověřit reálnou noc: čas prvního `startup_preflight`, model dostupný před 03, případné `reason_codes`, po 03:00 novou čerstvou sadu, začátek relace, SHA stream, ACK a guardy. V případě skutečného přechodového skoku po 03 konzervativní odmítnutí zůstává správné.

Stále **NO-GO pro fyzické řízení**: LIVE-01/02/03 (adaptér, Mode8 readback/timeout, fázová rezerva, fyzické špičky, kalibrace), historické N06-02/DB-01 se jednou bezchybnou nocí neuzavírají.

Veřejný zdroj obsahuje pouze souhrn, chyby a syntetické testy. Úplné naměřené časové řady, archiv databáze, logy, konfigurace domácnosti a přístupové údaje zůstávají na RPi.

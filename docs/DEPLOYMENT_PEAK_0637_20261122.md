# PEAK-01 — ověřené nasazení 0.6.37 na Home Assistant Raspberry Pi

**22. listopadu 2026, 10:30–10:32 SEČ.** Provozní přejímka pouze stínového doplňku `local_energy_priority_shadow`. Žádné nové fyzické povely, žádné změny SolaX Modbus, jističe, EV/HA Recorderu ani retence.

## Zdroj a ověření

- GitHub [PR #56](https://github.com/inenger/home-energy-coordinator-ha/pull/56), merged `9ad944945ee30c6518dc5a11e171b2b97d744be1` do `main`, obě CI úlohy `validate` a `recovery-python314` **PASS**.
- Lokální úplná sada testů na RPi: **654 PASS**, syntetická PEAK-01 E2E potvrzuje proud 20,3 A mezi výpočty a virtuální blok při >25 A, bez fyzických akcí.
- Před instalací vytvořena a pomocí Supervisor API ověřena nativní partial záloha stínového doplňku 0.6.36, soubor na RPi, 738 426 880 B; předchozí zdroj 0.6.36 archivován odděleně v `/share/hec-upgrades/20261122-0637/source-dir-0636`. Přesný identifikátor a obsah zálohy nejsou publikovány do Gitu.
- `git archive origin/main priority_shadow` je potvrzeným zdrojem aktualizace. Supervisor ARM64 image 0.6.37 byl úspěšně sestaven a nainstalován, služba spuštěna.

## Reálný readback po restartu

- Supervisor: **`started`**, version **`0.6.37`**, mode **`observe_only`**.
- Home Assistant `sensor.nocni_stinovy_plan`: `software_version=0.6.37`, `collection_health.status=ok`, `evidence_pipeline.status=ok`, SHA-256 podepsaného/komprimovaného atributu PASS, `device_actions=0`.
- Nová `fast_loop.collection_worker.phase_peaks`: stav **`ok`**, `breaker_a=25.0`, `lookback_s=8.0`, **3** nové unikátní reporty pro každou fázi během kontrolního okna, u každé fáze neprázdná `maxima.{L1,L2,L3}.at` a `a`, `unverified_phases=[]`, `over_limit_phases=[]`. Proběhlo mimo noční okno, proto očekávaný `collection_worker.poll_interval_s=2.5`, v okně 03–05 je nastaveno `1.0`.
- `sensor.nocni_stinovy_ridici_denik` uzavřen, `mode=observe_only`, `device_actions=0`, komprimovaný atribut SHA PASS. SOC asynchronní výpočet může po restartu nejprve hlásit `waiting_for_calculation`; není to důkaz chyby PEAK-01.
- SolaX integrace beze změny: `scan_interval_fast=1`, `scan_interval_medium=5`, `scan_interval=5`.

## Kritéria zbývající pro první noční regresi

- Za následující úplné období 03–05 SEČ porovnat přesné časové průběhy 1s HA Recorderu a nových RAM highwater L1/L2/L3, a nenechat krátkou špičku zapadnout do 5s souhrnu.
- Měřit `overrun_count` jako **delta přes stejné období**, kontrolovat `success_rate`, karanténu/timeout, čerstvost reportů i výpadky fáze. Nepovažovat kumulativní overrun za komunikační chybu.
- Zachovat 0 fyzických akcí, původní ochrannou fyzickou logiku, ACK bez ztrát. Zaznamenaný 25 A guard je jen virtuální fail-closed, **není to hard-real-time ochrana hlavního jističe**.

**Omezení:** Dnešní denní readback ověřuje kolektor, integrační cestu a načtení aktuální nové verze. Není důkazem záchytu příštích krátkých nočních špiček; to zůstává provozním validačním úkolem.

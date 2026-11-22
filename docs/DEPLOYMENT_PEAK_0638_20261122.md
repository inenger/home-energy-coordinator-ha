# Provozní přejímka 0.6.38 – PEAK-02 / MODBUS-02

**22. listopadu 2026, Raspberry Pi Home Assistant (lokální čas Praha).** Změny: čerstvost a mezery posledního platného reportu proudu L1/L2/L3 nezávisle na 8s highwater, a přesné read-only statistiky skutečných dob Modbus cyklů podle numerické periody.

## Implementace a testy

- Zdroj [PR #57](https://github.com/inenger/home-energy-coordinator-ha/pull/57), merged `fe8576998556a9d7c9656500282ce91d8f25824b`; obě CI úlohy PASS, **663 lokálních regresních testů PASS**.
- První on-device Docker image sestavení selhalo výhradně proto, že jeden vendor-only unit test importoval zdroj z repo-root `ops/`, ale standalone image staví pouze adresář addon. Žádná chyba řízení ani Modbusu. Oprava hranice testování (v image **3 skip vendor-only tests**, repo-root nadále 3 PASS) publikována v hotfix commit `3072f8e98223b1c7167d83b19dc6715c6a54615a`; druhý image build úspěšný.
- Nativní HA partial backup HEC 0.6.37 dokončen a ověřen (738 539 520 B) před změnami. Stará source složka zachována v `/share/hec-upgrades/20261122-0638/source-dir-0637`.
- Custom SolaX Modbus 2026.11.04 instrumentace zálohována v `/share/hec-upgrades/20261122-0638/solax_modbus_original`. Původní `__init__.py` SHA-256 `376ba1abf0d85f18f444e2521426812344c67d169d8b1870790948124781b53c`, nový soubor `9507d55ef4226eea8ca00007cdc17a9e8031f0cebd195fc73a1aa976f249c7a0`. V repozitáři se uchovává malý dedikovaný modul `ops/solax_modbus/poll_interval_monitor.py`, nikoli kopie původního vendor zdroje.
- `ha core check` PASS, následný řízený restart pouze HA Core a readback SolaX `Healthy`, success 100 %, quarantine=0. FAST interval stále 1s, MEDIUM a DEFAULT 5s. Nic se neměnilo na Modbus registrech, zápisech, SolaX hardware, EV wallboxu ani hlavní DB Recorderu.

## Skutečné časové metriky SolaX

Přibližně 11:10:49 SEČ, posledních 64 FAST cyklů: interval 1s, průměr 664ms, P95 1236ms, P99 3451ms, maximum 3451ms, 15,6 % překročení intervalu, 100 % úspěšnost. Pomalá spojená skupina MEDIUM+DEFAULT 5s: průměr 1628ms, P95/P99 4098ms, 0 % překročení, 100 % úspěšnost.

Přibližně 11:25:59 SEČ, další rolling okno: FAST průměr 636ms, P95 1531ms, P99 1572ms, 17,2 % překročení, úspěšnost 100 %. Společná 5s skupina průměr 1162ms, P95 1530ms, P99 1558ms, 0 % překročení, úspěšnost 100 %.

Závěr: interval 1s někdy trvá déle než perioda, avšak nelze tuto metriku zaměnit za timeout či ztracenou hodnotu. **1s perioda nebyla změněna na 2s**. Reálná délka cyklu už je oddělena pro každou fyzicky plánovanou skupinu. Není prokázána fyzická ochrana 3×25A jističe.

## Skutečný readback HEC

- Supervisor `started`, version `0.6.38`, mode `observe_only`.
- Plan `collection_health=ok`, `monitor_publication=ok`, `evidence_pipeline=ok`, `device_actions=0`, SHA-256 zabalených atributů PASS.
- Nové `fast_loop.collection_worker.phase_peaks` reálně zveřejňuje 8s maxima, `freshness_limit_s=3.0`, `breaker_a=25.0`, per-phase `phase_quality` a `last_report_age_s`. Při kontrolním readbacku 11:26:57 SEČ `status=ok`, stáří všech tří fází **1,129 s**, worker stále živý.
- Nové `fast_loop.collection_worker.modbus_diagnostics`: `status=ok`, `group_latency_stats` obsahují obě fyzické skupiny, kumulativní overrun a intervalové delty.
- Při prvním publikačním kroku po restartu se jednou spustila **MONITOR_PAYLOAD_OVERFLOW** na diagnostický journal (původní záznam plně zachován v archive). Následující journal byl bez overflow a následná kontrola plánu ukázala `collection_health=ok`, `monitor_publication=ok`, `overflow_count=1`. Nejedná se o ztracenou řídicí dávku; přesto sledovat, aby během nočního provozu nezačalo docházet k opakování této výjimky.

## Otevřená akceptace

První kompletní noc **22.–23.11. 03:00–05:00 SEČ** na 0.6.38: porovnat Recorder proudové špičky a stínové `measured_phase_max_a`, počet a délku stale fází, virtuální 25A guard, delty a P95/P99 Modbusu, úspěšnost komunikace, 0 ztracených dávek, overflow count a nulové fyzické povely. Nastavení pro fyzické řízení **zůstává NO-GO**.

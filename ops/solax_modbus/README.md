# SolaX Modbus per-interval observabilita – lokální instrumentace

Autoritativní čistý kód výpočtu statistik je poll_interval_monitor.py; původní integrační knihovna je vendor soubor na RPi, NEPŘIDÁVAT 186kB vendor soubor do tohoto GitHub repozitáře.

Testovaná lokální instalace: custom_components/solax_modbus, verze 2026.11.04, upstream init.py SHA-256:
376ba1abf0d85f18f444e2521426812344c67d169d8b1870790948124781b53c

Modifikovaný init.py SHA-256:
9507d55ef4226eea8ca00007cdc17a9e8031f0cebd195fc73a1aa976f249c7a0

Změny ve čtyřech přesných bodech na oddělené kopii:

1. Před importem .connection přidat import PollIntervalMonitor z .poll_interval_monitor.
2. Při inicializaci hubu po self._comm_overrun_count = 0 přidat self._comm_interval_monitor = PollIntervalMonitor().
3. V _record_poll_cycle, po existujícím počítání overrunů a před self._update_communication_data() přidat self._comm_interval_monitor.record(interval, elapsed, outcome.communication_succeeded).
4. V communication_health_attributes() hned za atribut overrun_count přidat poll_interval_diagnostics: self._comm_interval_monitor.snapshot(self.config).

Nezasahuje do žádného Modbus requestu, timeoutu, retry či scheduleru. Vzorek je délka dokončeného cyklu, nikoliv jednotlivého Modbus registru. Interval FAST=1 a sloučená MEDIUM+DEFAULT=5 se měří odděleně. Bounded rolling 64 položek a 30s obnovování publikovaného snapshotu.

Po update vendor integrace se lokální změny mohou ztratit. Návrat: z originálního copy-on-disk zálohovaného init.py obnovit původní soubor, odstranit novou poll_interval_monitor.py, restartovat HA Core. Nikdy neupravovat zdroj bez diff/code review a explicitní zálohy.

Původní soubor, nativní Supervisor backup a neveřejné výsledky výkonu zůstávají na RPi. HEC pokračuje v observe_only; HA Recorder/retence, SolaX registry a EV aktuační příkazy beze změny.

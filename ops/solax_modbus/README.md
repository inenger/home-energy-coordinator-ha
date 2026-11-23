# SolaX 2026.11.04 – reprodukovatelná read-only diagnostika 1s / 5s

Proprietární/custom zdroj integrace *nepatří* do tohoto repozitáře;
GitHub uchovává pouze náš vlastní malý monitor a čtyřhunkový delta patch.

- [Čistý Python monitor](poll_interval_monitor.py)
- [Přesný patch pro custom `__init__.py`](solax_2026.11.04_interval_diagnostics.patch)
- CI kontrola: `python scripts/test_solax_patch_contract.py`

**Vstupní SHA-256 (pouze původní `__init__.py`):**
`376ba1abf0d85f18f444e2521426812344c67d169d8b1870790948124781b53c`

**Výstupní SHA-256 (po patchi):**
`9507d55ef4226eea8ca00007cdc17a9e8031f0cebd195fc73a1aa976f249c7a0`

## Reprodukce / ověření na izolované kopii

Předpoklad: odpovídající originální soubor z *téže*
integrace `solax_modbus 2026.11.04` a běžný program `patch`.

1. Zkopíruj celou integraci do izolovaného adresáře,
   nikdy do aktivního `/homeassistant/custom_components`.
2. Ověř SHA vstupního `__init__.py` přes `sha256sum`.
   Pokud nesouhlasí, **neaplikuj**; zkontroluj upstream změny.
3. V kořeni izolované kopie integrace spusť
   `patch --dry-run -p1 < /PATH/solax_2026.11.04_interval_diagnostics.patch`
   a teprve pak `patch -p1 < /PATH/solax_2026.11.04_interval_diagnostics.patch`.
4. Vedle `__init__.py` zkopíruj `poll_interval_monitor.py`.
5. Ověř uvedený výstupní SHA a `python3 -m compileall -q .`.
   Před nasazením prověř kompatibilitu s konkrétní verzí Home Assistantu,
   zálohování původního kódu, rollback a možný dopad do Recorderu.

Patch pouze přidává import `PollIntervalMonitor`, bounded rolling
instanci, jeden `record(interval, elapsed, outcome.communication_succeeded)`
po dokončeném cyklu a `poll_interval_diagnostics` do existujících
health atributů. **Nemění žádný Modbus request, registr, timeout,
překryv ani rychlost měření.** FAST interval je 1 s, sloučené
MEDIUM+DEFAULT 5 s. Snapshot jednou za 30 s,
nejvýše 64 dokončených cyklů v paměti na skupinu.

Aktuální RPi instalace již obsahuje tuto změnu z 22.11.2026.
Zachovaná originální lokální kopie pro rollback:
`/share/hec-upgrades/20261122-0638/solax_modbus_original/`.
Při aktualizaci upstream integrace může být patch přepsán;
**neaplikovat bez hash/diff kontroly** a nevracet vendor
soubor do GitHubu. Při rollbacku obnovit původní `__init__.py`,
odstranit `poll_interval_monitor.py` a podle běžného postupu
restartovat pouze HA Core.

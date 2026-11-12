## 0.6.31

- START-01: read-only validace modelu/fází v poslední minutě před 03:00; před startem nevznikne nový virtuální vlastník, lease nebo příkaz.
- PRICE-01: opraven metodický výběr senzoru v auditu (cez_indi_cenik versus current_buy_electricity_price); uživatel 12.11 potvrdil, že ČEZ INDI ceník je doložen a ověřen podle smlouvy.
- Nové přesné regrese pro DST, cenu, neplatnou fázi/model a dvě nové post-start sady.
- [Kompletní zdůvodnění a rizika](docs/PREFLIGHT_PRICE_AUDIT_0631.md).
- [Dokumentační doplněk 12.11.: skutečné nasazení 0.6.31 a ověřené nové ACK na RPi](docs/DEPLOYMENT_0631_20261112.md).

## 0.6.30

- Opravy N06-03/04, REC-02, DATA-03/04, MON-03 a UI-01; podrobnosti v [kontraktu](docs/READINESS_FIXES_0630.md).
- Žádný live adaptér ani změna automatizací, pouze observe_only.

## 0.6.29

- Cancellable normal-priority admission for durable analytics; local queue wait is explicit and does not replay a partially completed job. Actual SQLite faults retain retry/degraded evidence.
- Remaining RAM/control/priority/audit/SOC/evidence schema checks use read-only existence probes; missing tables/indexes are repaired. FULL/WAL and fast evidence deadlines unchanged.
- No physical control or historical rewrites.

# 0.6.28

- Wallbox určuje připojení a pozorované nabíjení; Tessie je doplňkový zdroj SOC/cíle.
- PLN-01: oddělení nesoučasného EV přechodu od skutečného skoku domu v kalibraci.
- DB-05: příprava mimo writer gate, omezené dávky metadata a férové přidělení zápisů.
- Historie, FULL a observe_only zachované. [Meze a ověření](docs/WALLBOX_WRITES_0628.md).

# 0.6.27

- Local EV/weather calibration context; no legacy runtime DB.
- Bounded preview cadence; full recorder journal retained.
- Six-hour portable copies outside the night window.
- WAL lifetime and passive checkpoint worker, FULL unchanged; writer phase diagnostics.
- Recorder receipt validation outside writer scope.

# 0.6.26 · stabilní hot archiv a čtení bez writer zámku

[Kontrakt, regrese, neúspěšné pokusy a meze](docs/BACKUP_IDLE_0626.md). Pouze observe_only.

# 0.6.25 · deník bez duplicit a komprese mimo writer

Velký živý náhled deníku používá existující úplný multipart stream; session a transport zůstávají v monitoru, vynechaný náhled je výslovně označen. Chybový plán neopakuje celý deník. Příprava transportu běží mimo writer gate, atomický commit kontroluje původní kurzory. Diagnostika rozlišuje držitele lokálního zámku a nativní SQLite chybu bez SQL parametrů. Pouze observe_only.

[Regrese, neúspěšné pokusy a meze](docs/JOURNAL_SQLITE_0625.md).

# 0.6.24 · záloha za běhu bez zastavení regulátoru

Nativní hot záloha s ověřeným SQLite snímkem a kontrolovanou obnovou před workery. Běžný restart nesmí vrátit novější živou DB ke starému snímku. Zachovaná cesta pro zálohu již zastaveného doplňku. Pouze observe_only.

[Kontrakt, regrese, odmítnuté varianty a meze](docs/HOT_BACKUP_0624.md).

# 0.6.23 · rozběh EV, odolná analytika a obnova monitorů

Plně proveditelný naměřený rozběh EV se zachová i pod 6 A. Přetečení jedné entity má úplný soukromý archiv a pravdivý malý doklad; ostatní monitory pokračují. Analytika má trvalou FIFO frontu s retry mimo potvrzování řídicí evidence. Dohled rozlišuje odpovídající HTTP výpadek od zamrzlého publisheru, používá tři obnovy za 300 s a omezuje opuštěná IPC vlákna. Pouze observe_only.

[Opravy, regresní případy, slepé cesty a meze](docs/NIGHT_FIXES_0623.md).

# 0.6.22 · nezávislá obnova a dohled pomocných procesů

Po převzetí chyby regulátorem v RAM se čerstvá cache obnoví nezávisle na trvalém potvrzení deníku. Produkční sběr nikdy nezapisuje chybu na disk ve vstupním vlákně. Pozdější ztráta evidence nepřepisuje uzavřenou relaci; má samostatný trvalý doklad. Pomocné procesy mají heartbeat a nejvýše tři automatické obnovy za běh; nepotvrzené dávky se idempotentně opakují. Zaseknutá publikace se hlásí jako degraded. Pouze observe_only.

[Opravy, reprodukce, slepé cesty a meze](docs/RECOVERY_FIXES_0622.md).

# 0.6.21 · oprava falešné blokace ručním podrežimem

Uložená Force Charge/Force Discharge při čerstvém známém Back Up Mode, Self Use Mode nebo Feedin Priority neblokuje stínové převzetí. Aktivní ruční nabíjení/vybíjení v Manual Mode, neznámé režimy, cizí vlastník a zastaralé vstupy dál blokují. Reporty pracovní strategie a podrežimu omezují platnost intentu. Pouze observe_only.

[Chování, regrese a meze](docs/MANUAL_MODE_FIX_0621.md).

# 0.6.20 · regulace oddělená od ukládání evidence

Řídicí smyčka používá soukromý stav v paměti. Diskové zápisy a analytika mají vlastní proces; příprava a HTTP monitorů další proces. Omezená fronta hlásí zpoždění a případnou ztrátu evidence, aniž by resetovala platný řídicí návrh. Skutečné vstupní a bezpečnostní poruchy nadále zastavují. Pouze observe_only.

[Architektura, syntetické regrese a historie pokusů](docs/CONTROL_ISOLATION_0620.md).

[Úplný předchozí changelog ve verzované historii](https://github.com/inenger/home-energy-coordinator-ha/blob/af73cb3c1df6827e9843677a9ce2161cccde07ba/priority_shadow/CHANGELOG.md). Předchozí historie zůstává zachovaná; do této změny nejsou znovu vkládány provozní dokumenty ani rozsáhlé logy.

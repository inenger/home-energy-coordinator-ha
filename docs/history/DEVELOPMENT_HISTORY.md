## 0.6.30 · readiness opravy, 11. 11. 2026

Vstupní commit `dee01fc`. Sedm softwarových counterexample reprodukcí převedeno na akceptaci; originály uchovány jako readiness_counterexamples_0629.py/mjs. SOC první kandidát neuložil revokaci kvůli rollback při výjimce v SQLite transakci, poté opraven commit a pozdější raise. Asynchronní REST první varianta vyžadovala upravit staré testy závislé na synchronní odpovědi. Další kandidát pickle fingerprint selhal na determinismu po multiprocessing a watchdog chybně zahrnoval již potvrzené seq; obojí napraveno, skutečné spawn replay regrese po opravě PASS. Komplexní RPi testovací průchod přerušen kvůli ochraně HA hostitele, nenárokovat PASS. [Podrobný report](../../priority_shadow/docs/READINESS_FIXES_0630.md).

# Dohledatelná historie vývoje

Aktuální zdroj0.6.27, pouze observe_only.

[Kontrakt, regrese a odmítnuté varianty0.6.27](../../priority_shadow/docs/STANDALONE_0627.md).

[Předchozí neměnná verze tohoto dokumentu](https://github.com/inenger/home-energy-coordinator-ha/blob/2fe74836c3a87ec53184434e2c095180d48f3142/docs/history/DEVELOPMENT_HISTORY.md); původní obsah zůstává v historii Git a není touto dodávkou přepisován zpětně.

## Aktuální pravidla

- Autoritativní nový balíček je priority_shadow; původní balíček se nekopíruje ani neaktualizuje novým runtime.
- Žádný fyzický akční adaptér. Historická měření, seed, provozní doklady a credentials zůstávají soukromé.
- DEP-01: místní kalibrace a vlastní sběr; zastavení legacy až po ověřené migraci.
- DB-04: porovnání recorder zpráv mimo gate, stabilní WAL a oddělený PASSIVE checkpoint při FULL.
- DATA-02: omezená četnost diagnostických náhledů a šestihodinové portable kopie mimo okno. Úplný journal transport zůstává.
- DB-01: příčina všech historických timeoutů není uzavřená; diagnostika SQL/commit/close a provozní ověření zůstávají nutné. N06-02 a LIVE blokátory zůstávají otevřené.
- První syntetická planner fixture neměla fit_period; druhá neobsahovala schéma priority_samples z produkčního maintenance entrypointu. Obě vyvolaly calculation_unavailable a byly opravené, nikoli potlačené.
- Vývojový baseline je veřejný strom předchozího vydání. Lokální testy, veřejná CI, merge a skutečné nasazení jsou samostatné důkazy. Nová celá noc není nahrazena syntetikou.


##0.6.28 · wallbox and bounded write follow-up

Baseline0.6.27, synthetic PLN-01 counterexample in [issue36](https://github.com/inenger/home-energy-coordinator-ha/issues/36) confirmed the old defect. [Final source contract](../../priority_shadow/docs/WALLBOX_WRITES_0628.md) records source authority, transition uncertainty, bounded writer changes and acceptance boundaries. Private historical traces remain on RPi. New failures/adjustments must be appended, not silently removed.


## 0.6.29 · background admission

Baseline source79d3f6d/treecde4d286. [Contract and retained failed candidate](../../priority_shadow/docs/ANALYTICS_ADMISSION_0629.md). First new schema regression failed on remaining RAM DDL; production RAM/control/priority/audit/SOC/batch entrypoints fixed, regression unchanged. Reject increasing fast evidence TTL/SQLite timeout, resetting counters or claiming background waiting eliminated physical I/O. Older analytics timeout test adapted to cancellation/FIFO; actual SQL/partial failure tests retained. RPi lacks rg, source inventory used Python. Source, CI, native deployment and whole-night evidence are distinct.


## Audit připravenosti 0.6.29

Vstupní veřejný merge2b83d779fcf416b72a8827adde1aa7fdd37b7953, runtime beze změny. [Nálezy, odmítnuté hypotézy a kritéria](../READINESS_AUDIT_0629.md). První suite5PASS/1FAIL: audit očekával sémantickou zprávu, která se v produkci ztrácí; vznikl MON-03 a přesná kontrola source location. První rozšířená worker fixture použila e.sqlite místo požadovaného evidence.sqlite; opravena fixture, nikoli recovery aserce. Hypotéza backdating nového počasí vyvrácena skutečným timestampem po převzetí odpovědi. Původní pokusy uchované. Nová sada dokládá vady, neopravuje je. DOC-01 opravuje aktuální rozcestník, verzi registru a rozpadlou tabulku; historické dokumenty nemazat. Soukromé provozní důkazy zůstávají na RPi.

Předpublikační diff check ještě odmítl prázdný řádek na konci přeskládaného registru. Whitespace normalizován před commitem; žádná vzdálená publikace v neúspěšném pokusu neproběhla.


## 12. 11. 2026 – PRICE-01 a START-01, 0.6.31

Vstup main 5360c73d593b80b85d0e972ed828935ffd6ebe34, běžící RPi 0.6.30.
Původní automatický audit zaměnil senzor current_buy_electricity_price (7,7080 /
7,9089 Kč/kWh) za uživatelem používaný cez_indi_cenik (1,8078 Kč/kWh).
Uvedených ~185 Kč je chybný ekvivalent pro uživatelův ceník; oprava 23,63 ×
1,8078 = 42,72 Kč. Není ověřená smluvní fakturovaná částka.

Vyvrácena hypotéza, že sběr začne až ve 03. Produkční noční window zrychluje
collector na 1 s a RAM smyčku na 5 s již v 02:55. Skutečný nedostatek byl
předsestavení session/modelu a předběžná kontrola fáze.
Přidán read-only preflight od 02:59; před 03 žádné RAM sessions / events /
commands / lease, dvě nové sady po 03 povinné, DST dvojitá hodina ošetřena.

První syntetický test neplatné fáze FAIL: fixture měnila výkon L2 na identickou
výchozí hodnotu, takže nevytvořila rozpor. Opravena pouze fixture na fyzicky
nekoherentní proud L2 0,1 A; produkční ochrana nebyla oslabena. Následná
přímá nová sada PASS. CI, merge a nasazení jsou samostatné důkazy.
Původní soukromá data zůstávají na RPi, nikoli ve veřejném GitHubu.

[Plný kontext](../../priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md).

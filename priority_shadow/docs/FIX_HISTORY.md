## 0.6.30 · sedm oprav auditu

[Kontrakt a historické FAIL](READINESS_FIXES_0630.md). Jen observe_only, nedotčené fyzické řízení a originální provozní data.

# Historie oprav

Aktuální zdroj0.6.27, pouze observe_only.

[Kontrakt, regrese a odmítnuté varianty0.6.27](STANDALONE_0627.md).

[Předchozí neměnná verze tohoto dokumentu](https://github.com/inenger/home-energy-coordinator-ha/blob/2fe74836c3a87ec53184434e2c095180d48f3142/priority_shadow/docs/FIX_HISTORY.md); původní obsah zůstává v historii Git a není touto dodávkou přepisován zpětně.

## Aktuální pravidla

- Autoritativní nový balíček je priority_shadow; původní balíček se nekopíruje ani neaktualizuje novým runtime.
- Žádný fyzický akční adaptér. Historická měření, seed, provozní doklady a credentials zůstávají soukromé.
- DEP-01: místní kalibrace a vlastní sběr; zastavení legacy až po ověřené migraci.
- DB-04: porovnání recorder zpráv mimo gate, stabilní WAL a oddělený PASSIVE checkpoint při FULL.
- DATA-02: omezená četnost diagnostických náhledů a šestihodinové portable kopie mimo okno. Úplný journal transport zůstává.
- DB-01: příčina všech historických timeoutů není uzavřená; diagnostika SQL/commit/close a provozní ověření zůstávají nutné. N06-02 a LIVE blokátory zůstávají otevřené.
- První syntetická planner fixture neměla fit_period; druhá neobsahovala schéma priority_samples z produkčního maintenance entrypointu. Obě vyvolaly calculation_unavailable a byly opravené, nikoli potlačené.
- Vývojový baseline je veřejný strom předchozího vydání. Lokální testy, veřejná CI, merge a skutečné nasazení jsou samostatné důkazy. Nová celá noc není nahrazena syntetikou.


##0.6.28 · EV-01/PLN-01/DB-05

[Contract](WALLBOX_WRITES_0628.md) and test_wallbox_0628.py. Original counterexample demonstrated the defect in0.6.27; corrected tests preserve real house steps, old records, FULL and fail-closed live inputs. Public CI, native installation and whole-night validation are separate.


## Audit připravenosti 0.6.29 — runtime beze změny

[Audit a reprodukce](../../docs/READINESS_AUDIT_0629.md): N06-03/N06-04/REC-02/DATA-03/DATA-04/MON-03/UI-01 jsou nově otevřené, LIVE-03 výslovné omezení monitorů. Counterexample PASS znamená potvrzenou mezeru. DOC-01 opravuje pouze dokumentaci a její kontrolu. Žádný fyzický adaptér ani aktivace LIVE. První dvě neúspěšné auditní fixture a vyvrácená hypotéza počasí jsou zachované v historii auditu.

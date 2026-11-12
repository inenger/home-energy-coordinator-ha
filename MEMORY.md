# Aktuální vývoj 0.6.31 · 12. 11. 2026

- [Cena ČEZ INDI, audit noci a příprava 02:59](priority_shadow/docs/PREFLIGHT_PRICE_AUDIT_0631.md).
- Běžící HA 0.6.30 absolvoval jednu úplnou noc 03–05 se zdravou evidencí; původní soukromý report je jen na RPi.
- Závazný rozsah: observe_only; pro noční audit ignorovat události po 05:00:01 jako činnost tohoto doplňku.
- Chybný audit ~185 Kč používal jiný senzor než graf. Podle uživatelského sensor.cez_indi_cenik platí obě hodiny NT 1,8078 Kč/kWh a 23,63 kWh odpovídá 42,72 Kč. Nejde o ověřenou fakturu.
- 1s kolektor a 5s rychlá smyčka běžely už od 02:55. 0.6.31 od 02:59 připraví analytický model a validuje aktuální fázové reporty; dvě nové sady až po 03 zůstávají povinné.
- Tento zdroj 0.6.31 zatím není důkazem CI ani nainstalované verze. N06-02, DB-01, LIVE-01/02/03 stále otevřeny.

---

# Stav 0.6.30

[Sedm oprav readiness auditu](priority_shadow/docs/READINESS_FIXES_0630.md), bez LIVE a nasazení. N06-02, DB-01 a LIVE stále otevřené. Historické auditní protipříklady zachované.

# Projektová paměť

Aktuální zdroj0.6.29, pouze observe_only.

[Kontrakt, regrese a odmítnuté varianty0.6.27](priority_shadow/docs/STANDALONE_0627.md).

[Předchozí neměnná verze tohoto dokumentu](https://github.com/inenger/home-energy-coordinator-ha/blob/2fe74836c3a87ec53184434e2c095180d48f3142/MEMORY.md); původní obsah zůstává v historii Git a není touto dodávkou přepisován zpětně.

## Aktuální pravidla

- Autoritativní nový balíček je priority_shadow; původní balíček se nekopíruje ani neaktualizuje novým runtime.
- Žádný fyzický akční adaptér. Historická měření, seed, provozní doklady a credentials zůstávají soukromé.
- DEP-01: místní kalibrace a vlastní sběr; zastavení legacy až po ověřené migraci.
- DB-04: porovnání recorder zpráv mimo gate, stabilní WAL a oddělený PASSIVE checkpoint při FULL.
- DATA-02: omezená četnost diagnostických náhledů a šestihodinové portable kopie mimo okno. Úplný journal transport zůstává.
- DB-01: příčina všech historických timeoutů není uzavřená; diagnostika SQL/commit/close a provozní ověření zůstávají nutné. N06-02 a LIVE blokátory zůstávají otevřené.
- První syntetická planner fixture neměla fit_period; druhá neobsahovala schéma priority_samples z produkčního maintenance entrypointu. Obě vyvolaly calculation_unavailable a byly opravené, nikoli potlačené.
- Vývojový baseline je veřejný strom předchozího vydání. Lokální testy, veřejná CI, merge a skutečné nasazení jsou samostatné důkazy. Nová celá noc není nahrazena syntetikou.


## Zdroj0.6.28

[Wallbox a zápisy](priority_shadow/docs/WALLBOX_WRITES_0628.md): EV-01 autorita wallboxu, PLN-01 koherentní učení rezervy, DB-05 příprava mimo gate a dávky recorder metadata. Fyzický adaptér se nepřidává. DB-01/N06-02 a LIVE zůstávají otevřené. Lokální testy, CI a nativní nasazení jsou samostatné důkazy.


## Zdroj 0.6.29

[DB-06](priority_shadow/docs/ANALYTICS_ADMISSION_0629.md): přerušitelné normální čekání pouze durable analytiky a zbývající no-op schema guardy. Skutečné SQL chyby a původní evidence zachované; DB-01 není uzavřená. První nová regrese odhalila další RAM DDL; opraveny všechny související entrypointy, nikoli oslabený test. Jen observe_only.


## Audit připravenosti 0.6.29

[Zdrojový audit](docs/READINESS_AUDIT_0629.md) má verdikt NO-GO pro fyzické řízení. Nové otevřené N06-03/N06-04/REC-02/DATA-03/DATA-04/MON-03/UI-01, explicitní LIVE-03. Counterexample PASS potvrzuje existenci vady, ne její opravu. Runtime beze změny, zdrojové a soukromé provozní doklady oddělené. DOC-01 zpřesňuje aktuální dokumentaci a verifikátor; historické texty zachované.

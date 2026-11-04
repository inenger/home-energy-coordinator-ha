# 0.6.21 · podrežim vyhodnocovaný v kontextu pracovní strategie

Původní gate blokovala Force Charge/Force Discharge i při Back Up Mode. Nově
se oba podrežimy považují za aktivní ruční nabíjení/vybíjení pouze tehdy, když
čerstvý známý pracovní režim říká Manual Mode. Uložená volba při Back Up Mode,
Self Use Mode či Feedin Priority již sama převzetí stínové relace neblokuje.

Mapování vychází ze samostatných Gen4 registrů pracovní strategie (0x1F)
a ručního podrežimu (0x20), ověřených ve zdroji integrace. Její
[dokumentace pracovních režimů](https://homeassistant-solax-modbus.readthedocs.io/en/stable/solax-G4-operation-modes/)
řadí tři volby pod Manual Mode. Nejde o novou fyzickou validaci zařízení.

Oba reporty musí mít známé hodnoty a původní HA last_reported mladší15s.
Neznámé režimy včetně neověřených PeakShaving/Smart Schedule, neznámé
podrežimy, chybějící či zastaralý report nadále blokují. Reporty strategie
a podrežimu nově také omezují input_valid_until a intent_expires_at.
owner_reports nyní obsahují pět pojmenovaných zdrojů. Staré vzorky se nemění.

Vzorek, diagnostika blokace a živý pohled rozlišují work_mode,
stored_manual_submode, manual_submode_applies a skutečně aktivní ruční
nabíjení/vybíjení. Změna pracovního režimu nebo jiného chráněného parametru
po převzetí dál pozastaví relaci a respektuje cizí zásah. Remote control,
vlastník, měření fází, freshness, dvě nové sady a ostatní ochrany zůstávají.

Syntetické regrese procházejí produkční MemoryControl, převzetí, změnu
na Manual Mode za běhu, zastavení, TTL, idempotentní flush, outbox a uzavření.
Ověřují všechny uložené podrežimy při známých pasivních strategiích,
skutečně aktivní ruční charge/discharge, neznámé/chybějící/stará data
a zachování původní neaktivní volby při předání. Původní reprodukce PR18
je v Git historii; nyní má očekávání úspěšného převzetí. Původní baseline
s novým očekáváním selže, opravený zdroj projde.

Jen observe_only. Žádné přepínání fyzických režimů, mazání historie, změny
původních automatizací/tarifu/rezerv/priorit. Oddělení diskové evidence
a analytiky od regulátoru z0.6.20 se nepřesouvá zpět do řídicí smyčky.
Celá nová noc a fyzické řízení se syntetickými testy neprokazují.
Plné provozní podklady/paměť zůstávají na RPi; veřejně kód, syntetika a tento
obecný popis. Nativní build/nasazení a CI se dokládají zvlášť.

Neověřený/stará data mají v diagnostice aktivitu null, nikoli tvrzení o neaktivním řízení. Finální hlavní smyčka je ověřena také přes flush/outbox/přípravu monitorů. Host plná sada před posledním dodaným main testem:498 shadow +164 legacy; finální cílená sada10 kontraktů. Docker a GitHub CI spouštějí finální plnou sadu zvlášť.

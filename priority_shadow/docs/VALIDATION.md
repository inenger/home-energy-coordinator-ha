# Ověření stínových nočních priorit

Režim zůstává observe_only. Sledují se různé druhy důkazů odděleně:

1. Jednotkové regresní testy dokazují vlastnosti výpočtu, ne fyzickou odezvu.
2. Čerstvý HA stav a jednotka dokazují známý stav HA, ne fyzický heartbeat.
3. Historická kontrola bilance/EV fází neověřuje nově zapnuté proudové senzory.
4. Kompletní noční relace uvádí dostupnost prognózy, čas inicializace SOC,
   platné/neplatné intervaly a oddělené AC/DC energie. Bez pokrytí není nula.
5. Srovnání priorit potřebuje shodné časové pokrytí; pro ekonomickou validaci
   také stejné splněné potřeby a konečné zásoby. Přetok sám nic z toho nedokazuje.
6. Ověřená chyba FVE potřebuje shodnou AC/DC měřicí hranici. Později získaná
   prognóza se nevydává za tehdejší znalost. Původní záznamy se nepřepisují.
7. Publikace používá přesný seznam nových monitorovacích entit. Jediné UI
   servisní volání je select_option pro stínový helper. Fyzický adaptér chybí.
8. Před nasazením: záloha doplňku a zdrojů, čerstvý Lovelace config a JS,
   ověření zdrojových hashů. Poté: testy, stav lokálního doplňku a původního
   koordinátoru, čerstvé monitory, integrita DB a HTTP/hash servírovaného JS.
9. Ostré automatizace a ostatní záložky mají zůstat shodné s pořízenou zálohou.


Historii opravených případů najdete v `FIX_HISTORY.md`; aktuální stav v kořenovém `MEMORY.md`.

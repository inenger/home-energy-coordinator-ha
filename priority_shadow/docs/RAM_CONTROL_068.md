# 0.6.8 · výkonový stín bez trvalých zápisů

## Provozní kontrakt
Pouze observe_only. Modul ram_control nemá akční adaptér, HTTP klienta ani Modbus spojení. Výstupem je validovaný logický požadavek W AC s odhadem A DC, persistent_writes=0 a wire_command=null. Neznámé klíče/typ paměti, požadavek na fyzický registr či nenulové trvalé zápisy validátor odmítne. Trvalý Battery Charge Max Current (write0x24/read0x90), Charger Use Mode a Manual Mode Select se pouze čtou. Nová smyčka je nikdy ani virtuálně nenastavuje. Původní deník má vlastní zachované tabulky a označenou starší politiku.

## Řídicí smyčka
Cílový interval v pozorovacím nočním okně je5s; mimo okno60s. Pomalé výpočty SOC, uzavírání souhrnů, denní audit a portable záloha mají samostatné vlákno, vlastní SQLite spojení a HTTP klienta. Výsledek údržby se předává jako kopie. Smyčka není tvrdý realtime: HTTP, SQLite iRaspberry Pi mohou mít zpoždění. Zpoždění>7.5s ruší návaznost a výkonový požadavek.

Kalkulace přijímá pouze Normal Mode s aktuálním HA last_reported, platné fast vstupy do15s a napětí baterie do30s. Rozptyl časů Modbusových fázových hlášení musí být nejvýše2s. Čerstvost se nepřepisuje časem REST dotazu; collector již čte skutečné last_reported přes read-only template. Toto není doklad stejného fyzického měření ani heartbeat zařízení. Vstupy wallboxu mají nezávislé hodiny, jejich stáří se kontroluje zvlášť. Stávající konzistence P/U/I zůstává platná; neplatná data se nedoplňují nulou. Událost uchovává konkrétní vstupy a chybějící pole.

Dva nové souvislé snímky jsou nutné pro převzetí/obnovu. Stejný podpis hlášení nesmí zvýšit výkon ani obnovit logický povel. Logický povel má platnost10s, nejde o ověřený timeout SolaXu. Návrh se zaokrouhluje dolů na100W AC a zvyšuje nejvýše100W AC/s; snížení je okamžité v nejbližším zpracovaném kroku. Tyto hodnoty jsou stínová politika, nikoli schválené fyzické parametry či ověřená jističová ochrana. Výkon se stále omezuje po nejslabší fázi do25A; ověřená reakční rezerva nadále chybí.

## Převzetí a předání
Snapshot vznikne po použitelných vstupech před prvním virtuálním převzetím. Zůstává virtuální pozastavení pěti přesně vyjmenovaných automatizací a podržení EV priority. Výkonový model má vlastní SOC/energii podle skutečně navrženého omezeného výkonu; ideální max-fill srovnání se nepovažuje za uskutečněný RAM průběh. Začátek při zpoždění používá čerstvé SOC. Výpadky se nepřemosťují.

Při chybě nastane virtuální0W. Na konci okna se nejprve uvolní logický požadavek, potom se vrátí pouze převzaté automatizace/EV příznak. Původně vypnuté zůstanou vypnuté. Běžící EV má conditional_handoff, neznámý stav restore_pending; manuální změna se nepřepíše. Restart pokračuje z vlastní evidence; chybějící konec se nezpětně nedatuje. Neuzavřená starší relace brání druhému vlastníkovi.

## Rozhraní SolaXu a EEPROM
Zdroj integrace a dokumentace rozlišují běžná persistentní nastavení a provozní VPP povely. Přítomnost entity či čitelných registrů není důkaz fyzické podpory ani bezpečného návratu. Z nové vrstvy není možné aktivovat Mode8 ani jiný režim.

Při auditu místní integrace byl nalezen rozdíl mezi názvy direct parametrů a výrobcovým popisem Mode8:0xA6 je ExecDuration,0xA7 je NextMotion (0xA0 návrat do základní strategie,0xA1 přechod doVPP6). Direct entity je popisují jako duration/timeout a poslední umožňuje zadat časovou hodnotu. Nepřebírat takový převod bez opravy/ověření. Výrobcův dokument ukazuje regulaci na portu baterie; účinnost převodu k přípojce musí být samostatně ověřena. Readback1A6 s názvem Timeout sám nedokazuje hardwarové vypršení při ztrátě HA. wire_mapping_verified, ac_dc_boundary_verified, timeout_verified a physical_control_ready jsou proto false.

Zdroje:
- https://homeassistant-solax-modbus.readthedocs.io/en/latest/solax-mode8-modbus-power-control/
- https://kb.solaxpower.com/solution/detail/2c9fa4148ecd09eb018edf67a87b01d2 (Mode8, obrazové strany18–19)

## Ověření
Syntetické testy zahrnují celou120min relaci po5s, nezměněné persistentní registry, odmítnutí neznámého zápisu, stavy/čerstvost/skew, rozporný vzorek, obnovu až po dvou snímcích, expiraci logického povelu, restart, ruční konflikt, předání a blokující pomalou údržbu. Renderer rozlišuje model W AC, odhad A DC a trvalý proudový limit. Testy nejsou fyzická validace. Před ostrým testem je nutné ověřit konkrétní protokol, EEPROM semantiku i chování při ztrátě komunikace; tento release jej nezapíná.

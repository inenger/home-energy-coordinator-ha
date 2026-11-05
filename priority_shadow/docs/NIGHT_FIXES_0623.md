# 0.6.23 — opravy nálezů A22-01 až A22-04

Výchozí veřejný runtime: 0.6.22, main `9d8a86e1ade8bbb966f453d41ec34ac3c33d33eb`.
Navazuje na [původní audit](../../docs/NIGHT_AUDIT_0622_20261105.md) a jeho zachovaný
[reprodukční skript](../../scripts/audit_ev_startup_0622.py). Tento historický skript
**očekává starou vadu**; není bránou správnosti nové verze. Audit ani původní noční
vzorky se opravou nepřepisují. Soukromé skutečné podklady zůstávají na RPi.

## A22-01: rozběh EV není požadavek na nastavení pod 6 A

Při plně proveditelném naměřeném požadavku (`f == 1`) se zachová i přechodný
odběr pod 6 A. Minimum se nadále uplatní při skutečně navrhovaném omezení EV.
Není tím přidán povel wallboxu ani povolen zásah bez akčního adaptéru. Při
potřebě takového zásahu RAM stále hlásí `requires_ev_control_not_implemented`.

Regrese pro obě priority, jednu i tři fáze procházejí skutečnou `run_loop`, RAM,
SQLite, trvalým outboxem a přípravou monitorů. Opačný případ se skutečným omezením
pod minimální proud zůstává blokovaný. Proudová mez 25 A a DC mez baterie platí.

## A22-02: přetečení jedné entity neblokuje celou sadu monitorů

Příprava rozlišuje jednotlivé entity. Pokud ani bezztrátový zabalený obsah
nevyhoví rozpočtu 14 000 B atributů, monitorovací proces uloží úplné původní
atributy do soukromého obsahově adresovaného archivu `monitor-overflow`.
Zápis má SHA-256, kompresi zlib, fsync souboru i adresáře a oprávnění 0600.
Příslušná entita publikuje `payload_overflow` a malý doklad s entitou, časem,
velikostí a hashem; ostatní entity pokračují. Monitoring zůstává degraded až
do nové úspěšné přípravy. Idle heartbeat chybu nemaskuje.

Archiv se automaticky nemaže a má limit 64 MiB. Chyba disku nebo vyčerpaný
limit výslovně vrací `retained: false`; nesmí tvrdit uchování. Úplný obsah
přetečeného monitoru není v recorderu ani automaticky dostupný kartě přes
HA API. Doklad říká `full_payload_in_recorder: false`; skutečný řídicí deník
má vlastní původní trvalý transport. Nejde o tiché oříznutí ani o záruku zápisu
při selhání disku. Historický ztracený detail dvou přetečení 0.6.22 nelze obnovit
pouhým zpětným přidáním diagnostiky.

## A22-03: trvalá FIFO fronta vedlejší analytiky

Každá dávka zapisuje původní vstupy a čas analytické úlohy atomicky se svým
commit receipt do `control_analytics_pending`. Potvrzení řídicí evidence a
outbox pokračuje ve vlastním vlákně. Analytika má jiné spojení/vlákno, krátké
čekání na writer a retry s odstupem 0,5 až 5 s. Úloha zůstává v databázi až
do dokončení; po restartu se obnoví ve stejném pořadí a s původními vstupy.
Nejde o coalescing či náhradu zmeškaného vzorku novým měřením.

`WriterTimeout` a skutečné SQLite BUSY/LOCKED jsou rozlišeny od I/O chyby.
Health obsahuje původní kód/název/hlášku, počet retry a poslední závadu i po
zotavení. Neočekávané chyby zůstávají degraded a úloha se nezahodí. Dříve
commitnuté dílčí analytické kroky se opakují idempotentně, bez dvojí energie.
Maintenance dostane nový čas až po vyprázdnění fronty, aby neuzavřela den před
zpracováním jeho čekajících pozorování. Platí stávající limit úložiště;
nekonečné výpadky disku neznamenají nekonečnou kapacitu evidence.

## A22-04: omezená obnova bez doživotního vyčerpání

Dohled dovoluje nejvýše tři pokusy v klouzavých 300 s. Kumulativní počet
restartů a poslední příčina se nemažou. Po dobu vyčerpaného okna je vidět
cooldown; po jeho skončení může dohled znovu zkusit obnovu. Nejde o ruční
reset starého běhu 0.6.22 ani o neomezenou smyčku forků.

Dokončené neúspěšné HTTP pokusy se počítají jako aktivita publisheru. Dostupný
worker při výpadku nadřazeného HA hlásí chybu HTTP a pokračuje v retry, aniž
by zbytečně spotřebovával procesní obnovy. Pouhý heartbeat bez postupu čekající
publikace nadále nestačí: zamrzlý publisher se po 30 s obnovuje.

Nové IPC generace zachovávají replay do durable ack a odmítají staré odpovědi.
Navíc se sledují opuštěná reader i feeder vlákna. Nejvýše tři od každého typu;
živé opuštěné prostředky nad mez zastaví další automatické obnovy s konkrétní
chybou. Uzavírání nedovolí pozdní spawn. Mez chrání prostředky i během mnoha
klouzavých oken; neznamená, že lze vždy zotavit neopravitelný systémový stav.

## Ověření a zachované neúspěšné pokusy

Nová sada `test_night_fixes_0623.py` má 12 testů včetně produkčního evidence
workeru se zablokovanou analytikou, skutečného místního writer zámku, restartu
analytiky, částečného commitu, přetečení a nedostupného archivu. Rozšířená
kritická brána obsahuje 26 případů opakovaných třikrát na Pythonu 3.12 a 3.14.
Stávající úplné testy a kontroly distribuce zůstávají součástí vydání.

První cílený běh odhalil chyby testovacích přípravků: neexistující název priority
místo `Baterie SolaX`, jméno `e.sqlite` místo produkčního `evidence.sqlite` a
záporný případ, jehož odběr byl ve skutečnosti stále proveditelný. Přípravky
byly opraveny podle skutečného kontraktu; proudové ani bezpečnostní kontroly
nebyly oslabené. Baseline harness nejprve chybně počítal čtyři subtest failures
jako jednu failure; opravená očekávání potvrzují starý EV stop a absenci
klouzavé obnovy. První soukromý replay také chybně požadoval přesnou nulu rozdílu celkového
a součtu fázových měření EV; opravený test používá existující měřicí toleranci
a dál ověřuje plné převzetí fázového požadavku i všechny limity. Původní logy
jsou zachované soukromě. Během revize byla
rozšířena ochrana prostředků z readerů také na IPC feeder vlákna; finální
regrese a celá sada se ověřují znovu na finálním zdroji.

První read-only nativní preflight dostal omylem syntetický token z univerzálního
test runneru a skončil HTTP 401. Produkční token se nevypisoval; druhý běh
oddělil prostředí skutečného čtení od syntetických testů. Nešlo o závadu HA
a původní neúspěšný log se nepřepisuje.

Výsledek testů, veřejný commit/CI a nativní nasazení jsou samostatné důkazy.
Syntetika a přehrání starých vstupů nejsou nová celá produkční noc. Fyzický
akční adaptér není implementovaný, účinnost/špičky zařízení nejsou ověřené a
25 A bez přechodové rezervy není ochrana jističe. Režim zůstává observe_only.

# 0.6.20 · regulace nezávislá na ukládání evidence

Základ af73cb3c1df6827e9843677a9ce2161cccde07ba (0.6.19).
Pouze observe_only, bez akčního adaptéru a bez změn původních automatizací.

## Příčina a rozsah

0.6.19 dávala krátkým řídicím zápisům přednost před čekajícími background
zápisy. Stále však otevírala diskovou SQLite, kontrolovala kapacitu,
archivovala a prováděla část analytiky ve smyčce regulátoru. Selhání evidence
se tak mohlo změnit ve falešný collection_failure a nulový výkonový návrh.
Koordinace writerů byla zmírnění, nikoli odstranění této závislosti.

## Implementované rozdělení

Produkční entrypoint spouští isolated_control.run_loop. Řídicí vlákno čte
aktuální cache, ověří stejné vstupy/limity, posune stav regulátoru a bez čekání
předá výsledek. Nepoužívá diskový Store, stat rozpočtu, fsync, analytiku,
přípravu monitorů ani HTTP. Nesmí vynechat bezpečnostní kontroly.

Stávající stavový algoritmus ram_control zůstává zachovaný. Pro jeho stav
se používá výhradně soukromá SQLite :memory:, bez společného souboru,
filesystemového zámku a writer gate. Jde o dočasný backend řídicího stavu;
neprohlašujeme tím, že algoritmus přestal používat SQL. Na disku zůstávají
původní tabulky a kompatibilní obsah relací, událostí a vzorků.

Evidence a analytika běží ve vlastním spawn procesu s nižší CPU prioritou.
Získávají jen hotové přírůstky; kontrola kapacity, komprese, trvalý commit,
outbox, recorder a pomalé přepočty nejsou důvodem k resetu řídicího stavu.
Monitoring má další proces: příprava/budget i HTTP jsou mimo regulátor.

IPC odpovědi čtou pomocná vlákna. Samotné Queue.get_nowait může po přijetí
hlavičky čekat na zbytek zprávy, proto ani tento zdánlivě neblokující pipe
read není v řídicí cestě. Monitoring má nahraditelný čekající snapshot.
Zámky cache/IPC chrání pouze krátké přesuny referencí, ne I/O.

## Paměť, persistence a pravdivost evidence

FIFO má 64 čekajících dávek, nejvýše 512 KiB na dávku; worker může mít navíc
jednu rozpracovanou dávku a feeder dočasnou serializovanou kopii.
Řídicí paměť zachovává posledních 24 událostí, dva vzorky a omezený startovní
stav relací. Staré skutečné záznamy se nemažou ani nepřepočítávají.
Není použita neomezená fronta ani slepé opakování celého regulačního kroku.

Zapisující worker potvrzuje dávku po trvalém commitu a přípravě outboxu.
Flush je FIFO a idempotentní podle runtime/seq; konfliktní immutable řádek
se odmítne, nepřepíše. Potvrzení recorderu je stále samostatný skutečný důkaz.
Při chybě zůstává právě zpracovávaná dávka k opakování a regulace pokračuje.
Zpoždění, smrt procesu, překročený diskový rozpočet a overflow jsou degraded.

Pokud dlouhá porucha zaplní omezenou frontu, nový přírůstek evidence se
nepředstírá jako uložený. Přibude počet ztracených dávek/událostí/vzorků,
časové meze a den. Relace dostane evidence_integrity=incomplete; následující
úspěšná dávka uchová kumulativní ztrátu. Závěrečný stav relace se po odmítnutí
znovu nabízí i bez další změny. Regulátor nezastaví kvůli ztrátě logu.

Pád celého zařízení může ztratit dosud neuloženou RAM frontu. Startup proto
označí otevřenou relaci jako unknown a zahodí předchozí lease; neobnovuje
neznámý výkon ani nedopočítává chybějící měření. Vyžaduje dvě nové celé sady.
Bez načtení známého startovního vlastnictví/modelu se žádný výkon nezahájí.
Starý nebo budoucí model se nepřenáší do jiného dne/časového rozhodnutí.

## Skutečné bezpečnostní poruchy zůstávají

Neplatné/zastaralé vstupy, cizí vlastník, fáze mimo konzistenci, návrat času,
konec okna, expirace a chyba samotné řídicí logiky nadále výkon odvolávají.
Souběžný výpadek sběru se nesmí ztratit v chybě evidence. Ack generace se
předává až po trvalém stopu/outboxu; fsync potvrzení probíhá mimo řídicí vlákno
a mimo zámek cache. Novější generaci starší ack nepotvrdí.

Linux/RPi a Python nejsou hard real-time systém. Oddělení procesů odstraní
čekání na tyto diskové/analytické operace, nikoli fyzikální záruku dostupnosti
CPU, RAM, napájení nebo zařízení. Akční adaptér a fyzický timeout stále chybí.

## Regrese a historie pokusů

Nové testy procházejí skutečný produkční entrypoint a run_loop, privátní RAM,
skutečný cizí SQLite zámek, spawn writer, následný přesný idempotentní flush,
saturaci, ztrátové značky, opakování závěrečného stavu, restart, budoucí model,
neblokující IPC a skutečné vstupní výpadky. Regulační smyčka je navíc spuštěna
s pastí na otevření souboru/diskové SQLite. Syntetika nevolá žádné HA služby.

Staré testy 0.6.13–0.6.19 používají výslovně historickou testovací smyčku
tests/historical_observer_0619.py. Uchovávají původní protipříklady, ale nejsou
vydávané za důkaz nové produkční architektury. Nový důkaz je samostatný
scripts/verify_control_isolation_0620.py.

První úplná regrese odhalila zacházení mimo existující persist testovací hook;
oprava hook zachovala a současně ponechala fsync mimo zámek cache.
Dílčí průchody a selhání jsou uchované, žádný neúspěch se nepřepisuje.
Jedno vzdálené vytvoření pomocného patch souboru selhalo interní chybou;
následný příkaz doložil, že soubor neexistoval. Až poté byl znovu vytvořen.
Kontrola odhalila také riziko částečného IPC čtení a ztrátu posledního
session delta po overflow; obojí je opravené a má regresi.

Host testy, nativní Docker build, nasazení, GitHub/CI a případná celá živá noc
jsou různé důkazy a potvrzují se odděleně v PR. Backend mění verzi na 0.6.20,
karta zůstává kompatibilní 0.6.17. Skutečná provozní data zůstávají na RPi.

Další ověření zachovalo i neúspěšný převod historických fixture importů (včetně lokálních importů a samostatných auditních skriptů). Dvě opakování skončila na těchto testovacích importecha bootstrapu historického skriptu; opravy nemění bezpečnostní aserce. Historická smyčka je nyní vždy výslovně oddělená. Host testy používají neplatný syntetický credential i při náhodně chybějícím mocku. Nové regrese navíc hlídají neměnnost uzavřených relací, omezenou RAM retenci a návrat času před starší archivní den. Při návratu času se neotevře historická relace, která není v RAM.

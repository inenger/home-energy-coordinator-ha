# 0.6.19 · koordinace SQLite zápisů a přesná diagnostika

Základ: f7d4a2aa60aeabf86b3ccabec63d6135c27778ff.
Pouze observe_only, bez změny tarifu, priorit, rezerv a fyzických zařízení.

## Co se opravuje

Rychlý regulátor, analytika a recorder publisher používají různá SQLite
spojení na stejný soubor. Samotný WAL/timeout nezajišťuje pořadí jejich
zápisů. Syntetická regrese skutečné kolize potvrdila riziko přerušení RAM
INSERT a následné bezpečné zastavení. Původní noční OperationalError neměla
uložený SQLite code/name/text, takže přesná historická příčina není zpětně
vydávaná za jistotu.

Nový sqlite_writes.Connection koordinuje zápisové kontexty, schema skripty
a samostatné DML pro stejné rozlišené DB cesty v jednom procesu.
Spojení s krátkým timeoutem (řídicí .25 s) mají před čekajícími běžnými
spojeními přednost. Aktivní transakce se násilně nepřerušuje.
Čekání má omezenou délku; transakce, rollback, commit a close uvolňují
koordinátor i při chybě. Běžné SELECTy mimo zápisový kontext zůstávají
souběžné. Původní SQLite timeout/WAL/FULL durability zůstávají.

Celý krátký RAM krok včetně schema/INSERT je koordinovaný. Původní reporty
a čas rozhodnutí se převezmou až po získání přístupu k zápisu, přímo
z neblokující kolektorové cache. Žádné síťové HTTP se nepřesouvá do
řídicího vlákna. Tím se blokující čekání nevydává za čerstvý report.

Komprese velkého SOC rozhodnutí a denní historie se připraví před
vstupem do zapisujícího kontextu. Výpočty, HTTP a běžná analytika
se neserializují jako celek; zámek není držen po celou životnost Store.

Koordinace je uvnitř procesu. Nezakrývá cizí nekooperující writer,
dlouhý blok, poškozený soubor ani I/O selhání. Tyto případy nadále
procházejí bezpečnou chybovou cestou a nemají omlazené vstupy/TTL.
Není přidáno slepé opakování celého rozhodnutí po částečném zápisu.

## Diagnostika

SQLite výjimka zachová skutečný sqlite_errorcode, sqlite_errorname a
omezenou původní hlášku v health a události uloženého selhání.
Lokální timeout koordinátoru má vlastní source=local_writer a nevymýšlí
si nativní SQLite kód. Sekundární chyba při zápisu stopu má vlastní
diagnostiku. Analytika a recorder transport zaznamenají rovněž SQLite
podrobnosti. Původní kind collection_failure zůstává kompatibilní;
storage_error.source odlišuje chybu úložiště od samotného kolektoru.
Skutečné provozní chybové zprávy zůstávají v privátním prostředí HA/RPi.

## Regrese a meze

Nové syntetické testy ověřují:
- skutečný lokální writer zahájený uprostřed RAM rozhodnutí přes celou
  main cestu; řídicí zápis dokončí přednostně a nevytvoří falešný stop;
- pořadí čekajícího regulátoru před background writerem;
- omezené čekání, rollback a uvolnění při výjimce;
- souběžné čtení během cizího zápisu ve WAL;
- skutečný vnější SQLite lock, nativní BUSY diagnostiku, stop/outbox/zotavení;
- zachování I/O výjimky jako selhání, nikoli úspěšného sběru;
- souběžný řídicí zápis během záměrně zablokované SOC komprese.

Původní phase/freshness/frame/failure-latch regrese zůstávají.
Karta se nemění. Celou živou noc nové verze, fyzický heartbeat,
Mode8 mapování a timeout ani ostrou ochranu jističe syntetika neověřuje.

Předchozí pokus skončil limitem automatické kontroly ještě před vytvořením
modulu; tato neprovedená akce se nevydává za dřívější opravu/nasazení.
Pokračování používá běžné schválené nástroje a uchovává místní historii.
Provozní MEMORY, raw data a soukromé hash manifesty se nezveřejňují.
Veřejně jsou kód, obecné poznatky a syntetické pokusy; GitHub/CI a nativní
nasazení se potvrzují odděleně v PR a soukromém dokončovacím protokolu.

Finální host kontroly: 473 shadow +164 legacy testů,9Node sad, původní main
a auditní kontrakty a test zabaleného Docker rozložení prošly. Vypnutá
koordinace ve srovnávacím syntetickém běhu selhává očekávaným způsobem;
se zapnutou koordinací všech7nových kontraktů projde. Vstupní soukromá data
se nepoužívají. Nativní build/deployment a živá noc se potvrzují zvlášť.

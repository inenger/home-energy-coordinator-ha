# Deník a SQLite · 0.6.25

## Prokázané mechanismy

MON-02: opakované úplné diagnostiky v recent_events/recent_samples mohou
překročit 14 000 B i po zlib/base64. Samostatný multipart deník přitom již
uchovává nezkrácené události. Chybový plán navíc opakoval celý control_journal.
Nová projekce platí pouze pro monitor řídicího deníku s platným formátem a
stream_id. Nevejde-li se původní monitor, zachová session/transport a ostatní
atributy, odebere celé duplicitní náhledové seznamy a výslovně uvede
preview_source=journal_transport a preview_omitted_counts. Nedělá zkrácené
objekty se stejnými ID. Neprokazuje recorder ACK před jeho skutečným načtením.
Pokud se nevejde ani projekce nebo stream chybí, původní explicitní overflow
archiv/retained=false/fallback zůstávají. Limit se nezvyšuje.

DB-02: journal_transport.enqueue držel lokální writer gate při čtení,
dekompresi podkladů, přípravě JSON a kompresi celé dávky. Synteticky
zablokovaná komprese způsobí WriterTimeout analytiky před načtením FIFO.
Příprava se přesouvá mimo writer; commit ověří všechny původní kurzory před
prvním vložením. Souběžné zastaralé enqueue vyvolá JournalQueueChanged a
nepotvrzená původní dávka se opakuje. Transakce drží outbox i nové kurzory
společně, selhání nevytvoří částečný postup. Pořadí, hash a původní časy
nezkrácených řádků se nemění. Malé kódování obálek při přidělení seq zůstává
uvnitř transakce; nejde o bezmezní real-time záruku.

DB-01 zůstává otevřený pro přesnou příčinu jednotlivých provozních čekání a
SQLITE_BUSY. Prokázaný mechanismus DB-02 se nesmí vydávat za důkaz původu
každé historické chyby. WriterTimeout nově uchovává název držícího vlákna,
délku držení a mez čekání. SQLite chyba zachovává vlastní kód/název/hlášku a
bezpečný typ operace. Diagnostika neukládá SQL ani hodnoty parametrů. Nulování
counterů, prodloužení timeoutu nebo ignorování I/O nejsou součást opravy.

## Regrese a původní neúspěchy

Vstupní veřejný základ: dokumentační PR29 nad runtime PR28 (0.6.24).
Testy jsou [test_monitor_sqlite_0625.py](../tests/test_monitor_sqlite_0625.py).
Nový kontrakt proti původnímu kódu selhal na PayloadOverflow a WriterTimeout.
První verze reproduktoru zpomalovala i malou inicializaci streamu; v2 cílí
přímo kompresi delta JSON s events a stejnou vadu reprodukuje. První oprava
prošla writer testem, ale chybový plán stále opakoval celý deník a monitor
test selhal. Oprava proto zahrnuje normal i failure publikaci přes stejnou
projekci plánu. Původní chybové výsledky nejsou nahrazené pozdějším PASS.

Sedm regresí kontroluje nezávislou FIFO analytiku během blokované komprese,
nezkrácený multipart detail při velkém preview, explicitní nesouvisející
overflow, souběžný kurzor a idempotentní retry, rollback po I/O, lokálního
držitele a skutečné externí SQLITE_BUSY. Syntetický příklad dále prochází
produkční Python publikací/SQLite outboxem a skutečným JS loaderem karty:

```sh
cd priority_shadow
JOURNAL_PROJECTION_FIXTURE=/tmp/journal-625.json python3 -m unittest discover -s tests -p test_monitor_sqlite_0625.py -v
JOURNAL_PROJECTION_FIXTURE=/tmp/journal-625.json node ../scripts/test_journal_transport.mjs
```

Původní karta se nemění; nejde o nový test scrollování v HA shellu.
CI spouští tuto návaznost i celé původní sady. Zelené regrese nejsou důkaz
nové celé noci, fyzického nabíjení, úplné nedostupnosti dalších DB zámků ani
instalace konkrétní verze. Původní koordinátor, aktuátory, tarify a vstupní
TTL se nemění. N06-02, MON-01 a fyzické blokátory zůstávají otevřené.

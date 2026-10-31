## 0.6.11 · konzistentní sběr a výsledek regulátoru

Rychlý HA snímek obsahuje hodnotu, jednotku, meze, kontext a původní report ze stejného State objektu. Komplexní prognózy mají omezené opakování a explicitní snapshot_race místo ztracené entity. Missing/unavailable se nevydává za chybu jednotky. SQLite kontrola ignoruje pouze neexistující dočasné sidecary; hlavní DB a ostatní I/O chyby zůstávají chybou. Log má bezpečně omezené místo výjimky. Přehled odděluje RAM regulátor, ideální alokaci a aktuální skutečnost; historie připojuje původní výsledek regulátoru bez přepisu dat. Pouze observe_only, žádný akční adaptér ani EEPROM zápisy.

## Ověření a meze

Testovat nejen helper, ale collector→controller→SQLite→outbox→UI. Reálný HA template se ověřuje i při souběžných změnách. Chybné jednotky a chybějící report se nadále odmítají, stejně jako aktivní cizí vlastník a neplatné časy. Opakování prognóz má pevný limit; nelze z něj vytvořit nekonečný retry.

Původní noci se nepřepisují. Přehled ideální alokace má vlastní význam a nemá být zaměněný za RAM regulátor; rozdíly ramp a blokování jsou očekávané a viditelné. Energie i SOC regulátoru jsou model, nikoli naměřené nabití. Fyzický protokol a timeout zůstávají neověřené.

Starší sběr0.5.4 je samostatný build context s vlastními testy; přebírá jen konkrétní malý monitorovací transport a SQLite helper, nikoli novější algoritmus priorit. Verze, soukromá záloha, přesný deployment a zachování všech původních dat se dokládají zvlášť naRPi.


## Frontend 0.6.11-r1 · rekonstrukce a živý běh stejného dne

Deník má výslovnou volbu zdroje pro každý den. Pokud existuje samostatný archiv,
výchozí zobrazení vybere rekonstrukci a původní živý běh zůstává dostupný.
Cache, ID událostí, vzorky a souhrn regulátoru se mezi zdroji nesmějí sloučit.
Nenačtený nebo neúplný archiv se nenahradí původním živým výsledkem. Ideální
srovnání rekonstrukce se bere ze stejného archivního výpočtu; tabulka původních
živých nocí zůstává výslovně označená. Python runtime se nemění ani nerestartuje.

Regrese: scripts/test_same_day_reconstruction.mjs testuje stejný den, kolidující
ID, obousměrné přepnutí, chybějící archiv a bezezměnové původní atributy.
Podmíněné časové údaje a doplněné kroky musí mít vlastní provenienci. Neimportovat
aktuální metadata jako historická a neintegrovat za konec okna jen proto, že
uzavírací krok dorazil později. Soukromé podklady a ověření recorderu zůstávají na RPi.

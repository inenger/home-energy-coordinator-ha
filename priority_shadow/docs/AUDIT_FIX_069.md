# 0.6.9 · opravy devíti nálezů auditu

Pouze observe_only, bez fyzického adaptéru, SolaX povelů a EEPROM zápisů.

## Řízení a bilance
Před prvním snapshotem i během relace musí být input0x100 a readback0x1A0 čerstvé Disabled (<15s). Chybějící/stará/rozporná hodnota blokuje převzetí. Podpis nové sady používá jen nutné fázové reporty SolaXu; všechny musí postoupit proti poslední přijaté sadě a splnit skew≤2s. EV report nové Modbus měření nenahrazuje. Dvě nové platné sady jsou nutné před převzetím/obnovou. Snížení známého limitu nezávisí na obnově lease; zvýšení ani obnovení platnosti není dovoleno nad starými daty.

Při chybě modulu deníku se provede stejná fail-closed cesta jako při chybě sběru: nulový modelový požadavek, událost v evidenci a failed health. Pokud selže samotný zápis diagnostiky, monitor ukáže samostatnou chybu. Fyzický adaptér neexistuje.

Previous allocation obsahuje stejný rampovaný výkon baterie, součet sítě a fázové proudy. Před vypršením logického povelu se poslední časový úsek integruje nejvýše do expiry/window_end; skutečná mezera>7.5s se nepřemosťuje. Nejde o ověřený hardwarový timeout.

Čerstvé číselné proudové reporty se uchovají i při odmítnutí P/U/I. Každá fáze má current_quality, statistiky oddělují neověřené snímky/chybějící proudové fáze. Hlášená vysoká hodnota není potichu odstraněna ani prohlášena za nezávisle potvrzený fyzický proud.

## Recorder a přenos
Každý emitovaný monitor projde byte rozpočtem14 000B. Větší atributy se zabalí bezztrátově jako zlib-json-v1 s SHA256 a délkou; žádné tiché ořezání seznamů. Příliš velký nekomprimovatelný obsah se před HTTP odmítne s viditelnou chybou, plná lokální evidence zůstává. Frontend i historický loader kontrolují délku/hash a rozbalují kompletní podklady. Chyba rozbalení je viditelná.

Živý deník navíc přidává přírůstky do vlastní trvalé SQLite fronty. Každý den má vlastní cursor řádků; pozdní návrat původní relace nezmění den. Obsah dávek se komprimuje a dělí do částí pod limitem. Výhradní síťový cíl workeru je nový monitor sensor.nocni_stinovy_denik_prirustky. Worker běží odděleně od regulace, posílá nejvýše32 in-flight částí a opakuje nepotvrzené pokusy. Každý pokus má odlišný monitorovací stav, aby i přesně stejná opakovaná část vyvolala state_changed.

HTTP200 neznamená potvrzení. Worker zpětně čte recorder a porovnává celý kanonický obsah části. Teprve potom uloží receipt a posune souvislý ack. Čas pro rozsah historie je původní HA last_updated, nikoli pozdější čas ověření. Timeout potvrzení a síťová chyba jsou degraded; globální monitor sběru tuto chybu přebírá. Žádná purge fronty/receipts ani původní evidence se neprovádí.

Frontend kontroluje integritu částí a úplnost počtu událostí/vzorků, rozlišuje čekání na recorder a chybu. Umí duplicity, jiné pořadí, doplnění chybějící části i výběr staršího dne. Běžné načítání je přírůstkové s překryvem; při potvrzené mezeře znovu načte rozsah. Stará historie a výslovné retrospektivní archivy mají zachovanou samostatnou cestu.

## Ověření a meze
Regrese pokrývají A01–A09 přes deník/model/publisher/main()/UI, restart, přenosovou chybu, potvrzení z recorderu, chybné hashe/velikosti, částečné snímky a pozdní předání jiného dne. Skutečný HA roundtrip prověřil vícedílný explicitně označený validační monitor a rozbalení velkých atributů. Testovací SQLite je oddělená od produkční.

Historicky chybějící last_reported ani nezaznamenaný readback nelze doplnit jako fakta. Nová revize zpětného deníku uvádí všechny své podmínky; starší archivy zůstávají. Fyzický VPP paket, mapováníA6/A7, AC/DC odezva a fail-safe timeout zůstávají neověřené. Tři celé skutečné stínové noci nenahrazuje rekonstrukce ani syntetické testy. Uložení atributů v recorderu také neověřuje fyzický heartbeat zařízení.

# Postup vydání, diagnostiky a obnovy

Tento postup nenahrazuje rozsah konkrétního zadání. Samotná editace
dokumentace nepotřebuje restart doplňku, nový runtime ani zásah do HA.

## Před opravou

1. Přečíst [AGENTS](../AGENTS.md), [aktuální stav](PROJECT_STATUS.md),
   [registr](KNOWN_ISSUES.md), MEMORY a konkrétní audit.
2. Oddělit původní koordinátor a stínový Docker context. Zjistit skutečný
   commit, veřejný tree, větev, runtime verzi a konfiguraci; stará poznámka
   v MEMORY není nové měření.
3. Zapsat hypotézu, vstupní commit a reprodukci. Zachovat původní FAIL i
   vyvrácenou hypotézu; příčinu neodvozovat jen z časové souvislosti.
4. Přidat protipříklad přes dotčenou produkční cestu a opačný bezpečnostní
   případ. Historický reproduktor očekávající vadu nepoužívat jako release gate.
5. U skutečných dat zachovat originál. Rekonstrukce má vlastní zdroj,
   verzi, předpoklady a místo uložení; není opravou původního měření.

## Ověření zdroje a publikace

1. Použít [mapu testů](TEST_MATRIX.md). Ověřit relevantní celek i povinné
   kontroly. Neobcházet FAIL opakováním až do zeleného výsledku.
2. Vyhodnotit chybu fixture/auditního helperu odděleně od chyby aplikace.
   Opravit helper, zachovat první výsledek a popsat změnu kritéria.
3. Aktualizovat registr, historii a současný rozcestník. Verzi/changelog
   měnit při změně balíčku; dokumentace mimo Docker context verzi nemění.
4. Veřejně publikovat kód, syntetické případy a obecné poučení. Soukromá
   databáze, seed, přístupové údaje a plné řady/logy zůstávají na RPi.
   Zamítnutý soukromý payload se nesmí odeslat jiným nástrojem.
5. Ověřit GitHub head/tree a CI. Před merge zkontrolovat rozsah zadání
   a dopad automatických aktualizací. Po merge ověřit obsah main a jeho CI.
   Nenechat výsledek označený „v main“, pokud existuje pouze PR.
6. Při automatickém zamítnutí zapsat akci/důvod a pokračovat neblokovanou
   prací. Vyžaduje-li blok konkrétní souhlas, žádat až nad hotovým výsledkem.
   Po novém souhlasu znovu ověřit head; neobcházet původní blok jinou cestou.

## Řízené nasazení na RPi

1. Potvrdit aktuální cílový doplněk, observe_only a skutečnou verzi.
   Nekopírovat privátní MEMORY/FIX_HISTORY větev do veřejného build contextu.
2. Uchovat source zálohu, konzistentní SQLite kopii a podporovanou native
   zálohu. Zaznamenat výchozí runtime, chráněné automatizace/kartu a stav
   původních doplňků. Nepoužívat tds-dev.
3. Zkontrolovat vhodný čas, dostupnou RAM/disk a rozsah autorizovaného
   přerušení. Kontroly se skutečnými daty a těžké testy dělat sériově.
4. Pro každou mutaci nejprve uložit jedinečný záznam žádosti, pak výsledek.
   Po timeoutu nejdřív zkontrolovat běžící operaci, stav a existující záznam;
   nikdy slepě neopakovat stop/update/backup/start.
5. Použít podporované Supervisor rozhraní. Nevypínat protection mode kvůli
   Docker CLI. Nekopírovat nový kód do původního koordinátoru.
6. Po instalaci vyčkat na novou runtime generaci a více čerstvých durable
   ACK. Zkontrolovat collection/storage/monitor/analytics health, backlog,
   loss, restartový stav, source shodu a zachování původních řádků.
   Stav entity „ok“ bez kontroly stáří není průkazný.
7. Selže-li update před novou běžící verzí, obnovit podporovanou předchozí
   službu podle uchovaného zdroje/image. Neobnovovat starou DB přes živou
   jen proto, aby se smazal chybový stav; nezatajovat další nutný zásah.

## Skutečná hot záloha a obnova

1. Vycházet z [kontraktu 0.6.24](../priority_shadow/docs/HOT_BACKUP_0624.md).
   Native archive musí obsahovat ověřený ZIP; source sentinel i staging
   musí být vyloučené. Raw SQLite má význam statické zálohy zastaveného app.
2. Během zálohy sledovat identitu hlavního runtime, started a postup ACK.
   Samotný úspěšný HTTP výsledek zálohy kontinuitu neprokazuje.
3. Obnovit obsah **do odděleného adresáře**. Ověřit manifest, SHA uvnitř
   archivu, integritu/FK a streaming porovnání tabulek se snímkem.
   Test obnovy nesmí přepsat živou DB ani měnit historii HA.
4. Rozlišit snímek potvrzené DB v čase manifestu od nepotvrzené RAM fronty
   a pozdějších commitů. Uvést RPO/časové meze; neslibovat nulové RPO.
5. Přímý quick_check portable kopie neoznačovat za přímý quick_check
   aktivního /data. Native restore test do izolace není destruktivní
   obnova celého Home Assistantu.

## Závěrečná zpráva

Uvést samostatně zdroj/CI, merge, nasazení, skutečně provedené ověření a
otevřené položky. Aktuální zdraví, historické retry a případná ztráta jsou
různé údaje; counter ani last_failure se nemažou.
Podrobné soukromé podklady uchovat na RPi. Veřejná zpráva obsahuje obecné
poučení a reprodukovatelný syntetický kontrakt, ne soukromý provozní payload.
Nevydávat počet testů za záruku 100% funkčnosti a neuzavírat N06-02 bez důkazu.

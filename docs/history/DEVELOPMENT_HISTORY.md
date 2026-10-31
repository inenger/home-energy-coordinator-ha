# Historie vývoje, chyb a slepých cest

Zapsáno 31. 10. 2026 na výslovný požadavek uživatele: celý dohledatelný vývoj včetně neúspěchů musí být zaznamenaný na GitHubu. Předchozí lokální commity včetně původních rodičů jsou uchované v přiloženém obnovitelném Git bundle, nikoli pouze v seznamu úspěšných změn. Staré závěry se neopravují přepsáním historie; doplňuje se jejich vyvrácení.

## Rozsah a hranice evidence

Tento záznam doplňuje [projektovou paměť](../../MEMORY.md), [historii oprav](../../priority_shadow/docs/FIX_HISTORY.md), jednotlivé verzované audity a regresní testy. Historické věty „veřejná publikace neprovedena“ popisují tehdejší stav a zůstávají zachované. Nejsou aktuálním stavem publikace tohoto dokumentu.

[Seznam původních commitů](local-commits-before-publication.txt) zachovává jednotlivé kroky 0.6.6–0.6.15. [Manifest reportů](evidence-reports.json) uvádí všechny nalezené přímé REPORT soubory pod recovery adresáři včetně původní chybné zprávy. SHA-256 identifikuje přesný původní dokument. Soukromé databáze, plné naměřené řady, konfigurace s tajemstvími a surové provozní odpovědi zůstávají na RPi. Manifest není záloha jejich obsahu na GitHubu.

Zpětně nelze zaručit zachycení každého neuloženého příkazu či myšlenky. Níže jsou doložené postupy, omyly a odmítnuté varianty; chybějící důkaz se nesmí domýšlet. Budoucí změny mají povinný průběžný záznam podle AGENTS.md.

## Doložené neúspěchy, chyby a změny závěru

| Období / případ | Původní postup nebo závěr | Proč neobstál / výsledek | Oprava a dohledatelná evidence |
|---|---|---|---|
| Analýza 24. 10. | Back Up Mode byl popsán jako provozní stav měniče. | Nastavovaná nabíjecí strategie a sensor.solax_run_mode jsou odlišné entity; závěr o provozním režimu byl odvolán. | Původní REPORT-original-before-run-mode-correction.md i opravený REPORT.md jsou v manifestu; MEMORY 0.6.3. |
| Plánování 0.6.2–0.6.3 | Vyžadovat celé dosažení žádoucího EV cíle před povolením jakéhokoli plánu baterie. | Nedosažitelný požadavek EV vyřadil veškeré porovnání a označení missing_forecast bylo zavádějící. Odmítnuté plány neukládaly úplný vstup. | Oddělené částečné splnění a původ vstupů i při zamítnutí; MEMORY 0.6.3 a testy. |
| Rozpočet 0.6.4–0.6.5 | Vydávat nižší SOC za čisté ekonomické optimum. | Kandidáty předem omezoval pevný proudový rozpočet a požadavek splnění ve stresovém scénáři. | Oddělení cíle, dosažitelnosti a okamžité alokace; MAX_FILL_065.md. Fyzická ochrana jističe tím není certifikovaná. |
| 0.6.6 | Souhrn závislý na pořadí dostupných fází a společné chybové cestě. | Chybějící fáze poškodila souhrn; chyba jedné noci mohla narušit další sběr. | Explicitní phase ID, izolace chyb, append-only revize; SUMMARY_066.md. |
| Publikace 0.6.6 | Lokální commit a nasazení bez dokončené veřejné publikace. | Tehdejší pokus odmítla automatická kontrola; následující verze zůstaly pouze na RPi. | Tento publikační úkol je nově výslovně autorizovaný. Oddělit GitHub, CI, merge a runtime. |
| Deník 0.6.7 | Výchozí history API a úplné monitory měly stačit pro historii. | Ořezané atributy a významové filtrování nezaručovaly historii změn při stejném state. | Plné atributy, significant_changes_only=0, samostatné přírůstky; CONTROL_JOURNAL_067.md. |
| Rekonstrukce 29. 10. | Držené recorder hodnoty použít jako důkaz čerstvého heartbeat. | Recorder změn nedokazuje opakované reporty. | Podmíněná rekonstrukce je oddělená od živé evidence; přísná varianta bez předpokladu vlastníka nepřevezme řízení. |
| Diagnostika P/UI 29. 10. | Obecné missing_inputs znamená chybějící měření. | Dostupné údaje mohly být rozporné. Horní P/UI rozpor nesmí být odstraněn kosmetickou změnou. | Konkrétní hodnoty a důvody; journal-audit-2026-10-29. Později samostatně přehodnocena dolní mez v 0.6.15. |
| Mode8 / RAM stín | Použít existující direct mapování jako ověřený fyzický timeout. | Význam A6/A7 a lokální Timeout mapování nejsou hardwarově potvrzené. | Fyzický adaptér nevytvořen, wire_command=null, pouze observe_only; RAM_CONTROL_068.md. |
| Audit 0.6.8 A01–A09 | 375 úspěšných testů a HTTP úspěch považovat za dostatečné. | Devět nálezů: příliš velké atributy; readback až po převzetí; EV report zaměněn za novou SolaX sadu; stáří vlastníka; neodvolaný intent po výjimce; chybná síťová energie rampy; skrytá odmítnutá fáze; neúplný loader; ztracený úsek před expirací. | AUDIT_FIX_069.md, FIX_HISTORY a test_audit_069.py; původní audit v manifestu. |
| Audit 0.6.9 B01–B03 | WebCrypto vždy dostupné; odmítnutý report může posunout watermark; JSON.stringify stačí na rovnost. | HTTP origin nemá crypto.subtle; budoucí čas blokoval zotavení; pořadí klíčů vyvolalo falešnou kolizi. | HTTP_CLOCK_0610.md, test_audit_0610.py a test_http_integrity.mjs. |
| Audit 0.6.9: vyvrácená hypotéza | Minutová prodleva při vstupu do nočního okna. | Reprodukce ji nepotvrdila: rychlá smyčka začíná už před 03:00. Chybný assert zůstal v původním control-probes.log, oprava ve final logu. | audit-069-2026-10-29/REPORT.md; nejde o potvrzený nález aplikace. |
| První noc 0.6.10 C01–C04 | Dva HA dotazy a vyřazení změněných řádků mají zajistit konzistenci. | Normální změny odstraňovaly metadata; SQLite WAL/SHM mohl zmizet mezi glob a stat; přehled ukazoval jiný model než deník; starý monitor překračoval limit. | CONSISTENT_SNAPSHOT_0611.md, 0.5.4 legacy opravy, test_night_fixes_0611.py. Přesné místo jediné historické výjimky není doloženo tracebackem. |
| Rekonstrukce 0.6.11 | Oprava sběru sama odstraní rozpad druhé hodiny. | Zůstaly falešné expirace lease při nesouhlasných periodách sběru/reportů. | Nová oddělená rekonstrukce 0.6.12; stará 0.6.11 zachována, žádné přepisování živé noci. |
| První kandidát 0.6.12 | Zablokovat obnovu při jakémkoli drobném návratu reportu. | Celý historický replay odhalil nefunkční variantu. Nebyla nasazena. | fix-0612/attempt-1, REPORT v manifestu; finální obnova omezená absolutní platností původních reportů; LEASE_RENEWAL_0612.md. |
| Frontend před 0.6.12-r1 | Nahrazovat celý shadow DOM, obnovovat scroll indexem tabulky a details podle CSS třídy. | Ztráta čteného místa, záměna offsetů, zbytečné rendery a stovky současných řádků. | Stabilní klíče, DOM/focus, cache, stránkování; SCROLL_0612_R1.md a Chromium regrese. |
| Audit 0.6.12 D01–D06 | Stabilní scroll a procházející původní testy znamenají hotovo. | Záměna proudů indexem; synchronní HTTP monitoring; ztráta potvrzení recorderu; graf přes stop; vadná integrita archivu; dva vlastníci po rollbacku. | AUDIT_0612_20261030.md, DEEP_FIXES_0613.md, zachované audit_deep_0612 skripty a nové testy. |
| Audit 0.6.13 A13-01–06 | Oprava RAM času pokryje všechny modely; stránkování už je rychlé. | Ideální model dvojmo integruje; failure ztrácí platnou energii; legacy vlastník se nedokončí; unknown nebrání exact_restore; stránkování blokuje; obnova limitovaná 14 relacemi. | AUDIT_0613_20261030.md, INDEPENDENT_FIXES_0614.md; původní i nové kontrakty zachovány. |
| Noc 0.6.14 | Pevná dolní P/UI mez 0.5 jako podmínka způsobilosti. | Odmítala dostupné údaje a přerušovala model. Dvě skutečné mezery mají neúplnou historickou diagnostiku. | NIGHT_FIXES_0615.md; konzervativní proudová mez, horní kontrola zůstala. Přesná příčina každé staré mezery není prokázána. |
| První kandidát 0.6.15 | Samostatný sběr se stejnou periodou 5 s odstraní problém. | Perioda 5 s aliasuje s přibližně 5.01 s zdrojových reportů a cache zbytečně zaostává. | Commit 8f0e160, deterministická regrese; worker 2.5 s bez vymyšlených report timestamps. |
| Navazující kandidát 0.6.15 | Oddělení HTTP samo vyřeší blokování celé smyčky. | SQLite ještě mohlo čekat 10 s; nezapsaný stop mohl později dostat nesprávný čas. | Commit 7afc43c; 250 ms busy timeout, původní pending failure timestamp i po restartu, skutečný lock a main-loop regrese. |
| Závěry o kvalitě obecně | „Vše opraveno“ z počtu zelených testů. | Následující audity opakovaně našly další celé neotestované cesty. | Každý závěr musí uvést přesný zdroj, rozsah, důkaz, omezení a zbývající ověření. |

## Ověřený stav před publikací

Runtime zdroj 7afc43c, dokumentační head 519f58c: na RPi nasazen shadow 0.6.15, legacy observer 0.5.4; frontend 0.6.14 beze změny. Doloženo 447 shadow a 164 legacy Python testů, Node regrese, původních 5+7 auditních kontraktů a osm cílených nových regresí. Všech 34 původně odmítnutých allocator snímků projde konzervativním modelem; není to přehrání celé nové noci.

Browser ověření pochází z 0.6.14 na testovací stránce se shadow scroll kontejnerem, nikoli z přihlášeného HA shellu. Nová úplná noc 0.6.15, fyzické Mode8 mapování/timeout, hardwarová ochrana jističe a realizované úspory nejsou ověřené. Původní skutečné noci a podmíněné rekonstrukce se nesmějí zaměňovat.

## Povinný záznam další práce

U každého pokusu zaznamenat problém/hypotézu, vstupní commit, reprodukci, výsledek včetně FAIL, důvod odmítnutí či přijetí, finální opravu a zbývající nejistotu. Neúspěšné pokusy nesquashovat pryč bez samostatné historie. Při práci se soukromými vstupy publikovat obecný postup, syntetický protipříklad a kontrolní otisk lokálního důkazu. GitHub větev a CI ověřit samostatně, poté zaznamenat merge a nasazení. Tajemství nikdy necommitovat.

## Obnova přesné původní Git historie

Přímý push z RPi nebyl možný: chybělo Git HTTPS přihlášení. Publikace přes GitHub konektor zachovává aktuální strom a přikládá `local-history-through-81b534e.bundle` s původními 28 commity, jejich metadaty, stromy a rodiči od veřejného e8ef9d3. Bundle vyžaduje původní základ, který je ve veřejném repozitáři. Nejde jen o textový export diffů. Nový publikační commit má vlastní SHA; nenahrazuje původní identitu nasazeného zdroje.

Po klonování repozitáře lze ověřit a importovat původní historii:

```sh
git bundle verify docs/history/local-history-through-81b534e.bundle
git fetch ./docs/history/local-history-through-81b534e.bundle HEAD:refs/heads/archive/rpi-through-0615
git log archive/rpi-through-0615
```

`bundle-metadata.json` uvádí SHA-256 archivu, původní head a předpokládaný základ. Kontrola před publikací prošla všechny unikátní bloby 27 původních nepublikovaných commitů na běžné formáty tajemství a zakázané datové soubory; nic nezachytila. Není to univerzální důkaz absence všech typů citlivých údajů.


## Navazující audit 31. 10. 2026
[Hloubkový audit 0.6.15](../../priority_shadow/docs/AUDIT_0615_20261031.md) uchovává tři nové nálezy, původní neúspěšný browser test i diagnostické opakování, nesprávný import root testů a opravené předpoklady porovnání build manifestu. Předchozí opravy nejsou přepsané; nový nález neznamená automatickou opravu.

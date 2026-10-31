# 0.6.14 · opravy nezávislého auditu A13-01–A13-06

Tato změna opravuje nové protipříklady z AUDIT_0613_20261030.md. Původní
nálezy a důkazy zůstávají zachované. Fyzické řízení se nezapíná.

## Čas a energie

Ideální model má monotónní watermark. Duplicitní čas nemění model, referenci,
čítač ani uložené řádky. Zpětný čas nezaloží starší relaci, neúčtuje energii,
vykazuje clock_rollback a přeruší předchozí návaznost. Po návratu nad původní
čas založí nový interval; nejistá mezera se nedopočítává. Stejný kontrakt
přežívá restart a platí i při vytvoření souhrnu. Již uzavřený souhrn se
nepřepisuje; staré chybné souhrny by vyžadovaly samostatnou explicitní revizi.

Při record_failure se před stopem účtuje pouze poslední krátký platný úsek:
nejvýše do min(stop, původní expiry, konec okna). Nadále platí maximální
pozorovaná mezera7.5s. Dlouhý výpadek se neúčtuje, opakovaný stop nepřidá
další energii. Jde o modelovou W AC energii, nikoli uskutečněné nabíjení.

## Předání a obnova

Nový observer umí výhradně dokončit otevřený starý virtuální deník. Nevolá
staré observe a neobnovuje jeho nabíjení. Uloží zastavení/předání skutečným
časem, zachová původní verzi/snapshot/události a čeká při neznámých stavech
či návratu hodin. Teprve uzavřený starý vlastník dovolí novou RAM relaci,
která nadále vyžaduje dvě nové platné sady. Přehled tohoto předání má vlastní
legacy_handoffs v monitoru a oddělené rozbalení v kartě.

Chybějící skutečný stav se ověřuje i u virtuálně nezměněných parametrů.
Neznámý údaj není Beze změny ani exact_restore=true. Zotavení znovu ověří
aktuální stav. Konflikty s jiným vlastníkem se nepřepisují. Obnova i
record_failure procházejí všechny otevřené relace; limit14je pouze prezentační.

## Odezva deníku

Přepnutí stránky mění pouze seznam a jeho ovládání. Nepřekresluje graf ani
ostatní panely. Současně je v DOM nejvýše20událostí; všechny události jsou
přístupné po stránkách a všechny grafové vzorky zůstávají uložené. Explicitní
přepnutí stránky začíná nahoře bez synchronního resetu staré odscrollované
velké tabulky. Průběžné HA aktualizace nadále zachovávají čtený kontejner,
focus, samostatná details a vnější scroll. Vodorovná pozice je zachovávaná.

Řádky mají pevné sloupce přes CSS grid a oddělený layout scroll kontejneru.
Dlouhý důvod má stručný náhled; úplný text i JSON podklady se bezztrátově
vytvoří až při otevření dané události. Detail má klíč dne/zdroje/ID, takže
přepnutí rekonstrukce/živý záznam nesdílí již dekódované detaily kolidujícíchID.
Při malém stránkování se zneplatní odpovídající HTML cache; další plný refresh
nesmí vrátit jinou stránku nebo přeskočit aktualizaci DOM.

## Regrese a meze

- test_independent_fixes_0614.py: rollback/duplicity/restart/souhrn/uzavřená
  evidence, energie do stop/expiry/okna/mezery a monitor/transport, předání
  při chybějícím údaji, upgrade starého vlastníka a obnova mimo14položek.
- scripts/audit_independent_0613.py: původní syntetické protipříklady se
  opakují bez změny původních důkazů; nyní musí vykázat contract_met=true.
- scripts/test_independent_fixes_0614.mjs: pravdivé předání, escapování,
  kompletní lazy podklady, izolace zdrojů a20řádkový výběr.
- test_card_scroll_browser.mjs: Chromium, obě šířky, geometrie/wheel/focus,
  všechny stránky a časový limit100ms pro jednotlivý přechod včetně vynucení
  layoutu. Jednotlivé uživatelské kroky jsou oddělené vykreslenými snímky.

Soukromé měření nad úplnou skutečnou nocí patří pouze naRPi. Samotné Node
ověření není vizuální prohlížeč a browserová fixture není přihlášenýHA shell.
Před nasazením a po něm se zvlášť ověřují HTTP artefakt, archivní checksumy,
recorder, zdroje, ochranné soubory a původní řádky DB. Žádný výsledek těchto
testů není zárukou60FPSkaždého klienta nebo fyzické odezvy měniče.

Rekonstrukce0.6.12 zachovává vlastní provenienci a původní evidence se
nepřeznačuje na0.6.14. Novou celou skutečnou noc a hardware je nutné ověřit
samostatně. Lokální commit, veřejná publikace a nasazení jsou oddělené kroky.

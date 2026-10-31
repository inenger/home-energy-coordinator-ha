# Historie chyb a regresní důkazy

## 0.6.1: opravy prvního SOC auditu

| Oblast | Pravidlo | Regrese |
|---|---|---|
| Teplota | Holdout používá tehdy dostupnou předpověď | `test_soc_fixes.py` F01 |
| EV | Nulový nebo fyzicky přípustný proud v každém úseku | F02 |
| DC port | Jeden součet nabíjení ze sítě a PV | F03 |
| Návrh | Novější neplatný návrh odvolá starý; TTL a restart | F04 |
| Limity | Nabíjení a vybíjení mají vlastní vstupy | F05 |
| PV | Integrace předpovědi na stejných měřených intervalech | F06 |
| Hash | Hash plného payloadu bez samotného hashe, až po metadatech | F07 |
| Čas SOC | Výchozí bod a koncový čas energie | F08 |

## 0.6.2: opravy následného auditu

| ID | Poučení | Regrese v `tests/test_soc_fixes_062.py` |
|---|---|---|
| N01 | Osiřelá stará relace nesmí obejít povinný nový plán | `SessionRecovery` |
| N02 | Po mezeře se nesmí znovu připojit předchozí vzorek | `EVContinuity` |
| N03 | Konzervativní fázový rozpočet není nákupní AC bilance | `ACBalance` |
| N04 | AC výstup měniče sdílí PV a vybíjení | `ACBalance` |
| N05 | Replay a review potřebují stejné brány; společné intervaly | `ReviewValidity` |
| N06 | DST ověřovat přes celou review cestu, nejen pomocnou funkci | `ReviewValidity` |
| N07 | Neznámá PV metadata nesmí zahodit platný profil domu | `IndependentQuality` |

Původní tvrzení „vše opraveno“ bylo po prvním průchodu příliš široké.
Od nynějška uvádět rozsah důkazu: jednotkové testy, nezávislé sondy,
provozní kontrola a dosud neověřené fyzické předpoklady. Nový nalezený
protipříklad rozšiřuje regresní sadu; historické důkazy se nepřepisují.

Privátní auditní zprávy, logy, seed a časové řady zůstávají na RPi.
Veřejné příklady a testy nesmějí obsahovat kopie naměřených řad.

## 0.6.3: nedosažitelný EV cíl a význam stavů

Regrese jsou v `tests/test_partial_063.py` a `scripts/test_partial_card.mjs`.

- Žádoucí EV cíl není potvrzené minimum do odjezdu. Nedosažitelný cíl
  vytváří výslovně částečný plán a uchovává deficit, nikoli falešný úspěch.
- Obě priority mají vlastní cíle, stejné limity a výslovně přiznanou různou
  službu autu. Částečná relace musí projít stejnými branami jako úplná.
- Zamítnuté rozhodnutí uchovává vstupy; snapshot se nesmí měnit po výpočtu.
- Provozní `sensor.solax_run_mode` a volba `select.solax_charger_use_mode`
  jsou samostatné údaje. Jejich rozdíl sám neprokazuje závadu či zastaralost.
- Přítomná předpověď s odmítnutým plánem není missing_forecast. Bez platného
  modelového pokrytí nepublikovat nulové energie ani výchozí SOC jako výsledek.
- Staré důkazy zůstávají zachované; opravený diagnostický pohled na historický
  souhrn uchovává i jeho původní diagnostický kontext.

## 0.6.4 · výkon a nedosažený cíl

Pevný limit 22 A × účiník 0,9 snižoval rozpočet a přísné odmítnutí cíle
v jediném scénáři zaměňovalo nedosažitelnost požadavku za ekonomickou
nevýhodnost. Nový odhad po fázích má zdrojové období a explicitní fallback;
vyšší cíle zůstávají v porovnání s dosaženým SOC a skutečně modelovanými
náklady. `tests/test_phase_064.py` ověřuje časovou kauzalitu, chybějící
a rozporné proudy, rezervy, nejslabší fázi, zbytek výkonu po EV, zachování
cíle s deficitem, průchod do view a letní vynechání nabíjení. Renderer
ověřuje rozdíl cíl/výsledek i zobrazení fázových rezerv.


## 0.6.5
- Ekonomické odmítnutí neblokuje alokaci: test_full_observer_path_without_soc_plan.
- Proudové vstupy, slabá fáze, minimum EV, DC/AC limity a bilance: test_instant_fill.
- Opožděný DST reset: test_calendar_reset_preserves_prefix a test_sparse_night_counters_dst.
- Oddělení deficitů a kvantování: test_deficit_dictionary a test_rounding_regression.


## 0.6.6 · Neúplné fáze při dokončení noci

Reprodukce: observe uloží řádek bez L1 nebo s prázdným phase; finish dříve indexoval phase[i-1], čímž zaměnil fáze nebo vyvolal IndexError. Opakovaný catch-up před další alokací pak blokoval i novou noc. Regrese v test_summary_066.py ověřují skutečnou cestu přes SQLite, restart a publisher, zachování starých souhrnů i pokračování po izolované chybě. Karta má test chybového stavu, posledního úspěchu a skrytí starých výkonů bez mutace atributů HA.


## 0.6.7 · Deník celé řídicí relace

Změny modelových W samy nejsou příkazy do registrů ani přehled vlastnictví automatizací. Nový samostatný deník ukládá snapshot a virtuální stav, zaokrouhluje A DC na krok registru a odděluje skutečně pozorované hodnoty. Testy chrání především idempotenci, původně vypnuté automatiky, cizí změny, čekající obnovu a výpadek před05:00. Karta se nespoléhá jen na posledních24událostí: přírůstkově načítá recorder a deduplikuje ID. Fyzické chování a nový dopad na tepelnou zátěž zůstávají neověřené.


## Frontend0.6.7-r2 · konkrétní diagnostika deníku
Provozní stav nebyl v přehledu deníku výslovně oddělen od nastavované strategie, přestože jde o různé entity. Obecný důvod invalid_charge_inputs ztrácel rozdíl mezi chyběním a rozporem. Karta přidává provozní kontext, přesné entity a auditní podklady. Kontrola fáze se neobchází. Syntetická regrese přes alokaci/deník/stop/obnovu a Node testy popisků a evidence; původní archiv zachován jako předchozí revize. Runtime nezměněn.


## 0.6.8 · bezpečný stínový kontrakt paměti a času
Předchozí deník virtuálně přepisoval běžný proudový registr a neměl explicitní run_mode bránu. Nový samostatný výkonový deník takové zápisy nepřipouští. Odděluje dočasný logický požadavek od neověřeného VPP paketu. Výpadek či rozpor znamená0W a přerušení integrace; obnovu vyžadují dva nové souvislé snímky. Pomalé výpočty již nejsou ve stejné smyčce. Testy pokrývají i restart a předání, neověřují reakci hardwaru.


### Frontend0.6.8-r1 · zdrojová verze archivního deníku
Banner zpětné rekonstrukce měl pevné označení0.6.7 i pro novou politiku. Nyní čte escapované provenance.software_version, při chybějícím údaji zachovává0.6.7. Test scripts/test_partial_card.mjs ověřuje novou verzi, legacy fallback a escapování přes controlPanel; skutečný archiv je ověřen přes recorder a loader. Nejde o změnu runtime politiky ani fyzického řízení.


## Audit 0.6.8 · 29. 10. 2026 · neopravené nálezy
Hloubkový audit přesného lokálního11835fb odhalil mezery přes úspěšných375 testů. Reprodukováno: nadlimitní monitorovací atributy a chybějící kontrola úplnosti živé historie; opožděná kontrola aktivního readbacku při prvním převzetí; společný podpis EV/SolaX dovoluje růst nad stejnými fázovými reporty; chybějící TTL vzdáleného vlastníka; vnitřní výjimka deníku neodvolá uložený intent a sběr zůstáváok; grid energie zůstává ideální při rampované baterii; vyřazené fáze mizí z proudových statistik; poslední úsek lease se při expiraci nezapočítá. Osm nových kontraktů na zmrazeném zdroji selhává, UI má další protipříklad. Recorder limit ověřen vHA2026.10.4 a skutečném provozním logu. Nejde o vydanou opravu. Runtime0.6.8/0.5.3 a archiv zůstaly beze změny, žádné fyzické povely ani veřejná publikace. Před ostrým řízením opravit a ověřit celé návaznosti. Audit samotný nemění runtime verzi.


## 0.6.9 · opravy auditu
Implementovány A01–A09. Nové owner_errors vyžaduje čerstvé Disabled z0x100 i0x1A0, dvě celé nové sady fázových hlášení SolaXu nezávislé naEV. Výjimka deníku vede do nulového intent/failed health; bilance sítě se shoduje s rampou a platným úsekem lease. Raw proudy mají samostatnou kvalitu. Monitorovací byte budget14k používá bezztrátové zlib JSON/SHA, ne tichý ořez. Trvalý journal_transport má per-day cursor, multipart, skutečné recorder receipts, opakování a oddělený worker; potvrzovací čas pro historii je HA timestamp. Frontend ověřuje hash/velikost/počty a rozbaluje nové i staré cesty. Nepotvrzené části zůstávají vSQLite, fyzické řízení stálefalse. Soukromé doklady naRPi. Stav nasazení a finální kontroly ověřit podle soukromého completion; tento záznam sám nepotvrzuje nasazení ani publikaci.


## Opakovaný audit0.6.9 · neopravené B01–B03
394 testů znovuOK,3 nové kontrakty selhaly: B01 HTTP frontend nemá SecureContext-only crypto.subtle, B02 odmítnuté budoucí časové razítko přesto posune accepted_solax_reports a blokuje obnovu, B03 jiné pořadí JSON klíčů vyvolá falešnou kolizi části. Jde o nové neopravené nálezy. Runtime zůstal0.6.9/observe_only, žádný restart ani fyzický povel.64 skutečných monitorovacích řádků je kompletních a podlimitem; to neověřuje HTTP browser. Podezření na minutový skluz03:00 se nepotvrdilo díky5s smyčce již od02:55. Podrobná soukromá evidence naRPi v/share/hec-recovery/audit-069-2026-10-29/REPORT.md. Audit runtime verzi nemění a veřejnou publikaci neprovádí.


## 0.6.10 · HTTP, časové reference a JSON části

Opraveny B01–B03: SHA-256 s ověřeným fallbackem i bez crypto.subtle, sémantické porovnání částí nezávislé na pořadí objektových klíčů a reference pouze z přijatých časově platných snímků. Neplatná reference starší verze se odvolá; návrat vyžaduje dva nové platné snímky. Bez fyzického adaptéru a EEPROM zápisů. Viz docs/HTTP_CLOCK_0610.md. Soukromé doklady zůstávají na RPi, veřejná publikace neprovedena.


## Ověřené lokální dokončení 0.6.10 · 29. 10. 2026
B01–B03 opraveny a nasazeny na RPi. Kód304d4c3, záloha fd7e06d5, soukromé důkazy /share/hec-recovery/fix-0610.399 Python testů a tři původní auditní kontrakty prošly; SHA vektory/náhodné délky do2MiB, transport HTTP/HTTPS a renderer prošly. Nasazený JS načtený skutečným HTTP má shodný hash a v Node VM bez crypto.subtle rozbalí oba skutečné velké monitory i původní archiv455/1440. Jde o ověření dat a schopností, nikoli vizuální test skutečným browserem. Runtime0.6.10 started/observe_only, původní0.5.3 zachován, healthok; baseline měření/modely/deník a konfigurace zachované, quick_checkok. Cache weather_attempts smí přirozeně obnovit čas dotazu; původní hodnota zůstává v záloze. Nové kompletní monitorovací řádky recorderu pod14kB, bez nových oversize varování. Archiv zůstává výpočtem0.6.9; žádná nová rekonstrukce ani testovací produkční RAM/outbox data. Fyzické řízenífalse,0povelů/EEPROMzápisů; veřejná publikace neprovedena. Skutečné noční chování a hardwarové mapování/timeout nadále vyžadují budoucí ověření.


## Audit noci 30.10.2026 · runtime0.6.10 beze změny
Potvrzené C01–C04: dvoukrokový REST/template join bez retry vyřazuje normálně aktualizované entity a missing chybně označí unit_mismatch; glob/stat nad SQLite sidecary má TOCTOU FileNotFoundError; přehled ideální alokace nedoplňuje odlišný souhrn RAM regulátoru; starší teplotní monitor překračuje recorder limit a ztrácí atributy. Noční FileNotFoundError i race jsou doložené odděleně; přesný stack noční výjimky není v logu.399 baseline testů OK,3 nové Python kontrakty FAIL, cílený UI a starší teplotní datový kontrakt FAIL. Recorder nového deníku je bezztrátový a shodný seSQLite; nesměšovat se starým teplotním monitorem. Zmrazené zdroje, podrobné soukromé podklady a REPORT.md naRPi v/share/hec-recovery/audit-night-2026-10-30. Žádná oprava/restart/změna automatizací/řízení/purge/publikace; runtime stále0.6.10 observe_only. Přechod na ostré řízení není ověřen. Verze se dokumentačním auditem nemění.


## 0.6.11 · konzistentní sběr a výsledek regulátoru

Rychlý HA snímek obsahuje hodnotu, jednotku, meze, kontext a původní report ze stejného State objektu. Komplexní prognózy mají omezené opakování a explicitní snapshot_race místo ztracené entity. Missing/unavailable se nevydává za chybu jednotky. SQLite kontrola ignoruje pouze neexistující dočasné sidecary; hlavní DB a ostatní I/O chyby zůstávají chybou. Log má bezpečně omezené místo výjimky. Přehled odděluje RAM regulátor, ideální alokaci a aktuální skutečnost; historie připojuje původní výsledek regulátoru bez přepisu dat. Pouze observe_only, žádný akční adaptér ani EEPROM zápisy.

Připravená oprava; nasazení a finální ověření se evidují samostatně. Soukromé podklady zůstávají naRPi.


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


## 0.6.12 · obnova výkonu v mezích původní čerstvosti

Při asynchronním 5s sběru mohl opakovaný čerstvý snímek ponechat desetisekundový
intent bez obnovy. Následující nová sada pak dorazila o milisekundy po expiraci
a vyvolala zbytečné zastavení a novou rampu. Politika volatile-power-shadow-v2
odděluje zvýšení výkonu od držení: dvě nové celé sady jsou nadále podmínkou
převzetí/obnovy a pouze nová celá sada dovoluje zvýšení. Stále platná lease může
být obnovena na stejný či nižší výkon při úplných validních vstupech. Opakovaný snímek se nestává novým reportem ani good frame.

Platnost každého nenulového intentu je minimum z času vydání +10s, původních
deadline všech požadovaných rychlých vstupů, napětí/limitu/SOC baterie, stavu
měniče, obou vlastníků a konce nočního okna. Neprodlužují se reporty ani jejich
povolené stáří. Opakovaná data tedy nemohou výkon udržovat neomezeně. Skutečná
expirace, neplatné vstupy, cizí vlastník, výpadek sběru a mezera rychlé smyčky
nadále zastavují s nutností dvou nových sad. Integrace energie končí na skutečné
deadline; žádná mezera se neúčtuje jako nabíjení.

Vzorek ukládá intent_expires_at, input_valid_until a způsob obnovy. Událost
would_renew je v kartě označená jako podržení výkonu bez zvýšení. Původní živá
evidence a předchozí rekonstrukce zůstávají zachované; nový výpočet má vlastní
archiv a provenienci. Historicky nedoložené heartbeat časy zůstávají výslovným
předpokladem, nikoli změřenou skutečností.

Regrese: test_lease_0612.py pokrývá asynchronní celou noc, restart SQLite,
nezávislou integraci energie, souhrn a bezztrátový outbox; samostatně duplicity,
absolutní stáří, rollback, neplatné vstupy, skutečnou expiraci a výpadek.
Původní testy ukončení po pevných10s bez nových snímků jsou aktualizované
na nezměněnou15s mez čerstvosti zdroje. Privátní opakování původních pěti
selhání i dnešní noci běží jen na RPi. Fyzický adaptér a hardwarový timeout
nejsou touto opravou ověřené; observe_only zůstává zachované.


## Frontend0.6.12-r1 · stabilní čtení a stránkování deníku

Karta při každém HA hlášení nahrazovala celý shadow DOM, obnovovala scroll
podle indexu tabulky a otevření details podle společné CSS třídy. Doplnění
jiné tabulky tak přeneslo offset jinam a rozbalení jedné capacity otevřelo
i ostatní. Zobrazení celé relace současně vytvářelo stovky řádků; dekódovaný
monitor navíc dostával novou objektovou identitu i při nesouvisejícím HA
hlášení. Časovač i výškový ResizeObserver vyvolávaly další zbytečnou práci.

Nově se mění obsah stávajících DOM prvků podle stabilních klíčů. Zaniklé
prvky se odstraňují před vložením nových, aby nová výstraha nepřesouvala
všechny další panely. Zachovávají se jednotlivá details, focus, horizontální
offset, čtený řádek i vnější HA scroll. Při doplnění obsahu nad čteným místem
se kompenzuje pouze skutečná změna jeho polohy. Scroll tabulky se nesmí
kompenzovat o pohyb celé tabulky na stránce.

Deník uchovává všechny načtené události/vzorky, ale současně vykreslí nejvýše
50 událostí. Celý deník je dostupný po stránkách. Nové živé události neposunou
rozečtené okno; zobrazí se po výslovném kliknutí na tlačítko nových událostí.
Uzavřený kompletní stream se znovu nestahuje bez změny očekávaných počtů
nebo výslovného reloadu. Neúplné a aktivní streamy mají původní obnovu dat.

Dekódované State wrappery mají při stejném zdrojovém State stabilní identitu.
Externí změny se slučují do animation frame, stejné fragmenty se nepřekreslují
a formáty Intl se používají opakovaně. ResizeObserver reaguje jen na změnu
šířky; grafy mají vyhrazenou výšku.

Regrese: scripts/test_card_updates.mjs (identita, cache, explicitní reload,
úplnost všech stránek a stabilní živé okno) a test_card_scroll_browser.mjs
(skutečný Chromium, dvě šířky, načtení obsahu, geometrie, wheel, focus,
details a všechny události). Browser test přijímá PUPPETEER_MODULE_PATH,
CHROMIUM_PATH, CARD_SOURCE, CARD_FIXTURE a CARD_BROWSER_RESULT. Skutečná
data se předávají pouze na RPi; výchozí data jsou syntetická. Browser běží
na testovací stránce s vnořeným shadow scroll kontejnerem; není to přihlášený
HA shell. Načítání skutečného HA recorderu se ověřuje samostatně.

Jde pouze o frontendovou revizi. Backend0.6.12 ani observer0.5.4 se nemění
a nerestartují. Archivní manifesty a původní data se nepřepisují. Fyzický
adaptér zůstává vypnutý. Soukromá evidence v recovery adresáři na RPi.


## Hloubkový audit0.6.12 / frontend0.6.12-r1 · 30.10.2026 · otevřené nálezy
Audit přesného1494f78 odpovídajícíhoRPi potvrdil D01–D06:
P1 chybné indexové mapování proudů vUI; P1 synchronní monitoring blokuje
rychlou smyčku a uniká její metrice; P1 klouzavé časové okno ztratí potvrzení
při recorder commit zpoždění nad resend intervalem; P2 graf prodlužuje
požadavek za explicitnístop; P2 archiv přijme neplatné indexy/konfliktní
duplicity jako kompletní; P2 návrat hodin přes datum dovolí dalšího vlastníka.
Sedm nových kontraktů tyto chyby reprodukovalo přes dotčené celé cesty.
419+164 původních Python testů a Node regrese prošly; dalších1200 vzorků
ověřilo nezávislou energii, deadline a modelové fáze. UI mapování i graf
potvrdilChromium s RPi daty na testové stránce, nikoli přihlášenémHA shellu.
Reprodukce: scripts/audit_deep_0612.{py,mjs} s ENERGY_AUDIT_OUTPUT.
Soukromý REPORT a důkazy /share/hec-recovery/audit-0612-2026-10-30.
Audit runtime neopravuje ani nemění verzi; provozní zdroje/restarty/zařízení
beze změny. Livehealthok nepopírá chyby za reprodukovaných podmínek.
Žádná veřejná publikace ani fyzické povely/EEPROM.


## 0.6.13 · opravy D01–D06

D01: čtyři proudové údaje karty mají konkrétní pojmenované entity, jednotky
a timestampy. Seznam entit pro sledování změn neurčuje jejich význam.

D02: monitoring běží v samostatném vlákně. Čistá příprava ověřuje allowlist
a byte budget ještě ve fail-closed cestě; nahraditelná fronta drží nejvýše
poslední čekající snapshot každé entity a zachovává férové pořadí. Trvalý
deník má svůj původníSQLite outbox. Jednotlivé chyby monitorů drží degraded
do úspěchu dané entity. HTTP latence/počty/stav mají samostatnou metriku;
rychlá smyčka nevykonává HTTP publikaci ani v chybové větvi. Výpadek sběru
stále okamžitě odvolá uložený intent a prioritně zařadí nulové/unknown monitory.
Nejde o fyzickou real-time záruku; akční adaptér stále chybí.

D03: potvrzení recorderu se hledá od prvního možného přijetí s trvalým
cyklickým kurzorem a omezeným120s dotazem. Prohledávání se vrací ke starším
časům, zahrne pozdější retry a přežije restart i návrat hodin. Resend nemění
první mez. HTTP200 samotné nic nepotvrdí; bez skutečné shody recorderu
zůstává část v trvalé frontě a při dlouhém čekání je transport degraded.

D04: modelový graf zohledňuje explicitní stop i intent_expires_at; nenulový
požadavek nesmí přemostit odvolání nebo konec platnosti. Nejisté mezery se
oddělují. Skutečný měřený proud a trvalý proudový limit mají vlastní série
a virtuálním stopem se nemění.

D05: přesné indexy0..N−1, souhlas metadata a odmítnutí konfliktních duplicit
událostí/vzorků/session/částí. Přesná opakování a jiné pořadíJSON klíčů
zůstávají přípustné. Neúplný či vadný archiv neposkytne controllerSession
a nespadne do živého fallbacku. content_sha256 váže celý kanonický obsah:
{session, events seřazené numericky podleid, samples podle textovéhoat};
rekurzivně seřazené klíče, JSON.stringify, UTF-8, SHA-256. U starých
manifestů bez otisku je zachovaná pouze strukturální kompatibilita; nové
rekonstrukce musí mít otisk. Nasazené archivy je třeba ověřit z recorderu
a doplnit jejich manifestům checksum, bez přepisu původních řádků/provenience.

D06: vlastníka blokuje každá jiná otevřená relace bez ohledu na pořadí dat.
Návrat času pod last_processed_at odvolá výkon, zruší návaznost integrace
a čeká do dohánění původního času. Poté vyžaduje dvě nové platné sady.
Původní model/history se nezpětně nedatují a žádný interval se neintegruje dvakrát.

Regrese: test_deep_fixes_0613.py (skutečná souběžnost, Store, observer,
fronta, zpožděný recorder/restart/pozdní retry/časový návrat) a
scripts/test_deep_fixes_0613.mjs (čtyři různé proudy, grafstop/TTL,
indexy/konflikty/integrita a zamezení částečného modelu). Původní auditní
skripty jsou opakovatelným srovnáním; staré důkazy zůstávají zachované.
Starší test návratu hodin je zesílen na čekání do monotónního času.

Připravená oprava; nasazení a skutečný recorder/browser se ověřují samostatně.
Režim observe_only, žádné změny starých automatizací, priorit či tarifů.
Žádný akční adaptér, fyzický povel nebo EEPROM zápis.


## Audit0.6.13 · 30.10.2026 · otevřené A13-01–A13-06
Nové protipříklady odhalily překryv času/duplicitní čítač ideálního modelu,
ztrátu posledního platného úseku při výpadku, nedokončitelného starého vlastníka,
falešné přesné předání při neznámém skutečném stavu a zbývající dlouhé UI úlohy.
P3: starší otevřený řádek po importu mimo14položek se neobnoví. Viz
AUDIT_0613_20261030.md a scripts/audit_independent_0613.py. Nejde o opravu
runtime ani přepis předchozích výsledků; 0.6.13 a původní evidence beze změny.


## 0.6.14 · A13-01–A13-06
Monotónní idempotentní ideální model a souhrn; platný krátký úsek před failure
stop; dokončení původního vlastníka bez nového legacy nabíjení; neznámé
nezměněné stavy neznamenají přesné předání; všechny otevřené relace se obnovují.
Seznam deníku má vlastní20řádkový update, oddělený layout a lazy podklady.
Nové test_independent_fixes_0614.py/.mjs a časový browser kontrakt doplňují
původní zachované auditní reprodukce. Podrobnosti INDEPENDENT_FIXES_0614.md.
Režim observe_only; runtime oprava není přepis historických modelů ani úspora.


## 0.6.15 · noc31.10.2026
Pevná dolní mez P/UI0.5 odmítala34dostupných měření. Pro nízký poměr nyní
platí původní konzervativní trojúhelníková proudová mez, nikoli domyšlený
účiník nebo chybějící proud. Horní kontrola P/UI1.05 a čerstvost zůstávají.
Modelový proud zahrnuje proudový offset i v RAM deníku. Základ nad rozpočtem
zablokuje alokaci. Není to fyzicky certifikovaná ochrana jističe.

Síťový sběr běží v samostatném workeru každých2.5s (proti aliasingu s5sHAreporty). Řídicí smyčka čte kopii
snímku s původními HA reporty; nevytváří nový heartbeat. Starší než7.5s nebo
explicitně selhaný snímek je odmítnut, platí stop a původní dvousnímková obnova.
Pouze při studeném startu čeká na první snímek nejvýše1s. Pomalý HTTP dotaz
neblokuje další řídicí kroky. Snapshot/HTTP/DB timing jsou oddělené metriky.
Přesná historická příčina obou nočních mezer není ze starých metrik doložená;
oprava odstraňuje blokující síťovou cestu a doplňuje diagnostiku ostatních příčin.

Původní noc a její31stopů se nepřepisují ani nevyplňují. Nezávislá původní
integrace souhlasí. Všech34původních odmítnutých allocator snímků nyní projde
bez nahrazení timestampů a s modelovou proudovou mezí≤25A. Nejde o novou
celou fyzickou nebo přehrávanou regulátorovou noc. Regrese test_night_fixes_0615.py
ověřují nízké/ nulovéP, horní rozpor, celýRAM/outbox průchod a zablokovaný HTTP
worker, stárnutí cache a selhání. Frontend0.6.14 a původní automatizace zůstávají.
Pouze observe_only, žádný akční adaptér, EEPROM, fyzickýpovel nebo veřejnýpush.

Řídicí DB spojení má busy_timeout250ms místo10s, včetně chybové větve. Pokud stop nelze zapsat, pamatuje se původní čas chyby a po zotavení se nejprve dokončí stop a dvousnímková obnova. Nezapsaný čas je i v priority-live.json pro restart. Rozlišené HTTP/cache/DB metriky umožní další mezery přiřadit ke konkrétní cestě; starý recorder nemá úplné rozlišení příčin. Nová regrese simuluje zamčenou SQLite i celémain zotavení bez zpětného prodlužování energie.

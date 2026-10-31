## 0.6.15 · nízký P/UI a neblokující vstupy

Nízký P/UI má konzervativní proudový rozpočet, síťový sběr má samostatný worker
s pevnou mezí stáří snímku a původními reporty. [Chování a meze](docs/NIGHT_FIXES_0615.md).
Původní živý deník zůstává zachovaný, pouze observe_only.

## 0.6.14 · opravy A13-01–A13-06

Monotónní a idempotentní ideální model, energie do posledního platného stopu,
dokončení starého virtuálního vlastníka, pravdivé předání při neznámých údajích
a obnova všech otevřených relací. Deník stránkuje po20událostech změnou pouze
seznamu; úplné podklady se otevřou na vyžádání. Všechna data zůstávají dostupná.
[Chování, testy a meze](docs/INDEPENDENT_FIXES_0614.md). Pouze observe_only;
žádné fyzické povely, změny tarifu/automatizací ani přeznačení staré historie.
Nasazení a ověření skutečného recorderu se dokládají samostatně.

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

## 0.6.11 · konzistentní sběr a výsledek regulátoru

Rychlý HA snímek obsahuje hodnotu, jednotku, meze, kontext a původní report ze stejného State objektu. Komplexní prognózy mají omezené opakování a explicitní snapshot_race místo ztracené entity. Missing/unavailable se nevydává za chybu jednotky. SQLite kontrola ignoruje pouze neexistující dočasné sidecary; hlavní DB a ostatní I/O chyby zůstávají chybou. Log má bezpečně omezené místo výjimky. Přehled odděluje RAM regulátor, ideální alokaci a aktuální skutečnost; historie připojuje původní výsledek regulátoru bez přepisu dat. Pouze observe_only, žádný akční adaptér ani EEPROM zápisy.

## Audit noci runtime0.6.10 · pouze dokumentace

Zapsané neopravené C01–C04: souběh čtení a nesprávná diagnostika missing, mizející SQLite sidecary, význam odlišných modelů v přehledu a nadlimitní starší teplotní monitoring. Produkční zdroje a runtime se nemění. Soukromé důkazy zůstávají naRPi.

## 0.6.10 · HTTP, časové reference a JSON části

Opraveny B01–B03: SHA-256 s ověřeným fallbackem i bez crypto.subtle, sémantické porovnání částí nezávislé na pořadí objektových klíčů a reference pouze z přijatých časově platných snímků. Neplatná reference starší verze se odvolá; návrat vyžaduje dva nové platné snímky. Bez fyzického adaptéru a EEPROM zápisů. Viz docs/HTTP_CLOCK_0610.md. Soukromé doklady zůstávají na RPi, veřejná publikace neprovedena.

## Opakovaný audit0.6.9 · pouze dokumentace

Zapsány neopravené B01–B03: HTTP/crypto.subtle kompatibilita, obnova po odmítnutém budoucím čase a sémantické porovnání JSON částí. Produkční kód se auditem nemění.

## 0.6.9

Opraveny A01–A09: byte budget a bezztrátové atributy, trvalá fronta deníku s recorder receipts a kontrolou úplnosti v UI, vlastník/readback/TTL před převzetím, nezávislé nové sady SolaXu, fail-closed výjimka deníku, energetická bilance rampy/expiry a oddělená kvalita proudových reportů. Přenos/retry a historický výběr dne mají regresní testy. Žádný fyzický adaptér ani dynamické persistentní nastavení. Viz docs/AUDIT_FIX_069.md.

## Auditní dokumentace 0.6.8 · bez runtime změny

Zapsány reprodukované neopravené nálezy v přenosu historie, ověřování vlastníka/snímků, chybové cestě a energetické/statistické bilanci.375 stávajících testů projde,8 nových auditních kontraktů selhává. Podrobná soukromá evidence zůstává naRPi.

## Frontend 0.6.8-r1

Zpětný deník zobrazuje verzi výpočtu z provenance místo pevně napsané 0.6.7. Starší archiv bez verze má původní fallback; text je escapovaný. Backend zůstává 0.6.8. Renderer ověřuje obě verze i nedůvěryhodný vstup.

# 0.6.7 · Stínový řídicí deník

- Snapshot převzatých automatizací a parametrů, přesné virtuální změny A DC a jejich důvody, ukončení a porovnání obnovy v05:00.
- Trvalá relace přežije restart, rozlišuje ruční/cizí změnu, blokování, výpadek sběru a čekající návrat. Nikdy nezapíná původně vypnuté automatiky.
- Karta má časovou osu, graf virtuálního/skutečného limitu a měřeného proudu, statistiky a přehled předání. Historie se načítá pouze GET, s deduplikací a přírůstkovým kurzorem.
- Původní deníky i provozní automatizace zachovány. Žádný akční adaptér, pouze observe_only.

# 0.6.6 · Odolné dokončení noci

- Souhrn páruje měření podle ID fáze, přijímá prázdné/neúplné řádky a uvádí počet dostupných měření. Chybějící proud zůstává neznámý.
- Selhání souhrnu jedné noci neblokuje další sběr, alokaci ani publikaci. Stav souhrnů a poslední úspěšný sběr jsou viditelné na kartě.
- Při selhání sběru se návrhy zneplatní; jejich staré výkony se nevydávají za aktuální. Historické statistiky se nemažou.
- Nové souhrny mají verzovanou přílohu; existující souhrny a vzorky se nepřepisují. Policy souhrnu odpovídá původní relaci.
- Regrese pokrývají observe → finish → restart/další noc → publisher a chybový/stárnoucí stav karty. Pouze observe_only.

# 0.6.5 · okamžité využití fází

Ekonomický cíl je poradní; stínová alokace využívá aktuální rezervu do 25 A.
Viz [MAX_FILL_065.md](docs/MAX_FILL_065.md). Pouze observe_only.

# 0.6.4

- Per-phase 25 A shadow budget calibrated from earlier measured night envelopes, with explicit data provenance, current checks and labeled fallback. No actuator or protection claim.
- Retain economically useful requested targets even when an adverse scenario reaches a lower SOC; expose target, attainable SOC and shortfall separately through runtime and card.
- Shared budget for planning and both priority replays; EV priority uses remaining room for battery charging without intentional EV reduction.
- Read-only reconstruction records phase model peaks and limiting reasons. No changes to historical records or the original addon.

# 0.6.3

- Explicit partial-service planning when the desired EV target cannot fit in 03–05; no invented departure or minimum requirement.
- EV priority minimizes worst remaining EV demand before battery regret. Battery priority minimizes household/battery regret before remaining EV demand; EV import costs are separated. Partial variants never claim equal service or measured savings.
- Independent targets for both priority replays, retained deficits and full input/forecast/calibration provenance on rejected plans.
- Distinct operating-state and charger-mode labels; invalid plan no longer misreported as missing forecast. Unknown model outcomes are published as unknown, preserving historical records.
- Read-only RPi reconstruction tool, Python regressions and an executable card rendering check.

# 0.6.2

- Complete Czech architecture, algorithm, operations, data/AI, automation and delivery documentation; persistent project memory and contributor rules. Documentation changes do not alter runtime behavior.
- Strict plan validation also covers orphan legacy sessions; active legacy models remain frozen.
- EV calibration requires continuous observed inactive-to-active sessions.
- PV-to-EV AC flow and common inverter AC limits are accounted per event.
- Review shares the valid/hash/complete-horizon gate and UTC pre-window calculation.
- PV comparison uses common measured intervals; house and PV quality masks are independent.
- 285 synthetic regression tests; observe_only, no actuator adapter.

# 0.6.1

- Archived as-of weather validation, shared EV/battery allocation and charge port limit.
- Separate directional battery limits, invalid/expired proposal revocation.
- Matched PV masks, canonical hashes and correct SOC end timestamps.

# 0.6.0

- Deterministic scenario SOC planner, causal calibrations and local immutable evidence.

# 0.5.9

- Reference table: forecast >=15 kWh maps to 30% SOC.
- Observe-only context of existing automations and proposed 03-05 coordination.


## 0.6.7-r1 · pouze karta
Samostatné označené zpětné rekonstrukce s kontrolou úplnosti archivu; backend0.6.7 beze změny. Viz CONTROL_JOURNAL_067.md.


## 0.6.7-r2 · pouze karta a auditní revize
Oddělení provozního stavu, strategie nabíjení a ručního povelu. Přesné entity v událostech; konkrétní diagnostika rozporného P/U/I. Zachované odmítnutí neplatných vstupů a původní evidence; backend beze změny.


## 0.6.8
Logický výkonový deník s nulovými persistentními zápisy, Normal Mode/freshness/coherence brány, dva nové snímky, rampa a expirace. Rychlá5s smyčka oddělená od pomalé údržby. Původní data zachovaná; žádný fyzický adaptér. Viz RAM_CONTROL_068.md.


## Audit 0.6.15 · 31. 10. 2026 (bez změny runtime)
Tři nové potvrzené P2 a pozorování latence; [nálezy a meze](docs/AUDIT_0615_20261031.md). Přidány syntetické auditní protipříklady, veřejné výsledky a otisky soukromé evidence. Žádná oprava nebo nasazení.

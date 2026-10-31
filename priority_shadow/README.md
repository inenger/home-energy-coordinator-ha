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

## 0.6.10 · HTTP, časové reference a JSON části

Opraveny B01–B03: SHA-256 s ověřeným fallbackem i bez crypto.subtle, sémantické porovnání částí nezávislé na pořadí objektových klíčů a reference pouze z přijatých časově platných snímků. Neplatná reference starší verze se odvolá; návrat vyžaduje dva nové platné snímky. Bez fyzického adaptéru a EEPROM zápisů. Viz docs/HTTP_CLOCK_0610.md. Soukromé doklady zůstávají na RPi, veřejná publikace neprovedena.

# 0.6.9 · opravy auditu a potvrzovaný deník

[Devět oprav, recorder a meze ověření](docs/AUDIT_FIX_069.md). Přísné převzetí a nové sady SolaXu, konzistentní energie, trvalé přírůstky s potvrzením recorderu, bezztrátové monitorovací atributy. Fyzické řízení zůstává vypnuté.

# 0.6.8 · výkonový stín bez zápisů EEPROM

[Rychlá smyčka, paměť a meze ověření](docs/RAM_CONTROL_068.md). Nové logické výkonové povely, explicitní Normal Mode, cílový interval5s a oddělená údržba. Fyzické řízení není zapnuté.

# 0.6.7 · Řídicí deník celé noční relace

Viz [převzetí, ampéry a obnova](docs/CONTROL_JOURNAL_067.md). Deník virtuálně zaznamená konkrétní automatizace a registry, sleduje změny A DC a předání v05:00 včetně konfliktů. Všechny skutečné provozní zásahy zůstávají vypnuté.

# 0.6.6 · Sběr pokračuje i při chybě souhrnu

Viz [odolnost souhrnů](docs/SUMMARY_066.md). Neúplná fázová data se nepřevádějí na nuly. Chyba minulého souhrnu neblokuje aktuální pozorování. Režim zůstává observe_only.

# 0.6.5 · okamžité využití fází

Ekonomický cíl je poradní; stínová alokace využívá aktuální rezervu do 25 A.
Viz [MAX_FILL_065.md](docs/MAX_FILL_065.md). Pouze observe_only.

# Noční nabíjení · stínové priority 0.6.6

Samostatný Home Assistant doplněk pro Raspberry Pi. Počítá návrhy SOC baterie
a porovnává priority EV/baterie v okně 03:00–05:00 Europe/Prague. Používá
známý nákupní tarif, hodinovou FVE, profil domu bez EV a mapu energie/SOC.
Režim je výhradně `observe_only`; akční adaptér neexistuje.

Tento adresář je kompletní Docker build context: `energy/`, `config/` a `tests/`
jsou přímo uvnitř něj. Původní `energy_coordinator/` zůstává na 0.5.3.
Autoritativní kód nového doplňku je zde; při dalších úpravách nekopírovat
novější kód automaticky do původního koordinátoru.

## Evidence a uvedení do provozu

Doplněk používá vlastní `/data/evidence/evidence.sqlite`; konzistentní kopii
a privátní seed drží na RPi pod `/share/home-energy-priority-shadow`.
Seed ani naměřená historie nejsou distribuovány v tomto veřejném repozitáři.
Bez importovaného lokálního seedu se návrh zablokuje s
`SOC_HISTORY_NOT_IMPORTED`; seed se nesmí nahrazovat vymyšlenou kapacitou.

Instalace z repozitáře má jiný Supervisor slug a vlastní `/data` než stávající
lokální doplněk. Nespouštět je současně proti stejným monitorovacím entitám.
Přechod vyžaduje zálohu, kontrolovaný přenos evidence, vypnutí původního
pozorovacího procesu a ověření zachování historie. Samotný GitHub PR nic
z toho neprovádí.

Dashboard je v `dashboard/night-priority-card.js`; pomocník je pouze stínová
preference. Před změnou dashboardu načíst aktuální konfiguraci, zálohovat ji
a ověřit ostatní záložky a zdroje. Původní provozní automatizace se nemění.

## Ověření

```sh
cd priority_shadow
python3 -m unittest discover -s tests -q
node --check dashboard/night-priority-card.js
```

Testy používají syntetická data. Soukromá ověření na skutečné historii běží
pouze na RPi. Výsledek modelu není naměřená úspora ani jističová ochrana.
Před další prací číst [`../MEMORY.md`](../MEMORY.md),
[`docs/FIX_HISTORY.md`](docs/FIX_HISTORY.md) a [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Podrobná příručka

[Architektura](docs/ARCHITECTURE.md) · [Algoritmus](docs/ALGORITHM.md) ·
[Provoz a obnova](docs/OPERATIONS.md) · [Data a AI](docs/DATA.md) ·
[Automatizace 03–05](docs/AUTOMATIONS.md) · [Vývoj a vydání](docs/DEVELOPMENT.md).

Aktuální změny runtime 0.6.6 popisuje SUMMARY_066.md; starší dokumenty uvádějí historii jednotlivých verzí. `config/settings.example.json` obsahuje
historické nastavení společných modulů; aktivní nastavení tohoto doplňku
určují výhradně volby v `config.yaml` načítané z `/data/options.json`.


Nové otevřené nálezy po nezávislém ověření0.6.13: [audit30.10.2026](docs/AUDIT_0613_20261030.md). Audit sám tyto chyby neopravuje.

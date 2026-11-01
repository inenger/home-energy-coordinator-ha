# 0.6.18 · příjem dat a přednost regulátoru před analytikou

Základ: fa84af2bc9092745ce4730b534cde802294e4478. Pouze observe_only.
Tento dokument obsahuje obecné poznatky a syntetické důkazy, žádné provozní
časové řady, MEMORY, soukromé hashe nebo raw HA odpovědi.

## Reprodukovaná chyba

Rozšířená syntetická cesta main → worker cache → RAM → SQLite → outbox
modeluje nezávislé periody SolaX 5 s, EV 8 s, doručení opožděné o 4 s
a práci smyčky 0–3 s. Původní test s nulovou délkou práce nestačil.
0.6.17 s poll 2,5 s vytváří při práci 1/2/3 s další lease expirace,
přestože nejde o úplný výpadek zdroje. Jde o syntetický protipříklad,
nikoli o doklad přesného doručování během některé skutečné staré noci.

Druhá chyba: RAM rozhodnutí používalo timestamp a snímek ze začátku kroku
i po zpracování prognóz a analytiky. Vznikal tak zpětně datovaný návrh.
Tento problém se nesmí opravit prodloužením freshness nebo falšováním reportů.

## Oprava

- Worker používá v pozorovacím okně 1 s, mimo něj dosavadních 2,5 s.
  Rychlé hodnoty i last_reported jsou vždy z nové HA template.
- Komplexní atributy prognóz/počasí/ceníku mají samostatný 60s REST cache.
  Změna state nebo last_updated vyvolá okamžitý refresh; přetrvávající
  rozpor zůstává snapshot_race. Cache nekopíruje staré scalar hodnoty
  do nového rychlého snímku a neobnovuje časy reportů. Atributy se vracejí
  hlubokou kopií, aby je konzument nemohl změnit v cache.
- Již dostupný zmrazený model se pro regulátor převezme pouze ze stejného dne.
  RAM rozhoduje jako první z aktuální cache. Analytika počká, pokud by
  spotřebovala zbývající lease headroom; její timestamp zůstává původní.
  Rozpočet analytiky se odvozuje z její poslední naměřené doby práce.
- První krok bez modelu nejprve připraví model, potom znovu převezme cache
  a použije skutečný aktuální čas rozhodnutí. Nové reporty se nevymýšlejí.
- Čekání zohledňuje také dobu práce, nejen pevnou sekundovou rezervu.
  TTL, absolutní vstupní deadline, kontrola fází, stop při skutečně
  neplatných datech a obnova přes nové koherentní sady zůstávají.
- Worker atomicky připojí pořadí snímku, začátek/ukončení requestu a jeho
  trvání. RAM vzorek uchovává přesné použité vstupy i owner reporty,
  jejich původní časy a čas čtení. Pozdější snapshot() jiného requestu
  se nevydává za důkaz zdroje dřívějšího rozhodnutí.

Jednosekundový poll sám nestačil pro 3 s práce. Ani pozdní nové čtení před
RAM samo neřešilo blokování dalším analytickým krokem. Finální syntetické
varianty 0/1/2/3 s práce jsou bez zbytečných stopů; skutečný výpadek nadále
zastaví výkon. Nejde o tvrzení, že libovolná latence nebo zátěž nemůže
způsobit oprávněný bezpečný stop.

## Ověření

Nové testy kontrolují celou main cestu s nenulovou prací, nezávislou
integraci energie, původní expiry/phase limity, odlišný skutečný výpadek,
cache scalar/complex race, TTL kontextu, atomickou provenienci
a přepravu rozšířené evidence v byte budgetu monitorů.
Původní regresní kontrakty včetně maskované worker chyby zůstávají.

Starší rekonstrukce zůstávají se svou verzí a předpoklady. Tato oprava
nevyhlazuje jejich grafy ani nedoplňuje nedoloženou historickou dostupnost.
HA karta se nemění. Novou celou živou noc, skutečný heartbeat zařízení,
mapování Mode8, fyzický timeout ani připravenost k ostrému řízení
syntetický test nedokazuje. Fyzický adaptér není přidán.

## Slepé cesty a chyby implementačních pokusů

| Pokus | Výsledek |
|---|---|
| Hledání clienta v ha.py / neexistujícího test souboru | ENOENT; skutečný klient je collector.py. |
| Zrychlení poll + rezerva podle práce | Stále propady při 3 s; zachováno v syntetických JSON. |
| Nové čtení až po analytice | Opravilo čas rozhodnutí, ale ne termín dalšího kroku; nestačí samo. |
| Pomocná fixture se state() a lokálním for state | UnboundLocalError; opravena fixture, nikoli produkční kontroly. |
| Kontrolní fixture bez skutečného select/day | Doplněn syntetický select i day, protože RAM nově čte skutečný stav a kontroluje den modelu. |
| Integrace testu před prvním intentem | None expiry při nulovém výkonu; integrace nyní účtuje jen nenulový výkon. |
| Payload fixture bez selected | Publisher správně odmítl neúplný syntetický výsledek; doplněna povinná položka. |
| Původní next_wait očekával 1 s | Nová rezerva podle práce vrací 0,55 s; regresní očekávání upraveno pro nový kontrakt. |
| Odmítnutý budoucí model v offline replay | Při AssertionError zůstával otevřený read-only SQLite handle; doplněn finally/close. |
| Převzatý příliš brzký cache výsledku | Při odkladu chyběl command_audit; cache se ukládá až po doplnění souhrnu povelů a regrese ověřuje jeho zachování. |
| Import TestCase pro fixture | Způsoboval duplicitní discovery starých testů; nahrazen importem modulu. |

Úspěšné i neúspěšné syntetické výsledky se zachovávají v collection-evidence-0618/.
Lokální testy, GitHub/CI a nativní nasazení jsou samostatné kroky.

Finální kontroly: 464 shadow + 164 legacy Python testů, 9 Node sad,
metadata/syntax, původní main protipříklady a čtyři dřívější auditní kontrakty
prošly. Nové collection-probes potvrzují 0 zbytečných stopů při 0/1/2/3 s
syntetické práce, zachování atomických receiptů i report evidence a stop
při skutečném syntetickém výpadku. Chromium se neopakuje: karta se nemění
a dostupná RAM byla pod dříve stanoveným limitem pro tento zátěžový běh.

Při přípravě veřejných logů zachytil diff --check koncovou mezeru na řádku
syntetického unittest výstupu. Veřejná kopie má normalizované koncové mezery;
původní log a předchozí lokální commit 9d1595c zůstávají na RPi zachované.

## Oprava balení odhalená při nativním sestavení
První image build selhal: test_archived_replay importoval nástroj, který
Dockerfile nekopíroval do /app/scripts. Dosavadní host/CI testy proto byly
pro distribuovaný balík nedostatečné. Doplněn COPY scripts a samostatný CI
kontrakt, který sestaví testovací rozložení přímo podle Docker COPY a spustí
replay test z tohoto rozložení bez původního source PYTHONPATH. Tentýž
kontrakt před opravou selhal na ModuleNotFoundError a po opravě prošel.
Neúspěšný build i první veřejný commit zůstávají v historii. Provoz byl
mezi pokusy obnoven na předchozí instalované verzi; nejde o novou poruchu
ani o změnu fyzického řízení. Nativní build se opakuje po opravě balíku.

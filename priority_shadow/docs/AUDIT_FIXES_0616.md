# Opravy auditu 0.6.15 → 0.6.16

Vstup: main 85b0c14156b8895af11f67faaa75b13da62b8cef, audit A15-01–03
a pozorování O15-04 z 31. 10. 2026. Práce dokončovaná 1. 11. 2026 na RPi.
Původní audit a jeho důkazy zůstávají zachované. Provoz pouze observe_only.

## Chování

- A15-01: chyba síťového workeru má generační číslo, nejstarší nepřevzatý
  čas a vlastní atomicky přejmenovaný JSON soubor. Úspěšné čtení ji nesmaže.
  Observer ji potvrdí až po uložení stopu a zařazení do SQLite outboxu.
  Potvrzení starší generace nesmaže souběžnou novější chybu. Chyba zápisu
  ponechá RAM latch; při opětovném čtení nevznikne platný návrh. Přetrvání
  při běžném restartu je testované; atomický rename bez fsync není zárukou
  přežití náhlého výpadku napájení nebo poruchy disku.
- A15-02: události se stejným ID a vzorky se stejným časem musejí mít
  sémanticky shodný obsah napříč potvrzenými dávkami, cache a živým náhledem.
  Konflikt blokuje modelový souhrn, graf i časovou osu daného živého dne.
  Přesné opakování a jiné pořadí klíčů JSON jsou přípustné. Čisté opakované
  načtení může chybu zrušit; chyba živého dne se nepřenáší do samostatného archivu.
- A15-03: konec dotazu uzavřeného a kompletně potvrzeného přenosu je nejvýše
  last_recorded_at + 2 s. Zohledňuje čas skutečného přenosu včetně pozdního
  předání, nikoli pevně 05:00. Aktivní/nepotvrzený přenos nebo neznámý konec
  používá současnost. Úplná cache stále šetří opakované dotazy.
- O15-04: stránka deníku nově obsahuje nejvýše 10 událostí. Původní
  nahrazení pouze scrollovací tabulky při výslovném přepnutí stránky zůstává;
  graf a ostatní panely se tím nepřekreslují. Všechny záznamy jsou dostupné.
  Aktualizace dat stále zachovávají čtenou kotvu, jednotlivé details a focus.

## Ověření

450 Python testů shadow a 164 původního doplňku prošlo.
Nové test_audit_fixes_0616.py ověřují restart, chybu disku, generační závod
a skutečnou main smyčku → SQLite stop → outbox → potvrzení. Při první chybě
SQLite se zachová původní čas výpadku; energie nekryje výpadek a obnova
vyžaduje dva nové snímky. Původní backendový protipříklad A15-01 nyní splňuje kontrakt.

scripts/test_audit_fixes_0616.mjs testuje skutečný loader s validními
hashovanými konfliktními dávkami v obou pořadích, přesné duplicity,
konflikty živých událostí/vzorků, přírůstkovou cache, návrat do platného
stavu, izolaci archivu a časové meze aktivního, čekajícího i pozdního přenosu.
Původní audit_deep_0615.mjs předpokládá existenci nesprávně přijaté cache;
nový regresní test používá stejný protipříklad a správně připouští její odmítnutí.
Původní audit se nepřepisuje. Dřívější auditní kontrakty a Node regrese prošly.

Nativní read-only ověření na RPi porovnalo skutečný HA recorder s původními
SQLite řádky posledních dvou nocí a s oddělenou starší rekonstrukcí.
Přepnutí rekonstrukce → původní deník → rekonstrukce nesloučilo zdroje.
Všechny archivní checksumy byly ověřeny; staré řádky ani provenience se nepřepisují.

Chromium používá HA podobný vnořený shadow scroll kontejner ve šířkách
1280 a 390 px. Není to přihlášený HA shell ani uživatelův iPhone.
Přísný limit stránkování zůstává 100 ms; měří i vynucený layout.
Konečné naměřené výsledky a hranice jsou v připojené evidenci.
Úspěch testu není zárukou nulových latencí na každém zařízení.
Jedna obnova celé karty se skutečnými daty trvala 116,3 ms, přesto držela
kotvu bez posunu; tento čas se nesmí zaměnit za stránkování.

## Pokusy, chyby a slepé cesty

1. Předchozí zápis nového testu skončil timeoutem; kontrola při pokračování
   potvrdila, že soubor nevznikl. Následný test nebyl spuštěn, protože
   automatická kontrola schvalování nemohla proběhnout kvůli limitu využití.
   Po uživatelově pokračování nástroj opět fungoval; práce se obnovila kontrolou stavu.
2. První nový integrační test použil neexistující journal_outbox místo
   journal_transport_outbox. Výjimku zachytila main smyčka, takže assertion
   zaznamenala chybějící potvrzení. Opraven název ve fixture, původní FAIL zachován.
3. První syntetický browser běžel souběžně s Python testy: stránkování
   117,2 ms FAIL. Izolované opakování 73,8/77,4 ms PASS nevylučuje první výsledek.
4. Skutečný deník měl i izolovaně 117,1 ms FAIL. Profilování ukázalo
   updateControlPage nejvýše 20,5 ms, ale kliknutí včetně layoutu 101,7 ms.
   Samotný kód skládání řádků tedy nevysvětloval celý náklad.
5. Hypotéza dodatečného CSS oddělení nebyla použita: strict containment
   scrollovacího kontejneru už existoval.
6. Pokus zachovat kontejner a vyměnit pouze tbody s následným scrollTop=0
   dosáhl na úzké šířce 203,9 ms FAIL. Zamítnuto a vráceno; soukromá
   kopie pokusu a log zůstávají na RPi, SHA-256 jsou v manifestu.
7. Menší stránky po 10 řádcích dosáhly na skutečných podkladech 46,5/51,3 ms,
   bez plného renderu, se všemi řádky dostupnými a bez posunu čtené kotvy.
8. Původních deset krátkých syntetických řádků se vešlo do kontejneru,
   takže test kolečka neměl co rolovat. Doplněn víceřádkový syntetický popis,
   který skutečně vytváří overflow. Limit 100 ms, geometrie a wheel assertion
   se neuvolňují. Původní neúspěšný test zůstává doložený.
9. Pomocné průzkumné příkazy dvakrát skončily na neexistujícím názvu/globu
   (ci.yml místo validate.yml, žádné fix-0615/*.mjs); navazující čtení
   v řetězci se neprovedlo a bylo provedeno samostatně. Nešlo o chybu aplikace.

## Meze a publikace

Nová úplná produkční noc s 0.6.16 ještě není ověřena. Syntetické scénáře,
načtení historických dat ani úspěšné nasazení nejsou takovým důkazem.
Výsledek rekonstrukce není skutečně realizované nabíjení. Žádné fyzické
povely, EEPROM zápisy, změny tarifu, priorit ani původních automatizací.
Nativní nasazení, GitHub commit, PR, merge a CI se dokládají samostatně;
tento dokument sám nepotvrzuje jejich dokončení.


## Nativní nasazení ověřeno 1. 11. 2026
Backend i HTTP podávaná karta jsou 0.6.16. Sběr je čerstvý/ok, zdrojové
hashe souhlasí, SQLite quick_check je ok a původní evidence zůstala zachovaná.
Původní automatizace, konfigurace původního doplňku, dashboard a archivní
provenience se nezměnily. Obě poslední původní noci mají přesnou shodu
načteného recorderu s SQLite; přepínání starší rekonstrukce je ověřené.
Před aktualizací vznikla nativní záloha a soukromá kopie zdrojů/evidence.
Původní lokální koordinátor0.5.4 běží, rollback0.5.3 zůstává zastavený.

Veřejný zdroj d1dab28607ae4695457bfc2d29e46db9340384ee má shodný strom
2071708876f79df0e42089be7d568bfb5598a5aa s lokálním bcd43e5285a0f8917290d075d438e1ef268d7ab7.
Publikace: [PR #10](https://github.com/inenger/home-energy-coordinator-ha/pull/10).
CI/merge jsou samostatná následná kontrola; jejich stav ověřit na GitHubu.
Důkaz nasazení: audit-evidence-0616/deployment-summary.json a privátní SHA manifest.
Celá nová noční relace0.6.16 zatím ověřená není.

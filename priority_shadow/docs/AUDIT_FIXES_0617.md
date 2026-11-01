# Opravy A16-01, A16-02 a vykreslování deníku · 0.6.17

Vstup main f0bc032079a41b26c1d79584333508012881e943,
audit AUDIT_0616_20261101.md. Starý audit, původní noc, neúspěšné
protipříklady a měření zůstávají zachované. Režim je observe_only.

## Časování obnovy místo prodlužování starých dat

Řídicí smyčka má nadále základní interval5s v nočním sběru/60s mimo něj.
Při nenulovém intentu naplánuje další krok nejpozději přibližně1s před
jeho původním koncem platnosti. Minimální čekání je250ms, aby nevznikla
aktivní nekonečná smyčka u krátké/končící lease. Čas práce se odečítá;
aktuální čas po práci určuje zbývající platnost.

Dřívější krok může převzít novou EV cache před expirací. Stejná sada
SolaXu dovolí pouze podržení/snížení již platného výkonu, nikdy zvýšení
nebo vydávání stejného reportu za nový snímek. Původní HA timestampy,
limity stáří a konec okna se nemění. Když data skutečně nepřijdou,
původní deadline stále ukončí intent a návrat vyžaduje dvě nové sady.

Změna je v priority_observer.next_wait a skutečném STOP.wait runtime.
Samotný RAM regulátor při vyvolání pouze po pevných5s zůstává správně
povinen zastavit po expiraci. Proto původní přímý auditní scénář A16-01
nadále ukazuje chybu starého způsobu volání; nemodeluje nový scheduler.
Konečná regrese ověřuje celou main smyčku s jejími skutečně zvolenými
čekáními, RAM, SQLite a outboxem.

test_audit_fixes_0617.py a scripts/verify_audit_fixes_0617.py používají
8s EV reporty s explicitně syntetickým4s doručením a nové SolaX sady po5s.
Včasná obnova nemá stop/expiraci, zachová původní reporty a energii
odpovídající platným intervalům. Kontrolní skutečný výpadek EV stále
zastaví a vyžaduje dvě nové celé sady. Syntetické4s není měřená latence
konkrétní integrace ani důkaz, že se opravily všechny původní příčiny.
Nativní nová celá noc0.6.17 dosud není ověřená.

## Nejdříve nejstarší výpadek, potom potvrzení

V každé chybové větvi se zjišťuje také dosud nepotvrzená chyba workeru,
i když ji právě maskuje storage/stat chyba před priority_states().
Stop použije nejstarší z pending času, aktuální chyby a worker first_at;
časy se porovnávají jako datetime, nikoli lexikograficky. Souhrn chyby
uchovává také worker metadata. Potvrzení konkrétní generace následuje
až po uloženém stopu a enqueue; novější generaci starší ack nesmaže.

Celá main regrese dokládá: platný500W požadavek v sekundě5, výpadek
v sekundě6, maskující budget/stat chyba v sekundě10. Stop se nyní
zapíše v sekundě6 a integrace má pouze500W×1s. Původní protipříklad
A16-02 nyní splňuje kontrakt; původní důkaz nesprávných5s zůstává v auditu.

## Stránkování bez vynuceného čtení scroll geometrie

Čtení scrollTop v click handleru může synchronně vyhodnotit dosud
nevyhodnocené rozložení celé karty. Offset se nyní ukládá ve scroll eventu.
Pokud je deník již nahoře, stránkování uchová kontejner, hlavičku, řádky
i buňky a mění jen potřebný obsah. Když je potřeba explicitní návrat
nahoru, vytvoří nový scroll kontejner s nulovým výchozím offsetem;
nečte starou vertikální geometrii ani nezapisuje scrollTop po výměně dat.
Horizontální offset se zachovává. Nový event ID dostává novou identitu
details a prázdné podklady; staré rozbalení/JSON se nepřenese jinam.

Limit10řádků a dostupnost celého deníku zůstávají. Browser regrese
kontroluje navíc skutečné zapamatování wheel offsetu, zachování DOM
při stránkování nahoře a izolaci rozbalených diagnostik různých událostí.
Limit100ms se neuvolňuje. Původní DOM/anchor/focus/offset, všechny stránky,
vzorky a zachování grafu se ověřují nadále.

První úspěšné měření skutečné fixture:40.3/30.9ms při1280/390px.
Zesílená regrese v dalším běhu:91.2/29.4ms,0pxrefreshshift.
Další finální výsledky jsou v připojené evidenci. Jedna obnova celé karty
trvala103.6ms; tato oprava nedokazuje univerzální limit100ms pro všechny
operace nebo klienty. Jde o izolovaný Chromium naRPi, nikoli přihlášený
HA shell nebo uživatelův telefon.

## Uchované neúspěšné pokusy

1. První varianta znovu používala řádky, ale resetovala scrollTop po jejich
   změně:405.2msFAIL. Profilování ukázalo na prvním přepnutí zhruba395ms
   v samotném handleru, ostatní stránky byly pod58ms.
2. Přesunutí čtení/resetu scrollTop před výměnu řádků nepomohlo:
   505.2msFAIL. Hypotéza „stačí jiné pořadí“ byla zamítnutá.
3. Konečná varianta odstranila synchronní čtení staré vertikální geometrie
   z click handleru; používá hodnotu ze scroll eventu a případný nový
   nulově posunutý kontejner. Prošla stejným přísným limitem i zesílenou regresí.

Původní kód obou odmítnutých variant je zachovaný naRPi a veřejně jsou
přiložené rozdíly, měření a SHA-256 soukromých podkladů.

## Ověření, provoz a meze

455Python testů shadow,164původního balíčku, nové celé main scénáře,
Node regrese, původní auditní kontrakty a metadata se ověřují odděleně.
Běží postupně, s kontrolou MemAvailable a monitorováním paměťové rezervy.
Hromadná soukromá rozhodnutí se nematerializují do seznamu.
Browser má omezený Node heap a umí při SIGTERM zavřít Chromium.

Před nasazením je nutná nativní záloha, aktuální konfigurace dashboardu
a ochrana původní evidence. Po nasazení se zvlášť ověřují verze,
freshness/Supervisor, zdrojové hashe, HTTP karta a skutečný recorder.
Dokončení nasazení a GitHub/CI se připojí samostatně; tento text je nenahrazuje.
Původní noci se nepřepočítávají ani zpětně neopravují vydáváním předpokladů
za naměřené reporty. Žádné fyzické povely, EEPROM, tarif nebo změny priorit.

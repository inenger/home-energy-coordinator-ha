# Aktuální sada a historický výchozí návrh

Následující původní text popisuje sadu při zavedení0.6.22. Současný počet a členství určuje [runner](../scripts/verify_robustness.py); 0.6.23 ji rozšířila o další kontrakty. Používejte [aktuální mapu testů](TEST_MATRIX.md) a [workflow](../.github/workflows/validate.yml), nikoli historický počet níže. Kritérium odmítnutí FAIL/skip/expectedFailure se nemění.

# Opakovaná kontrola odolnosti současného regulátoru

Navazuje na finální0.6.22, main18fc62f4aa620e4ea9f809eee057998b11a9283c.
Jde o testy a CI, bez změny provozního kódu, Docker contextu a verze.
Běžící doplněk se kvůli tomu nepřestavuje ani nerestartuje.

## Co běží při každé změně

Hlavní job validate používá explicitně Python3.12 a před původní úplnou
sadou provede třikrát14poruchových regresí. Druhý job recovery-python314
opakuje stejnou kontrolu na Python3.14. Selhání okamžitě ukončí job;
další iterace nesmí zamaskovat první neúspěch.

Brána odmítá i vynechané testy, expectedFailure a prázdnou/neúplnou sadu.
Čtyři samostatné testy ověřují tuto politiku, včetně negativních případů.
Počty opakování nejsou vydávány za počet různých scénářů.

Jde o automatické CI kontroly. Tato změna nenastavuje serverová pravidla
ochrany větve ani neomezuje administrátorské vynucení merge. Jejich skutečné
nastavení nelze zaměňovat s pouhou existencí zeleného jobu.

## Nové scénáře

1. Skutečný SQLite writer lock současně s přechodným selháním sběru a
   následným ukončením skutečného spawn ukládacího procesu před prvním ack.
   Produkční run_loop musí po převzetí chyby v RAM obnovit výkon ze známých
   nových vstupů. Po uvolnění disku a obnově procesu se fronta uloží přesně,
   bez duplicit, beze ztráty, se shodnými počty událostí/vzorků a s outboxem.
2. Celé dvouhodinové noční okno v urychleném syntetickém čase přes produkční
   run_loop a skutečnou SnapshotCollector.priority_states. Tři nezávislé
   generace výpadku, dočasně nedostupný proud fáze, návrat vstupů, výkonové
   a lease invarianty, uzavření v05:00, idempotentní SQLite zápisy, outbox
   a shoda finální relace s uloženou evidencí. Průběžné výsledky se v testu
   nehromadí neomezeně v RAM.

Zbývajících12případů je současná test_recovery_0622: zablokovaný fsync,
generace chyb a restartová stopa, ztráta dávky po trvalém uzavření, omezená
fronta, pád po commitu před ack, zamrzlý worker, pád monitoru, shutdown během
obnovy, restartovací rozpočet a zachování chyby přípravy přes heartbeat.
Historický vadný observer se nepoužívá jako důkaz aktuální produkční cesty.

## Reprodukce

```sh
python3 scripts/robustness/test_gate_policy.py
python3 scripts/verify_robustness.py --repetitions 3
```

Testy používají výhradně syntetická data a dočasné databáze. Případný
SUPERVISOR_TOKEN se v jejich procesu nahradí neplatným syntetickým tokenem.
Žádné služby zařízení ani produkční DB se nevolají. Časové limity CI
zabrání neomezenému visení; na RPi se spouští sériově s paměťovou pojistkou.

První místní průchod14případů na Python3.14.8 prošel. Dřívější nenalezený
adresář při vytváření testového souboru byl opraven vytvořením adresáře;
nešlo o chybu aplikace. Opakované výsledky a CI se dokládají zvlášť.

## Co kontrola neprokazuje

Urychlená syntetická noc není skutečná nová noc, fyzický watchdog ani
záruka plánování Linuxu, odezvy HA či spolehlivosti disku. Neověřuje
fyzický akční adaptér, který stále chybí. Nemaskuje neplatné vstupy a
nemění jejich bezpečný stop. Nenahrazuje kontrolu skutečné noční evidence.

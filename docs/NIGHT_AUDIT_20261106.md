# Audit nočního běhu a kandidáta 0.6.23 — 6.11.2026

Výchozí veřejný runtime: main `101ec014ed869cdcca9b7a9e5ab507d5a7e74120`,
strom `0f51f769955704085722dff0e6ea3800a57a22f1`. Noc proběhla na 0.6.22;
0.6.23 byla instalována až po jejím skončení. Tyto výsledky se nesmějí vydávat
za úplnou produkční noc nové verze. Jde o audit bez změny runtime či konfigurace.

## N06-01 — otevřený blokátor dostupnosti: studená záloha

Supervisor výslovně zaznamenal vypnutí primárního doplňku pro `cold backup`,
provedení zálohy a jeho opětovné spuštění během aktivního nočního okna.
Záznamy obsahují změnu hlavního runtime a odpovídající mezeru mezi vzorky.
Nešlo o samovolný pád analytického workeru ani důkaz pádu celého hostitele.

`priority_shadow/config.yaml` má **i v 0.6.23 `backup: cold`**. Dohled nad
pomocnými procesy nemůže zajistit pokračování regulátoru, pokud Supervisor
zastaví celý kontejner. Zelené jednotkové testy ani opravená obnova workerů
neprokazují nepřerušený provoz při této provozní podmínce.

[Syntetický protipříklad](../scripts/audit_cold_backup_0623.py) prochází skutečnou
`run_loop`, trvalým flushem/outboxem, shutdownem, opětovným bootstrapem a novými
vstupy. Potvrzuje mezeru, odvolání staré lease a konzervativní příznak
`runtime_restart_unflushed_state_unknown`. Původní události/vzorky zůstávají
zachované; obnova znovu vyžaduje nové koherentní sady. Reproduktor nevolá
Supervisor, neprovádí skutečnou zálohu a neposílá fyzické povely. Jeho úspěch
znamená **reprodukci blokátoru, nikoli readiness PASS**. Jde o historický
kontrakt 0.6.23, oddělený od současné poruchové brány.

Nutná náprava: sladit zálohování s požadavkem dostupnosti řídicího procesu.
Pouhé přepsání `cold` na `hot` bez konzistentního SQLite snapshotu a ověřeného
restore není doložené řešení. Dočasné provozní omezení musí zohlednit celé
aktivní okno a délku zálohy; změna globálního plánu záloh nebyla součástí auditu.
Dostupnost při záloze a obnova z nativního archivu potřebují samostatný test.

## N06-02 — bezpečnostní stop při zestárlé vstupní cache

Samostatný pozdější stop pochází z `COLLECTION_SNAPSHOT_EXPIRED`: cache byla
starší než její nastavená mez. Po dvou nových koherentních sadách se výpočet
obnovil. Z dochovaných dat nelze určit přesnou příčinu zdržení vstupního
požadavku. Souběh s běžící celkovou zálohou není důkaz příčinnosti.

TTL ani kontrolu čerstvosti kvůli tomu nezvyšovat. Zastaralé podklady se nesmějí
vydávat za aktuální. Audit tento stop odlišuje od chyby SQLite a od vypnutí
celého primárního procesu při záloze.

## Staré chyby monitoringu/analytiky a kontrola nové verze

Část staré noci nesla vyčerpaný doživotní rozpočet obnov monitorů. Objevily se
také místní `WriterTimeout`, rozlišené mezi vedlejší analytikou a cestou evidence.
Nejsou tím doložené poškození SQLite ani samotné `SQLITE_BUSY`. Některé body
vedlejší analytiky chybějí, i když řídicí vzorky a recorderový deník existují.
Tyto původní záznamy se neopravují přepisem historie.

0.6.23 má doložené opravy těchto mechanismů v [NIGHT_FIXES_0623.md](../priority_shadow/docs/NIGHT_FIXES_0623.md).
Po nasazení byly sledovány aktuální health, postup commitů, trvalá analytická
fronta, přetečení a obnovy obou workerů. Po ukončení očekávaného bootstrapu
nebyla ve sledovaném úseku zjištěna nová provozní chyba. To neuzavírá N06-01
ani nepotvrzuje novou kompletní noc 0.6.23.

## Integrita a meze výpočtů

Nezávislá integrace modelové energie z řídicích vzorků respektuje lease,
explicitní stop mezi vzorky a skutečné mezery. Výsledek, pokryté intervaly,
řetězec jejich hashů i nelineárně přepočtený SOC souhlasí s uloženým modelem.
Kontrolované reporty dodržují své původní časové meze; zkontrolovány byly
naměřené/modelové fáze a DC limit. Skutečný HA recorder a servírovaná karta
se porovnávají s původními uzavřenými záznamy.

Modelové nabíjení není skutečné nabíjení. Záznamy této noci neprocvičily odběr
EV, proto samy nepotvrzují rozběh EV ani souběh obou nabíjecích zátěží.
Stále chybí fyzický akční adaptér a ověření jeho protokolu, odezvy a expirace.
Proudové reporty a model bez přechodové rezervy nejsou ochranou jističe ani
měřením krátkých hardwarových špiček. `physical_control_ready` zůstává false.

Dále Supervisor hlásí jiné archivy v katalogu záloh bez očekávaného
`backup.json`. Jejich původ/účel a obnovitelnost nebyly tímto auditem prokázány;
nelze je automaticky považovat za použitelné nativní zálohy. Nesmazány ani
neupraveny. Toto varování není důkazem selhání právě dokončené konkrétní zálohy.

## Metodika a zachované opravy auditu

První pomocný součet energie opomněl explicitní stop ležící mezi dvěma vzorky.
Po doplnění hranice události se přesně shoduje i identita pokrytých intervalů;
nešlo o opravu aplikační energie. První klasifikace post-start health navíc
příliš široce označila stav `starting` před prvním commitem za chybu. Očekávaný
bootstrap je nyní vymezen krátkým časem od startu, nulovými sekvencemi a absencí
chybových kódů; pozdější/přetrvávající poruchy se tím nemaskují. Časové počty
rozhodnutí používají úplné časové značky s časovou zónou.

Soukromé časy, naměřené řady, databáze, logy a jejich kontrolní součty zůstávají
na RPi. Výchozí neúspěšné pomocné výstupy byly zachované odděleně. Historické
noční souhrny, nastavení, automatizace ani běžící služba nebyly auditem měněny.

SHA-256 privátního finálního numerického auditu (bez zveřejnění obsahu):
`bbc6de78f112f534226fd1c087a20f5ba25307d64623906674e6e81a0ce68e51`.

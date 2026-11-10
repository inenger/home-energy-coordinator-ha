# Audit připravenosti 0.6.29 k fyzickému řízení

Výchozí veřejný runtime: merge `2b83d779fcf416b72a8827adde1aa7fdd37b7953`,
strom `34dd459597fdf3c96377d4b98416854ad7387494`. Audit nemění runtime ani
jeho verzi. Přidává reprodukce, přehled a otevřené nálezy.

**Verdikt: NO-GO pro fyzické řízení.** Konfigurace i produkční entrypoint
podporují výhradně observe_only. Chybí akční adaptér, nezávislý fyzický timeout,
ověřené mapování a readback. Úspěšný pozorovací běh tyto části nedoplňuje.

## Rozsah a meze

Inventář zahrnuje všech 56 Python modulů build contextu, Docker entrypoint,
konfiguraci, aktivní síťové a procesové cesty, sběr/cache, RAM/lease, persistenci,
transport, plánování, zálohy, publikaci a kartu. Kritické cesty byly čtené a
vybrané slabiny mají syntetické protipříklady přes produkční komponenty.
Nejde o formální důkaz všech vstupů, fyzický hardware test, nový vizuální test
uživatelova HA shellu ani novou celou noc. Provozní data a soukromé důkazy jsou
oddělené od veřejného zdroje.

Dřívější testy přesně stejného runtime nejsou novou fyzickou certifikací.
Zde přidané testy pojmenované counterexample jsou úspěšné právě tehdy, když
potvrdí současnou slabinu. Neoznačují ji za opravenou. Při opravě se musí
převést na přísná akceptační očekávání a zachovat původní důkaz v historii.

## Blokátory a nové nálezy

| ID | Závažnost a současný význam | Reprodukce / zdroj | Podmínka odstranění |
|---|---|---|---|
| LIVE-01 | Kritický blokátor: žádná cesta od logického požadavku k ověřenému fyzickému povelu. | config.yaml: pouze observe_only; priority_observer.main jiný režim odmítne; ram_control.capabilities má všechny fyzické verifikace false, intent.wire_command je None. | Ověřený adaptér pro konkrétní firmware, AC/DC hranice, registr/timeout/next-motion a readback; hardwarový test zániku povelu bez HA/RPi a bezpečného předání. |
| LIVE-02 | Kritický blokátor: empirická kapacita/účinnost, fyzické fáze a odezva nejsou automaticky ověřené. Max-fill má transient_margin_a=0 a balancovaný příkon baterie; AC limit nabíjecí cesty může být neznámý. | instant_fill.allocate/session, soc_runtime.inputs; explicitní varování a control_verified=false. | Potvrdit měřicí hranice, fázovou topologii, charge/discharge limity a reálnou odezvu/špičky, souběh zátěží, schválenou rezervu. Žádné domýšlení hodnot. |
| N06-03 | Vysoká: pomalé obnovení komplexního REST kontextu blokuje stejné vlákno rychlého sběru. | ReadOnlyHA.priority_states nejprve synchronně volá priority_context; obnovení po60s může čekat na GET. Reálná7.5s cache v protipříkladu vyprší dříve, než začne rychlá template query; produkční run_loop hlásí failure. | Oddělit pomalé obnovení kontextu od rychlých reportů, zachovat původní dostupnost/race/TTL a testovat skutečnou pomalou GET cestu až přes běžící smyčku. Neprodlužovat TTL. |
| N06-04 | Vysoká dostupnost: sběrné vlákno nemá obdobu dohledu evidence/monitor procesů. | SnapshotCollector.run/start/snapshot; syntetické neočekávané ukončení vlákna ponechá cache expirovanou, error_code může zůstat None a nové volání ji neobnoví. | Explicitní liveness/progress diagnostika a omezená obnova skutečně mrtvého či uvízlého sběru; žádné neomezené opuštěné thready ani nová lease ze staré cache. SystemExit je vložená porucha, nikoli doložená příčina minulé noci. |
| REC-02 | Vysoká: čerstvý heartbeat může maskovat dlouhodobě stojící durable ACK. | EvidenceBridge.worker_problem kontroluje proces/odpovědi, nikoli postup committed_seq při pending dávce. Skutečný evidence_worker během vložené lokální contention opakovaně hlásí WriterTimeout/ack0; guard při čerstvých odpovědích neobnovuje proces. | Samostatně měřit čekající práci, stáří nejstaršího ACK a jeho postup; definovat omezené zotavení lokálně uvízlého writeru. Rozlišit trvalé I/O/BUSY a plný disk, ne restartovat bezhlavě. Ověřit FIFO/replay/epoch/late ACK a klouzavý restart budget. |
| DATA-03 | Vysoká integrita: klíč již potvrzené dávky není vázán na její celý obsah. | persist_batch při existujícím(runtime,seq) vrací před kontrolou řádků. Kolizní obsah stejného klíče tiše projde; původní immutable řádek se nepřepíše. | Přesné opakování musí být idempotentní, odlišný obsah téhož ID musí být výslovný konflikt. Svázat durable receipt s původním obsahem, ne s dnešní mutovatelnou session; kompatibilita se starými receipts bez přepisu historie. |
| DATA-04 | Vysoká integrita návrhů: konfliktní SOC rozhodnutí se stejným issued_at se vrátí, ale neuloží. | record_decision používá INSERT OR IGNORE a vždy vrací nový seal. Při validním původním a novém invalidním návrhu stejného času SQL dál vrací původní session_plan, zatímco volající dostal jiný hash. | Vracej pouze skutečně uložený obsah, kolizi odmítni a explicitně řeš revokaci bez přepsání původního návrhu. Ověřit monitor→SQL→session_plan/review/replay i přesné opakování. |
| LIVE-03 | Kritické při chybném budoucím zapojení, současná vlastnost stínového rozhraní: veřejný ideální výkon není platný fyzický intent. | run_loop/MemoryControl.step a publish_status.priority_rows: ideální senzor může být kladný při target_ac_w=0 kvůli Off-Grid. Senzor nenese lease deadline. Při neúspěšném HTTP může v HA zůstat poslední kladný stav. Karta ideální/řídicí/modelové veličiny rozlišuje; není tvrzeno současné fyzické ovládání. | Fyzický adaptér musí přijímat pouze autoritativní, platný, vlastněný intent s TTL/epoch a nezávislým watchdogem, nikoli automatizaci navázanou na tento monitor. Test síťového výpadku a expirace na zařízení. |
| MON-03 | Střední: různé RuntimeError příčiny se ztrácejí v obecné diagnostice. | failure_result zachová typ a umístění, nikoli známý sémantický důvod. COLLECTION_SNAPSHOT_EXPIRED a COLLECTION_WORKER_FAILED mohou oba skončit jako RuntimeError; první auditní test to odhalil. | Bezpečný omezený strojový kód příčiny, bez tokenů/celých citlivých zpráv; odlišit timeout, stale cache a mrtvý sběr v UI/evidenci. |
| UI-01 | Střední: neplatná časová metadata mohou přerušit celé vykreslení karty. | soc_runtime.inputs propustí sunrise='unknown'; TM formátuje new Date bez validace. Skutečné card.render v Node VM vyhodí RangeError a starý DOM zůstane. | Neplatné datum zobrazit jako unknown/—, izolovat vadnou sekci; test celé render cesty pro missing/unknown/unavailable/malformed i platná časová pásma. Nejde o nový vizuální test scrollu. |
| DOC-01 | Nízká, opraveno touto dokumentační revizí: rozcestník architektury a nadpis registru popisovaly starší zdroj; část řádků registru byla mimo společnou Markdown tabulku. | Původní texty zůstávají v Git historii. Aktualizovaný přehled a přísnější verify_documentation. | Verifikátor hlídá aktuální verzi registru i souvislou tabulku nálezů; historický popis architektury je výslovně oddělený. |

## Další známé meze, které nejsou tímto uzavřené

- DB-01 a N06-02: tento audit prokazuje nové mechanismy, nikoli příčinu každého
  minulého timeoutu či zastavení. Obnovený zdravý stav nemaže historii chyby.
- DATA-01: RAM fronta má omezenou kapacitu; dlouhá disková porucha může vést
  k přiznanému loss. Pád hostitele může ztratit nepotvrzenou RAM. Žádné nulové
  RPO není tvrzené. Rozpočet DB není totéž co veškeré kopie a archiv na disku.
- BACKUP-01/02: konzistentní SQL snímek, skutečný Supervisor katalog, běh přes
  zálohu a oddělená obnova jsou různé kontroly. Hash/obnova se musí ověřit pro
  konkrétní instalaci; samotný zelený unit test nativní archiv nedokazuje.
- PLN-01 a VAL-01: nová celá noc, přenosy a kalibrace mají vlastní rozsah.
  Částečný plán se nesmí přeznačit za splněný cíl. Stínový max-fill míří na100%
  a ekonomický cíl je pouze poradní. Toto oddělení musí být výslovné v návrhu
  budoucího ostrého řízení; není to nově schválená změna priorit.
- LIVE-02: default reserve15% je modelová reference, nikoli potvrzená fyzická
  politika. Neznámý limit nebo heartbeat se nesmí doplnit smyšlenou hodnotou.
- Credential Supervisoru má širší práva než aplikační rozhraní. Aktivní
  publisher má přesný allowlist monitorů, sběr odmítá redirect, karta zapisuje
  pouze vlastní stínovou preferenci. Není to OS-level read-only credential.
- V balíčku zůstávají historické collector/runtime/updater moduly. Docker
  spouští priority_observer, nikoli starý HTTP runtime; jejich přítomnost není
  důkaz, že běží starý server či updater. Při provozu nezaměňovat entrypointy.
- Chybějící fyzická odezva, ztráta CPU/napájení/HA a neověřený fallback na
  zařízení nejsou opravené oddělením SQL procesů. Linux/Python není hard RT.

## Co audit potvrdil jako správné v současném kontraktu

RAM smyčka nemá diskové Store/HTTP/analytiku; skutečné výpadky sběru a
neplatné vstupy zastavují logickou lease. Návrat vyžaduje nové sady.
Immutable původní řádky se při protipříkladech DATA-03/04 nepřepisují; problém
je falešné potvrzení/nesoulad reprezentací. Monitorovací síťová chyba není
přímý povel do zařízení. Vstupy wallboxu mají realtime autoritu, Tessie SOC
zůstává doplněk. Přísná ochrana TTL a fází se při tomto auditu neodstraňuje.

## Reprodukce a uchovaná historie

`priority_shadow/tests/test_readiness_audit_0629.py` obsahuje produkční-mode
checky a současné protipříklady N06-03/N06-04/REC-02/DATA-03/DATA-04/LIVE-03/
MON-03. Reálné thread/SQLite komponenty, žádné live HA služby. UI protipříklad:
`scripts/test_readiness_audit_0629.mjs`, skutečná card.render s Node VM,
standardní browser-like stuby a syntetická metadata.

První šestitestový kandidát: pět PASS, jeden FAIL, protože audit očekával
sémantickou chybovou zprávu, kterou failure_result nepublikuje. Test nyní
ověřuje skutečný RuntimeError a přesné místo chyby; samostatná reprodukce
potvrzuje MON-03. Neoslabuje test7.5s expirace ani produkční failure cestu.
Druhý kandidát pro skutečný evidence_worker použil e.sqlite; produkční
storage kontrola vyžaduje evidence.sqlite, takže se k writer gate vůbec
nedostal. Fixture opravena na skutečné jméno, čekání/ACK/recovery aserce
zachované. Původní skripty a logy zůstaly v soukromé evidenci.

Hypotéza zpětného datování nového počasí byla odmítnutá: weather.poll volá
aktuální datetime.now až po převzetí odpovědi, nikoli čas starého planner
pozorování. Není z toho nový nález. Pasivní statistická povaha mapy P/UI,
monitorovací stale stavy a částečné plány byly odlišeny od fyzických povelů.

## Pořadí před povolením LIVE

1. Opravit a znovu otestovat N06-03/N06-04/REC-02 a integrity DATA-03/04;
   MON-03 a UI-01 odstranit, aby obsluha viděla skutečný stav.
2. Specifikovat autoritu cílového SOC/priority, fyzické limity, souběhy a
   vlastnictví původních automatizací. Schválené hodnoty neodvozovat z modelu.
3. Implementovat a ověřit LIVE-01/LIVE-03: samostatný intent adaptér,
   nezávislý device timeout/readback, nouzový stop a konflikt vlastníků.
4. Řízený hardwarový test ztráty HA/RPi/sítě, restartu, starého povelu,
   změny času, fází, souběhu EV/baterie a předání. Pouhé sledování stínu nestačí.
5. Přezkum konkrétních důkazů a omezené nasazení s prokazatelným návratem.
   Datum samo není akceptační kritérium. Audit žádný fyzický režim nezapíná.

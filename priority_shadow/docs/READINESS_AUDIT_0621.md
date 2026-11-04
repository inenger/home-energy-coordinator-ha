# Audit připravenosti 0.6.21 — 4. 11. 2026

**Verdikt: NE pro fyzické řízení.** Verze je pouze observe_only.
Úspěch testů ani jedna další stínová noc nejsou potvrzením fyzické bezpečnosti.
Vstupní veřejný commit: 707f2a136800fd9cee1deb790ac3274e1ce68bb2.
Audit nemění runtime, automatizace, tarif, rezervy, priority ani historii.

## Metoda a meze

Čtení produkčního vstupního bodu a návazností: sběr, RAM rozhodnutí,
IPC, persistence, outbox, monitoring, výpočet fází, model SOC a obnova.
Cíleně znovu spuštěno 68 existujících testů: izolace, režimy, preflight,
RAM regulátor, okamžitá alokace a sběr. Všechny prošly.
Nové protipříklady níže přesto reprodukují vady: dosavadní sada je nepokrývala.
Syntetické sondy nepoužívají HA klienta, skutečné měření ani fyzické povely.
Provozní ověření a jeho soukromé podklady zůstávají na cílovém zařízení.
Žádný z níže uvedených hypotetických poruchových stavů není tímto tvrzen
jako nově pozorovaná havárie živé instalace.

## Nálezy

| ID | Závažnost | Zjištění a důkaz | Důsledek / podmínka uzavření |
|---|---|---|---|
| R21-01 | Blokátor fyzického provozu | config.yaml povoluje jen observe_only; priority_observer.main jiný režim odmítá; ram_control.intent vrací wire_command=null a physical_control_ready=false. | Chybí akční adaptér, ověřený protokol, potvrzení povelu a fyzický nouzový návrat. Nejde o funkci dostupnou zapnutím volby. |
| R21-02 | P1, reprodukovaná vada obnovy | SnapshotCollector.priority_states odmítá i novou čerstvou cache, dokud existuje pending_failure. run_loop žádá odstranění až podle evidence ack; worker ack vydává po persist_batch a outboxu. | Po přechodném výpadku vstupů se RAM neobnoví, pokud nefunguje zápis/outbox. Oddělení diskového procesu dosud nezajišťuje nezávislost obnovy. Nutno oddělit spotřebování chyby řídicí vrstvou od trvalého potvrzení evidence; zachovat restartovou stopu i generace a dvě nové ověřené sady. |
| R21-03 | P1, reprodukovaná vada evidence | MemoryControl.annotate_loss mění i již uzavřenou relaci aktuálního dne. persist_batch správně odmítá změnu trvale uzavřeného záznamu. evidence_worker opakuje stejný pending batch před dalšími. | Ztráta dávky po trvalém uzavření může trvale zablokovat FIFO chybou CLOSED_CONTROL_SESSION_CONFLICT. RAM pokračuje, deník ne. Ztrátu ukládat jako oddělený neměnný doklad, ne přepisem uzavřené relace; ověřit další den, restart i recorder. |
| R21-04 | P1, mez odolnosti | EvidenceBridge a MonitorBridge odhalí skončený proces, ale nemají automatický restart potomka. | Rodič může běžet degraded bez automatické obnovy ukládání či monitorů. Nutný dohled s omezenými restartovacími pokusy, bezpečný bootstrap, idempotence a explicitní eskalace. |
| R21-05 | P2, mez diagnostiky | MonitorBridge.snapshot kontroluje is_alive, nikoli stáří poslední odpovědi nebo přírůstek publikací. Živý zablokovaný proces může vracet poslední status ok. | Doplnit samostatný monotónní watchdog komunikace/publikace. Nejde o důkaz současného zaseknutí ani běžného HTTP timeoutu. |
| R21-06 | Blokátor fyzického provozu | instant_fill uvádí transient_margin_a=0 a odhad P/UI; RAM kontroluje HA reporty, ne nezávislý fyzický heartbeat. | Výpočet do 25 A není ochrana jističe. Změřit fáze, znaménka, odezvu a zátěžové skoky; stanovit a ověřit provozní rezervu. |
| R21-07 | Blokátor fyzického provozu | Virtuální vlastnictví pouze vytváří would_disable_automation; skutečné automatizace se nevypínají. | Nutná skutečná arbitráž jediného vlastníka a kontrolované předání včetně vnějšího zásahu/restartu. |
| R21-08 | Blokátor rozsahu funkce | ram_control odmítá alokaci vyžadující omezení EV důvodem requires_ev_control_not_implemented. | Priorita baterie může navrhnout řešení vyžadující chybějící EV adaptér. Ověřit celé zařízení a priority, ne pouze součet výkonů. |
| R21-09 | Blokátor fyzické validace | capabilities uvádí neověřenou hranici AC/DC, mapování Mode8, firmware a timeout; soc_energy označuje účinnost jako neověřený předpoklad. | Ověřit příkaz, DC převod, limity BMS/měniče a skutečné vypršení i při pádu procesu, HA, sítě a RPi. Logické expires_at přístroj samo nezastaví. |
| R21-10 | P2, riziko mylné interpretace | collection_health=ok lze získat při chybějícím modelu a nulovém cíli po celé okno. instant-max-fill má cíl 100 %, ekonomický cíl je poradní. | Připravenost posuzovat zvlášť podle převzetí, platného výkonu, pokrytí, důvodů blokace a skutečného výsledku. Zdravý sběr není běžící regulace ani splněný ekonomický plán. |
| R21-11 | P2, provozní dluh | Časování Linux/Python nemá hard real-time záruku; fronta má 64 dávek a 512 KiB na dávku. Při přeplnění se přizná ztráta. | Ověřit poruchy disku a IPC, výpadky napájení a obnovu. Ani omezená fronta nezaručuje bezeztrátový deník při libovolně dlouhé poruše. |
| R21-12 | P3, dokumentace | Úvod README stále popisuje 0.6.19 se sdílenou koordinací SQLite, přestože běží oddělená architektura 0.6.20+. | Opraveno v tomto dokumentačním auditu: přidán aktuální přehled a označení historických kapitol. |

Závažnost P1 zde znamená vadu dostupnosti/obnovy pozorovací aplikace,
nikoli prokázané nebezpečné fyzické sepnutí. Aktuální aplikace nemá
fyzický akční výstup. Bezpečný stop při neznámých vstupech musí zůstat;
R21-02 není požadavek ignorovat skutečný výpadek měření.

## Spustitelný důkaz a slepé cesty

Z kořene repozitáře:

```sh
python3 scripts/audit_readiness_0621.py
```

Výstup defect_reproduced=true je potvrzení známé chyby, **nikoli**
potvrzení připravenosti. První sonda vede produkční run_loop přes RAM,
FIFO persistence a outbox: nejprve trvale uzavře relaci, potom ztratí dávku
a reprodukuje dva pokusy o stejný konfliktní zápis. Původní relace je zachována.
Druhá používá skutečnou SnapshotCollector.priority_states, čerstvou syntetickou
cache a chybějící potvrzení evidence: po jedné přechodné chybě se všech
17 následujících čerstvých kroků odmítne a cíl zůstává nulový.

Dosavadní test přetečení anotoval ztrátu před trvalým uzavřením, a proto
R21-03 neodhalil. Dosavadní test výpadku v izolované smyčce používal klienta
bez trvalé pending_failure západky, a proto neodhalil R21-02.
Počáteční sonda R21-02 používala skutečný čas chyby proti syntetickému datu;
následná verze sladila first_at se syntetickými hodinami a výsledek zopakovala.
Tato metodická oprava není nová chyba aplikace. Pomocné sondy navíc ověřily
odhalení mrtvého procesu, chybějící stáří monitorovací odpovědi a zdravý sběr
bez dostupného energetického modelu. Neprokazují četnost skutečných poruch.

## Podmínky dalšího rozhodnutí

1. Opravit R21-02 a R21-03 s regresí přes produkční řetězec včetně restartu,
   trvalého záznamu, outboxu a čtení recorderu; ověřit zotavení pomocných procesů.
2. Získat úplnou novou noční relaci na konkrétním vydání: skutečné virtuální
   převzetí, důvody každého stopu, čerstvost vstupů, pokrytí, energie AC/DC,
   uzavření a shodu deníku s recorderem. Noc bez převzetí není úspěšný test.
3. Samostatně dokončit a ověřit fyzický adaptér, watchdog zařízení, readback,
   fáze, limity, rezervy, výhradní vlastnictví, předání a ruční nouzové ukončení.
4. Pro ekonomický plán potvrdit požadavky a rezervu, ověřit modely a srovnat
   splněné potřeby i konečnou zásobu. Okamžitý max-fill toto nenahrazuje.

Jedna stínová noc ověří pouze část bodu 2. Bez bodů 1 a 3 nelze schválit
fyzický ostrý provoz; audit žádnou takovou aktivaci neprovedl.

# 0.6.22 — obnova sběru a evidence bez zastavení řídicího stavu

Vstupem je audit0.6.21, veřejný head5a9ae778b2c66a19082c2225c1aa671556657cc4.
Původní nálezy a sondy jsou zachované v READINESS_AUDIT_0621.md
a scripts/audit_readiness_0621.py. Historická sonda očekává vady0.6.21;
na novém runtime se k ověření opravy používají regresní testy níže.

Pouze observe_only. Žádný fyzický adaptér, změna registrů, automatizací,
tarifu, rezerv či priorit. Fyzická připravenost zůstává false.

## Opravy R21-02 až R21-05

| Nález | Nové chování | Zachovaná ochrana |
|---|---|---|
| R21-02: disk blokoval obnovu | Chyba má zvlášť převzetí regulátorem v RAM a trvalé potvrzení evidence. Po provedeném stopu consume_failure uvolní čerstvou cache nezávisle na disku. Produkční sběr používá defer_failure_persistence; persistenci chyb i ack dělá pomocné vlákno. | Přesná generace, skutečný stop a dvě nové koherentní sady. Stará/neplatná data se nepovolí. Durable latch se smaže až po uloženém stopu a outboxu. Po restartu se nepotvrzená chyba znovu převezme. |
| R21-03: konflikt po uzavření | Pozdější ztráta nepřepisuje ani RAM snapshot uzavřené relace. Kumulativní doklad ztráty zůstává samostatně v neměnném control_evidence_batches.payload a v evidence_pipeline.loss. | Ochrana neměnných řádků zůstává. Žádné mazání, zpětné plnění ani vydávání ztracených dat za úplná. |
| R21-04: mrtvý pomocný proces | Samostatný dohled obnovuje skončený nebo neodpovídající proces v nové generaci IPC. Evidence drží nepotvrzené dávky v omezené RAM až do durable ack a předává je po obnově znovu ve stejném pořadí/runtime/seq. | Regulátor se nerestartuje ani nenačítá nový seed. Idempotence zabrání duplicitám i po commitu před ztraceným ack. Nejvýše tři automatické obnovy za běh; pak explicitní degraded. |
| R21-05: falešně zdravý zaseknutý monitor | Heartbeat procesu a monotónní stáří komunikace se sledují odděleně od postupu publikací. Čekající publikace bez postupu nebo chybějící heartbeat přes30s znamenají degraded a obnovu pomocného procesu. | Žádné spoléhání na posun nástěnných hodin. Nečinný zdravý proces pravidelně odpovídá. Nový monitor znovu převezme poslední výsledek. |

Starý potvrzený uzavřený deník se nikdy nepřepisuje. Ztráta dávky mimo noční
okno sama nedokazuje chybějící noční vzorky; doklad uvádí počty ztracených
dávek/událostí/vzorků. RAM stav regulátoru má vlastní kontinuitu nezávislou
na tom, kdy se tento doklad podaří uložit.

Celé IPC předávání evidence je nově v pomocném vlákně. Řídicí krok jen
omezeně uloží dávku do paměti. Kapacita je64dávek, jednotlivě nejvýše512KiB;
při přeplnění se ztráta přizná. Nejde o záruku bezeztrátového uložení při
libovolně dlouhé poruše disku nebo při výpadku napájení.

## Regresní důkazy

```sh
cd priority_shadow
PYTHONPATH=.:tests python3 -m unittest test_recovery_0622 -v
```

Nové případy ověřují:

- Produkční run_loop a skutečný SnapshotCollector: přechodná chyba → stop →
  první nová sada ještě0W → druhá obnoví výkon i bez durable ack → pozdější
  přesný flush stopu do SQLite a outboxu. Restart před ack chybu znovu převezme.
- Ztrátu po již trvale uzavřené relaci, idempotentní flush, samostatný doklad
  ztráty a pokračování FIFO další den bez změny původního uzavřeného záznamu.
- Novější generaci chyby proti opožděnému consume, stále vadný vstup a starou cache.
- Skutečně zablokovaný fsync pomocného vlákna při pokračujícím produkčním sběru.
- Omezenou RAM frontu a absenci IPC put v řídicím kroku.
- Skutečný spawn proces ukončený po commitu před ack: automatická obnova,
  opakování dávek bez duplicit, shodná finální relace a nepřerušený RAM výpočet.
- Skutečně zamrzlý ukládací proces: výměnu IPC a přesné předání nepotvrzených dávek.
- Ukončení aplikace během obnovy bez pozdějšího spuštění dalšího potomka.
- Skutečný pád monitorovacího procesu, opublikování posledního výsledku po
  obnově, diagnostiku zaseknuté publikace a vyčerpání omezeného počtu obnov.

Stejné dva hlavní nové regresní testy byly spuštěny proti původní0.6.21:
obnova selhala18místo1chybového kroku a uzavřený zápis skončil
CLOSED_CONTROL_SESSION_CONFLICT. Tyto záměrné neúspěchy jsou důkazem,
že nové regrese vady zachytí; nejsou selháním opraveného vydání.

## Meze a provozní ověření

Čísla úplných testů, cílové nasazení, hash zdrojů a stav skutečných monitorů
se dokládají samostatně pro finální sestavení. Změna zdrojů ani zelené CI
samy nepotvrzují nasazení. Během ověřování se nepoužívá fyzické řízení.

Obnova procesu neumí opravit trvale vadný disk ani zaručit plánování Linuxu.
Po třech automatických obnovách je potřeba provozní zásah; stav to přizná.
Výpadek napájení může zničit nepotvrzenou RAM frontu. Restart nikdy
nepokračuje ve staré lease; fyzický watchdog zařízení stále chybí.

## Průběh ověřování

První implementace prošla9novými testy, plnou sadou508shadow+164legacy
a20kontrolami. Následná kontrola souběhu shutdown/obnova přidala zábranu
startu potomka po zastavení dohledu a dvě další regrese. Před závěrečnou kontrolou nová
sada měla11případů; plná shadow sada510. Staré selhávající reprodukce
jsou zachované odděleně od výsledků opraveného vydání.

### Závěrečná korekce kandidáta před předáním

Dvanáctá regrese odhalila, že nový idle heartbeat mohl přepsat degraded
po chybě přípravy monitoru starým stavem publisheru ok. Nejde o původní
R21-02/R21-03, ale o vadu první implementace dohledu. Zachovaný nový test
nejprve selhal ok!=degraded. Monitor worker nově uchovává chybu přípravy
přes všechny heartbeat zprávy a vymaže ji až po úspěšném submit dalšího
výsledku. Dokud příprava selhává, heartbeat nepotvrzuje zdravou publikaci.

Finální kandidát stejného vydání0.6.22 má12nových regresí a511shadow
testů. První sestavení nebylo vydáváno za dokončené předání; finální
zdroj a nativní sestavení se znovu ověřují podle přesného Git stromu.

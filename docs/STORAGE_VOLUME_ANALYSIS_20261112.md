# Objem dat, redundantní zápisy a návrh retence – 12. listopadu 2026

**Rozsah:** samostatný HA doplněk `priority_shadow`, verze `0.6.31`.
**Zdroj:** konzistentní *přenosná kopie* `/share/home-energy-priority-shadow/evidence.sqlite`,
vytvořená 12. 11. 2026 v **07:24:18 Europe/Prague** (06:24 UTC).
Zdrojový kód: `main` commit `c9f9a1f3fbda94f2b2a4cbe0496e8a6fe17ed8d4`.
**Metoda:** `sqlite3 mode=ro&immutable=1`, agregace všech 43 tabulek,
`length(BLOB/text)` a délky numerických polí, časové přiřazení podle dne
pozorování (`day` / čas v Prague) nebo prvního zachycení, samostatně
`dbstat` pro skutečnou velikost současné databáze včetně indexů.

Srovnání se týká dat dostupných v **kopii v 07:24**, nikoli přímého
aktuálního obsahu živého kontejneru po tomto čase. Data denního
podkladového exportu nejsou veřejná; soukromé agregace jsou pouze na RPi.
**1 MB = 1 000 000 B, 1 MiB = 1 048 576 B.**

## Výsledek

| Metrika | Výsledek |
|---|---:|
| Poslední celý místní den – **11. 11. 00:00–24:00** | **24,423 MB** nově evidovaných logických bajtů záznamů |
| Z toho komprimované SQL BLOB payloady 11. 11. | **23,636 MB** |
| Počet záznamů přiřazených 11. 11. | **12 743** |
| Sedm úplných dnů 5.–11. 11., průměr/den | **29,896 MB/den** |
| Sedm dnů: minimum / medián / maximum | **23,743 / 30,890 / 35,341 MB/den** |
| Klouzavých 24 h do snímku 07:24 (časově označené tabulky) | **26,908 MB** / 16 153 záznamů |
| Velikost snímku SQLite jako souboru, včetně indexů | **502,485 MB (479,207 MiB)** |
| Součet logických dat všech aktuálních řádků | **452,472 MB** |
| Rozdíl (indexy + SQLite stránky/režie) | **50,013 MB** |
| Samotné SQLite indexy (dle `dbstat`) | **15,385 MB** |
| Aplikační kvóta `storage_limit_mb=2048` | **2 147,484 MB (2 GiB)** |
| Čerpání kvóty tímto snímkem | **23,4 %** |
| Teoretický přepočet průměru na btree stránky | **cca 33,2 MB/den** (odhad, ne naměřené SSD I/O) |

**Metodická hranice:** to jsou bajty **uložených obsahů přiřazených k datu
pozorování**, nikoli skutečné fyzické bajty zapsané na disk za den.
Pro přesný reálný denní write I/O je nutný průběžný měřič
`/proc/[pid]/io` / blokových zápisů, SQLite WAL checkpointů a plných
kopií. Starší srovnatelná nativní záloha byla mezitím odstraněna
z `/backup` a není dostupný párový snapshot souborové velikosti přesně
24 h zpět; proto **neoznačujeme aproximaci 33,2 MB za změřený růst
souboru**.

## Sedm úplných dní (lokální čas Europe/Prague)

| Datum | Záznamů | Logicky uložená data | Komprimované BLOB |
|---|---:|---:|---:|
| 5. 11. | 15 112 | 35,341 MB | 34,447 MB |
| 6. 11. | 13 070 | 23,743 MB | 22,982 MB |
| 7. 11. | 14 842 | 30,890 MB | 30,011 MB |
| 8. 11. | 13 548 | 35,316 MB | 34,502 MB |
| 9. 11. | 13 386 | 34,619 MB | 33,822 MB |
| 10. 11. | 12 690 | 24,940 MB | 24,203 MB |
| **11. 11.** | **12 743** | **24,423 MB** | **23,636 MB** |
| **Průměr/den** | — | **29,896 MB** | — |

Rozdíly mezi dny nejsou pouze v pravidelném sběru. Největší kolísání
způsobuje počet zapsaných plných `soc_decisions`.

## Kde vznikají data

| Tabulka | 11. 11. řádků | 11. 11. objem | Průměr MB/den za 5.–11. 11. | Trvalé místo v nynější DB |
|---|---:|---:|---:|---:|
| `journal_transport_outbox` | 1 441 | 7,774 MB | 7,769 MB | 106,689 MB |
| `priority_samples` | 1 440 | 5,638 MB | 5,730 MB | 103,510 MB |
| `soc_decisions` | 139 | 5,455 MB | 10,687 MB | 186,253 MB |
| `ram_control_samples` | 1 440 | 2,667 MB | 2,531 MB | 37,011 MB |
| `night_samples` | 1 549 | 1,892 MB | 1,926 MB | 37,368 MB |
| `control_evidence_batches` | 2 855 | 0,391 MB | 0,392 MB | 5,042 MB |
| `soc_observations` | 1 331 | 0,259 MB | 0,245 MB | 8,024 MB |
| `journal_transport_receipts` | 1 441 | 0,150 MB | 0,150 MB | 2,191 MB |
| Další tabulky | — | 0,197 MB | proměnlivé | zbytek |

Prvních **pět tabulek tvoří cca 96 %** objemu 11.11. `Trvalé místo`
je `dbstat` z celého období: jde o alokované B-tree a indexy,
nikoli aktuální jednodenní přírůstek.

## Prokázaná redundance a možnosti zlepšení

### DATA-05 — opakované verzované podklady v SOC rozhodnutích

Skutečných `139` záznamů `soc_decisions` z 11.11 má v
`forecast_versions` jen **8 unikátních obsahů** (solární předpověď
a tarifní verze). Pro jejich opakované ukládání:
**43,140 MB rozbalených** dat, při samostatném zlib na každý field
**2,726 MB**, proti **0,156 MB** pro 8 jedinečných zlib obsahů.
Izolovaný potenciál normalizace tohoto pole je **2,570 MB/den**
na tomto konkrétním dni. Ve skutečné komprimované celé SQL row
může být úspora jiná; vyžaduje variantní benchmark a regresi.

`calibration_summary` v téže tabulce: 139 kopií,
**3 unikátní obsahy**, izolovaný compressed field
0,262 MB proti 0,006 MB, potenciál **0,256 MB/den**.

`priority_samples.session`: 1 440 kopií, **2 unikátní obsahy**,
izolovaný compressed field 1,112 MB proti 0,002 MB, potenciál
**1,110 MB/den**.

Dohromady **3,936 MB/den izolovaného potenciálu** na zvoleném dni,
nikoli garantovaná skutečná úspora databáze. Správný mechanismus:
immutabilní `content-addressed objects` s `sha256`, transparentní
rekonstrukce **identicky kanonického původního payloadu**, včetně
`soc_evidence.verify`, replay, model version, as-of času a
`decision_hash`. Neodstraňovat pole z auditních rozhodnutí bez
úspěšné rekonstrukce a kryptografické rovnosti.

### RET-03 — potvrzený outbox je uložen i po zpracování

`journal_transport_outbox` má v celé SQLite **20 154** chunků,
`journal_transport_receipts` má také **20 154** potvrzení.
Každý z dní 8.–11.11 měl všechny chunky potvrzené, např.
11.11 **1 441/1 441 ACK**, přesto zůstává v live SQL
**7,774 MB** denních chunků. Obsah je odvozen z evidence
`ram_control_samples/events/session` a navíc publikován do
HA Recorderu. Nejde o chybu FIFO; kopie je nutná pro
obnovu, reconnect a historické replay při zániku Recorderu.

Po **prokázané archivaci a ověřené read-through cestě** lze
starý potvrzený outbox přesunout do immutable denního archivu.
V horké DB ponechat monotónní `last_seq`, potvrzení,
transport cursor, stream epoch a neskončené/nepotvrzené chunky.
**Nikdy nemazat dávky jen proto, že mají ACK**:
aktuální `HIST-01` doložil, že Recorder už staré dny neumí vrátit.

### DATA-06 — identická provenience v různých tabulkách

Za 11.11 jsem porovnal 1 440 dvojic stejných časů
`priority_samples` a `ram_control_samples`. Pole
`collection_snapshot` je **identické ve všech 1 440/1 440 případech**.
Je to skutečně opakované uložení téhož důkazu, ne ale důvod
smazat samostatný model priority nebo virtuálního řízení.
Vhodná je společná adresovaná evidence s odkazem,
nikoli slepé odstranění jedné tabulky.

### RET-02 — plné přenosné kopie každých 6 hodin

Živá konfigurace 12.11 potvrzuje
`portable_backup_interval_s=21600`. `priority_maintenance.Maintenance`
volá `priority_observer.backup()`, která přes
`sqlite3.Connection.backup` **přepíše celý přenosný SQLite
soubor** a atomicky vymění `evidence.next.sqlite` za
`evidence.sqlite` mimo noční okno.

Při 502,485 MB na kopii znamenají **čtyři kompletní přepisy
za 24 hodin až 2 009,94 MB logických backup zápisů**.
Je to **model podle nastavení a velikosti snímku**, nikoli
přímý záznam počtu kopírování za poslední den a nikoli růst
databáze o 2 GB denně. Významně se to liší od
cca 29,9 MB nové evidence za den. Navíc přispívají nativní
Supervisor zálohy, případné offsite přesuny a skutečné
SQLite WAL/commit zápisy; jejich reálný fyzický denní I/O
nebyl tímto auditem změřen.

**Nezkrátit obnovitelnost bez náhrady.** Ponechat současných
6 h do vybudování testované **inkrementální/blokově
deduplikované** kopie nebo konzistentního WAL-aware snapshotu
s rollback/restore. Měřit skutečnou frekvenci, runtime, bajty
čtení/zápisu a zatížení diskového subsystému.

## Co zatím neomezovat

- `night_samples` (cca 1,9 MB/den): vzorky kolem aktivního nočního
  okna mají vysokou důkazní hodnotu pro první dvě 03:00 sady,
  fáze, chybové stavy a pozdější regresní replay.
- `soc_decisions`: uchovat přesný vstup, model, varianty,
  zdrojovou verzi předpovědi i decision hash; změnit jen
  fyzické znovuukládání identických verzí.
- `priority_samples`: min. posledních 7 dní využívá
  `phase_budget.from_db`; jiné části potřebují celé dny
  pro souhrny a SOC/house calibration. Nepřepnout na 5min
  bez vyhodnocení dopadu na špičky a kvalitu fitu.
- Nepotvrzené `journal_transport_outbox`, `control_analytics_pending`,
  originální `control_evidence_batches`/receipts, `objects/versions`,
  SOC modely a data použitá v původním rozhodnutí. Zachovat FIFO,
  nefalšovat original `issued_at` a `available_at`.
- HA Recorder není permanentní úložiště historie;
  v minulém auditu pro některé starší dny vracel 0,
  ačkoli durable SQL chunky existovaly.

## Navržená retenční politika – bez ztráty surových dat

| Třída | Živé SQL (HOT) – cílový stav | Archiv – cílový stav | Podmínka |
|---|---|---|---|
| Detailní `priority_samples`, `ram_control_samples`, `night_samples` | 30 úplných dnů | **Všechny původní záznamy bez expirace** v denních immutable archivech | Jen po indexaci a úplném replay starého dne |
| `soc_decisions` včetně všech vstupů/variant | 30 dnů, transparentní deduplikace | Bez expirace, plná hash-rekonstruovatelná historie | Zachovat kanonický decision hash a as-of provenienci |
| Již ACKed `journal_transport_outbox` | Do uzávěrky dne + 7–30 dnů bezpečnostní okno | Kompletní originální chunky + receipts; přes denní read-only API | Nejdřív vyřešit HIST-01; nepřerušit global seq/cursor |
| Pending/nepotvrzený outbox, `control_analytics_pending`, loss/ACK epoch | **Bez časové retence** | Zálohovat a replay, nekompaktovat před potvrzením | Priorita integrity FIFO před kvótou |
| `objects`, `versions`, SOC modely a calibration baseline | Vše potřebné pro aktivní model a ≥30dnů replay | Bez expirace + reference index podle hash | Žádné dangling reference, FK, předpověď známá až od `available_at` |
| Denní/měsíční souhrny, kalibrační agregáty, alarmy | Bez nutné expirace (malý objem) | Dlouhodobě, minimálně 5 let | Původ a pokrytí, unknown není nula |
| Plná přenosná záloha | 6 h do náhrady za testovanou deduplikovanou/incremental | Offsite oddělená verifikovaná kopie | Neměnit RPO bez testu a ochrany live DB |

**30 dní je cíl, nikoli schválení okamžitého mazání**:
nejprve je nutné zjistit všechny závislosti kalibrace/replay
na delším horizontu. Počítač bez archivační čtecí vrstvy
musí ponechat současnou historii a pouze varovat při
přibližování kvóty. Kompletní archivy ukládat jak lokálně,
tak mimo RPi (např. uživatelský OneDrive) s kontrolou po přenosu.
Vyšší retence raw historie je ekonomicky přijatelná:
dnešní **~33,2 MB/den** očekávaného přírůstku btree
představuje orientačně **1,0 GB / 30 dnů** a
**12,1 GB / rok**, bez dalších záloh a kopií.

### Bezpečný archivní workflow

1. Po uzavření a ACK noci vyhodnotit úplnost dne:
   tabulky, schema/software version, counts, min/max seq,
   porovnání všech receipt, last committed ACK a stop/event boundaries.
2. Z **konzistentního snapshotu** vytvořit immutable denní
   archiv s `manifest.json` a `SHA-256` každého souboru,
   hash-chained origin and typed source timestamps.
3. Otestovat izolovaný restore a replay:
   `soc_evidence.verify`, denní souhrn, phase budget,
   UI přístup ze starého dne po purge Recorder, obsah všech
   chunků a koherentní původní časy.
4. Zapsat lokální + nezávislou offsite kopii. Nesmí stačit
   pouze úspěšný HTTP upload: stáhnout kontrolní hash nebo
   testovat druhou stranu a mít recertifikaci archivu.
5. Teprve po splnění invariantu „2 ověřené kopie + skutečně
   funkční archive read API“ povolit odstranění pouze
   uzavřených, nepoužívaných HOT partitions. Ponechat watermark,
   index pro vyhledání dne a všechny neuzavřené přenosy.
6. SQLite `DELETE` samo o sobě soubor nezmenší. Plánované
   přebalení/`VACUUM INTO` pouze mimo kritické okno a
   se zajištěnou volnou kapacitou, checksumem a atomickým
   přepnutím až po úplné validaci. Žádný live SQL compaction
   pod blokujícím gate ve 03:00–05:00.
7. Kvótní alerty **60 %** (plán archivace), **75 %**
   (vyšší naléhavost), **90 %** (kritický stav).
   I bez možnosti mazat musí evidence zůstat fail-closed,
   nepředstírat úplnost a oznámit výpadky/loss.

## Horizont do dnešní kvóty, pouze plánovací odhad

Po přepočtu historických logických dat na současný poměr
celkových stránek SQLite (`1,110532×`) je odhad
**cca 33,2 MB/den**. Aktuální kvóta 2 GiB má podle
snímku přibližně **1 645 MB** volné kapacity
*uvnitř aplikační kvóty*. Při hypoteticky konstantním
růstu vychází hranice za **cca 50 dní**.
Nejde o čerstvě změřené write I/O ani o pevnou predikci;
počet SOC rozhodnutí kolísá (za některé dny 5 MB, jiné 16 MB).
Dříve než tato hranice může nastat změna modelu, chybové
retries nebo nový růst. Alarm má být založen na
fyzické současné `sqlite_bytes` a trendu, ne na jediném
kumulativním čítači.

## Rozhodnutí a co nebylo provedeno

Tento krok je **analýza a návrh**, nikoli implementace retence.
Žádné SQL řádky smazány, žádný WAL checkpoint vynucen,
žádná automatizace či fyzický povel změněn,
`observe_only` zůstal nastaven. Soukromá auditní data
(soupisy tabulek, individuální distribuce a payload hash
analýzy) zůstávají pouze na RPi v
`/share/hec-recovery/analysis-20261112/`.

**Nová ID:** `RET-02` (frekventovaný full snapshot a I/O),
`RET-03` (trvalý ACKed outbox v live DB),
`DATA-05` (opakované forecast/calibration/session),
`DATA-06` (stejné collection_snapshot ve dvou doménách).
Dřívější `RET-01` a `HIST-01` zůstávají otevřené;
jejich důkazy tento report rozšiřuje. Případné runtime
úpravy vyžadují samostatnou verzi, regresní suite a
provozní průkaz, nikoli změnu textu „OPRAVENO“.

# Audit jednotlivých hodnot a návrh 7denní retenční politiky

**Datum:** 12. 11. 2026 (Europe/Prague)  
**Rozsah:** Home Energy Coordinator, samostatný doplněk `priority_shadow` 0.6.31, režim `observe_only`  
**Zdrojový commit před auditem:** `3e188301ab4cf37ee31746e2d8d92f6464f310e7`  
**Podklad:** skutečný konzistentní portable SQLite snapshot pořízený 12.11. v 07:24 CET na RPi. Všechny pokusy jsou read-only; žádné živé SQL či fyzické řízení se nemění.

## Rozhodnutí

**7 dnů pro detailní raw data je smysluplné. Trvale ponechat jen důležité výsledky, modely, skutečné události a podklady nutné k ověření trvale uložených výsledků.** Původní návrh *30 dnů HOT + všechny raw navždy* je tímto novým zadáním **nahrazen**, ne realizován. Sedmidenní purge **zatím nesmí být zapnutý**: přerušil by existující modely s 14, 21, 45, 60, 90 a 366denními čtecími horizonty. Retenci lze nasadit až po přesměrování všech spotřebitelů na kvalitní hodinové/denní agregáty a permanentní verze.

## Měřicí metoda a hranice důkazu

- Skutečná SQLite kopie obsahuje **43 tabulek**; z nich mělo **23** v testovaném výřezu měřitelné řádky. Podrobná neveřejná inventura: **2 935 odlišných cest k polím** (včetně zanořených struktur do hloubky 3), metrika četnosti, velikosti, jedinečnosti, typů a *indicie* výskytu v Python/JS kódu. Počty shod se zdrojovými literály **nejsou důkazem**, že je pole nepotřebné; jsou možná dynamická použití a auditní replay.
- Veřejná [filtrovatelná matice](FIELD_RETENTION_POLICY_MATRIX_20261112.csv) obsahuje **384 jednotlivých top-level JSON polí a 23 tabulkových položek bez v daném dni pozorovaného payloadu**, pokrývá všech **43 tabulek**. Ke každé položce dává návrh zacházení, dobu retence a nutný regresní důkaz. Zanořená soukromá metadata/konkrétní identifikátory entit nebyla zveřejněna; plný 2 935položkový inventář je jen na RPi.
- Snímek není živá DB po 07:24. Den 11.11. znamená data **přiřazená tomuto dni**, nikoli fyzické množství zápisu na SSD přesně v daném dni. 1 MB = 1 000 000 B.
- [Dřívější souhrnná analýza](STORAGE_VOLUME_ANALYSIS_20261112.md): **11.11. 24,423 MB / 12 743 řádků**, 7denní průměr **29,896 MB/den**, klouzavých 24h **26,908 MB**. DB soubor **502,485 MB**, fyzická 2GiB aplikační kvóta. Proti tomu je samostatně nutné počítat full copy 6h a přepisované SQL session/state řádky.

## Kam jde 30 MB denně

| Doména | 11.11. uložené řádky | 11.11. MB | Průměr 5.–11.11. MB/den | Návrhové rozhodnutí |
|---|---:|---:|---:|---|
| `soc_decisions` | 139 | 5,455 | **10,687** | Oddělit *issued at*, výsledek a verzované podklady; permanentně jen materiální rozhodnutí a výjimky |
| `journal_transport_outbox` | 1 441 | 7,774 | **7,769** | ACKed outbox není historický archiv; po rekonstruovatelném čtení ponechat jen nezpracované a krátké bezpečnostní okno |
| `priority_samples` | 1 440 | 5,638 | **5,730** | Jeden kanonický snímek zdrojových měření + malé scénářové rozdíly |
| `ram_control_samples` | 1 440 | 2,667 | **2,531** | Odstranit duplicitní `input_reports`, ostatní stav zjednodušit, zachovat safety důkazy |
| `night_samples` | 1 549 | 1,892 | **1,926** | 7 dní skutečná měření/quality; pro delší horizont denní souhrn a hodinové agregáty |
| Ostatní | — | 1,0 | ~1,25 | Eventy, ACK, malé modely – většinu není potřeba škrtat |

## Zjištění na úrovni jednotlivých položek

### SOC rozhodnutí: silná a přesně ověřená duplicita

V den 11.11. obsahuje 139 rozhodnutí `forecast_versions` jen **8 jedinečných obsahů**. Pole má 43,140 MB po rozbalení; jednotlivě komprimované kopie 2,726 MB vs **0,156 MB unikátního obsahu**. `calibration_summary` má 3 unikáty / 139 záznamů; `calibration_context` a `house_validation` rovněž jen 3 unikáty.

**Provedený syntetický benchmark:** plně rekonstruovatelný způsob *content-addressed reference + SHA256 objekt* pro `forecast_versions`, `calibration_summary`, `calibration_context`, `house_validation`, `battery_energy_model`, `history_source`, `assumptions`; vždy měřena také velikost samotných unikátních objektů.

| Den | Původní zlib tabulka | Řádky s referencemi + unikátní objekty | Úspora |
|---|---:|---:|---:|
| 8.11. (644 rozhodnutí) | 15,954 MB | **4,471 MB** | **72,0 %** |
| 11.11. (139 rozhodnutí) | 5,440 MB | **2,374 MB** | **56,4 %** |

Je to **měřený výsledek navrženého formátu na historických BLOB**, nikoli ověřená SQL migrace, indexová velikost či write I/O. `soc_evidence.verify` ověřuje kanonický kompletní payload: původní `decision_hash` se nesmí přepočítat nad kompaktními referencemi. Před ověřením se musí plný původní payload **bitově shodně rekonstruovat**.

**Rozdělení hodnot:**

| Pole / skupina | Potřebujeme? | Rozhodnutí |
|---|---|---|
| `issued_at`, `day`, `status`, `decision_hash`, `model_version_hash` | **Ano** | Permanentně u materiálního rozhodnutí; u všech mezivýpočtů 7 dní |
| `target_soc_pct`, `selected`, `decision_reason`, `warnings`, `missing_inputs` | **Ano** | Permanentně při změně cíle, blokaci, anomálii, při prvním platném 03:00 a při závěru |
| `forecast_versions`, `calibration_summary/context`, `battery_energy_model`, `house_validation` | **Ano, ale ne kopírovat** | Jedinečné verzované objekty + SHA256 reference; ponechat, pokud je na ně trvalý odkaz |
| `candidates`, `timeline`, `forecast_periods`, `priority_alternatives` | Jen vybrané / pro 7denní diagnostiku | Vše 7 dní; trvale plné alternativy pouze pro skutečně důležité, označené rozhodnutí |
| `input_snapshot`, `power_budget`, `ev_observation` | Ano pro provenienci | 7 dní v detailu; pro trvalý rozhodovací bod zmrazit původní zdroje a potřebnou kvalitu |
| `mode`, `device_actions`, `policy`, další neměnné texty | Jako konfigurace, nikoli 139x | Verzovaný manifest + historicky významná výjimka; netvrdit fyzickou akci |

**Možné omezení četnosti:** v 8.11. bylo 644 vydaných rozhodnutí, ale jen 23 různých hrubých signatur (`status/target/model/reason/night_charge`); v 11.11. 139 rozhodnutí / 28 hrubých signatur. **Nejde o 23 nebo 28 úplně stejných plánů.** Rozdílné vstupy a vydaný čas stále mají význam. Navrhuji:
1. udržovat aktuální issued/expiry záznam pro `session_plan`, který nyní kontroluje **30minutovou čerstvost**;
2. trvale ukládat *material change*, první platný preflight/03:00, rozhodnutí použité v night/session/review, blokaci/revokaci, změnu modelu a závěrečný vybraný plán;
3. mezivýpočty v úsporných delta/metrics řádcích pouze 7 dní;
4. po přechodu na nový formát ověřit identické sekvence `session_plan`, revokace, audit, replay, edge cases a DST.

### Priority vzorky (1 440/den)

| Pole | Rozhodnutí |
|---|---|
| `at`, `day`, `priority`, `actual_ev_w` | **Ano: 7 dní** (čas, volba a skutečnost), změny priority trvale jako události |
| `inputs` | **Ano, ale jeden kanonický rámec.** Pro fázový výpočet explicitně nutné `grid_voltage_l1..3_v`, `grid_l1..3_w`, `inverter_l1..3_w`, `ev_l1..3_w`, `grid_l1..3_a` včetně `value,quality,age_seconds,last_reported`; ostatní potřebné hodnoty a jejich provenience přes sdílený rámec a oddělené agregáty |
| `variants` | **Ano pro kontrafaktuální model**, ale společná pole držet jednou; 7 dní detail, trvalá `priority_summaries` |
| `session` | **Ne 1 440x.** Za 11.11. jen 2 unikátní hodnoty v 1 440 kopiích. Uložit verzi jednou při změně a referencovat z řádku |
| `models` | **Ne každých 5 s ve formě plného stavu.** Rozdílové kroky a kontrolní checkpointy, konečný model trvale |
| `collection_snapshot` | **Ano jako jeden sdílený důkaz.** Neopakovat v `ram_control_samples` |
| `soc_initialized_at` | **Ne v každém řádku.** Stačí ve stavu relace/události při prvním získání platného SOC |
| `observed_ev_kwh_ac`, `observed_covered_s`, `gap_s` | **Ne v každém řádku jako trvalá data.** Denní finální počítadla a případné checkpointy |

První experiment: jen nahrazení `session` SHA referencí ušetřilo cca **4 %** celé tabulky. Samostatný *lean* experiment (jen 15 vstupních fázových kanálů se `value/quality/age/last_reported` + reference `session`) snížil tabulku 11.11. **5,577 → 3,212 MB**. **Tento lean formát zatím není kompatibilní** s potřebou dalších 9 vstupních kanálů z `ram_control`; jeho úspora se nesmí nekriticky sčítat s odstraněním `input_reports` bez nové společné tabulky.

### Virtuální řízení (1 440/den)

U všech 1 440 párů 11.11. a všech 1 443 párů 8.11. jsou **všechny vstupní klíče `ram_control_samples.input_reports` přesně shodné** s odpovídajícími `priority_samples.inputs` ve stejném okamžiku; u obou dní jde o všech **24 společných klíčů**. Tím je konkrétní cross-table redundance doložena, ne odhadnuta.

Kontrafaktuální komprese `input_reports_ref_at=at` místo celé kopie:

| Den | Původní `ram_control_samples` | Úsporné s odkazem na prioritní vstupy | Úspora |
|---|---:|---:|---:|
| 8.11. | 2,423 MB | **1,339 MB** | **1,084 MB** |
| 11.11. | 2,607 MB | **1,580 MB** | **1,027 MB** |

Tato změna vyžaduje zachovat původní kvalitativní stav i po restartu a po 7denní purge; referenční řádek musí být ve stejném atomickém důkazu.

- **Nutná 7denní data:** `at`, `phase`, AC/DC skutečnost a hypotetický limit, `reason`, `report_skew_s`, `new_frame`, `frame_signature`, `input_valid_until`, `intent_expires_at`, `input_errors` a kvalita fázových hlášení.
- **Trvalé pouze při významné události:** změna `manual_control`, `owner_reports`, `wallbox`, `intent_renewal`, blokace, výpadek, narušení as-of, bezpečnostní stav. Běžné opakování stejného stavu není trvalým analytickým výsledkem.
- **Jednou na verzi:** konstantní `policy`, `device_actions=0`, `persistent_writes=0`, `hardware_response_verified=false`. Nezakrývat případné budoucí nenulové odchylky nebo novou verzi policy.
- **Co nefunguje:** v testu „nahradit každý `manual_control` a `owner_reports` vlastním SHA objektem“ narostl objem tabulky **o 25–27 %**. Tyto položky mají časovou provenienci a nejsou dostatečně totožné; vhodnější je **event-on-change s ověřeným periodickým quality checkpointem**, ne vytvoření 1 440 nových SHA objektů.

### Noční vzorky a diagnostika

`night_samples.points` je cca 11,37 MB rozbalených dat v 1 549 řádcích (komprimovaná tabulka 11.11. cca 1,89 MB). Zdroje zahrnují napětí/proudy jednotlivých fází, SOC, FVE, house/EV výkon, režim měniče, denní čítače, forecast a timestampy.

- **Nutné 7 dní:** skutečná naměřená čísla, původní timestamp `last_reported`, status `valid/stale/unavailable`, mezera a pokrytí, start 02:59/03:00 a omezení fází; uchovat 5s kvalitu kolem událostí.
- **Nad 7 dní:** výsledné denní/hodinové statistiky `minimum/maximum/mean/energy/coverage/rejected_samples`, nikoli opakované objektové hlavičky.
- **Bez trvalého opakování:** dlouhé názvy `entity_id`, nezměněná definice jednotky, `schema_version`, statický popis zdroje; ty patří do verzovaného katalogu entit. Některé `last_updated` byly shodné po celý den – **nebrat je za známku čerstvosti**. Originální `last_reported` a původ nezmizí.
- `shadow`: ponechat po 7 dní vybrané návrhy vs. skutečnost, permanentně jejich **ověřený denní výsledek**, nikoli každý redundantní pětisekundový kompletní scénář.

### Přenosový outbox je workflow, ne finální historie

- 11.11. **1 441** uložených chunků / **1 441 ACK**. V celé kopii **20 154** chunků a **20 154** potvrzení.
- Obsah `data` tvoří přes 90 % raw JSON metadata těla přenosu; jeho původem jsou již lokálně zaznamenané `ram_control_samples/events/sessions`. Znovu ho ukládáme kvůli FIFO a asynchronnímu Recorder transportu.
- **Nepotvrzené nikdy automaticky neodstraňovat**. Pro potvrzené navrhuji nejprve zajištěnou read-through cestu z kanonických 7denních vzorků i při vyčištěném Recorderu, a pak krátkou transportní pojistku (např. 24 h). Zachovat nepřetržitý globální `seq`, originální digest, uzavřený den a epoch. Po 7 dnech může podkladové raw podle nové politiky skutečně expirovat.
- **Trvale uchovat** finální denní shrnutí, počet/fingerprint ACK, ztracené dávky, vzniklé chyby a důkaz uzávěrky; **ne všechny chunky**.
- Pokud chceme nejen méně trvale uložených bajtů, ale také méně *fyzických zápisů*, nestačí smazat ACKed outbox dodatečně: je třeba navrhnout **durable source pointer** místo druhého plného payloadu a otestovat možnost opakovat identický wire chunk po restartu.

### Ostatní tabulky – všech 43 pokryto v [matici](FIELD_RETENTION_POLICY_MATRIX_20261112.csv)

| Skupina | Navržená politika | Důvod |
|---|---|---|
| `soc_observations`, `environment_samples`, `standalone_ev_history`, `samples`, `control_samples` | Raw 7d; před expirační hranicí vytvořit kvalitativně úplné hodinové/EV session agregáty | Historické kalkulace mají 21–366d horizont |
| `control_evidence_batches`, `control_batch_receipts`, `control_analytics_pending` | Pending do potvrzení, raw diagnostika 7d, trvalá denní receipt/loss evidence | Ztráta nesmí být maskována jako úspěšné ACK |
| `priority_commands`, `ram_control_events`, `priority_events`, `control_events`, `failures` | Významné změny, důvody a chyby trvale | Malý objem, vysoká provozní hodnota |
| `priority_summaries`, `priority_summary_revisions`, `night_summaries`, `priority_day_audits/revisions`, `soc_reviews`, `daily_observed`, `analytics_versions` | Trvale | Skutečné energetické/ekonomické výsledky a ověřená kvalita |
| `soc_model_versions`, `objects`, `versions`, `calibrations`, `manifests`, `telemetry_mappings`, `standalone_imports` | Trvale, pokud jsou referencované; jinak bezpečný GC po ochrané době | Kryptografické vazby a původ původního rozhodnutí |
| `priority_runs`, `priority_sessions`, `ram_control_sessions`, `night_sessions`, `control_sessions` | Aktivní bez časového limitu; ukončený stav trvale zredukovat na konečný výsledek + důležité události | Úplná rekonstruovatelná restart/owner/lease historie |
| `journal_transport_meta`, `journal_transport_receipts`, `control_analytics_pending` | Nevyřízené bez expirace; staré pouze po důkazu posunutí ACK/cursoru a uzávěrce | FIFO, idempotence a restart bezpečnost |
| Prázdné historické tabulky ve vzorku dne 11.11 | Bez automatické změny | Prázdný 11.11. **nedokazuje nepotřebnost** celé tabulky nebo mimořádného stavu |

## Zásadní technický konflikt: modely potřebují historii delší než 7 dní

Současní čtenáři:

| Čtenář / funkce | Dnes používá | Potřebná náhrada při 7d raw |
|---|---|---|
| `phase_budget.from_db` | až 7d detailní priority/phase vzorky | posledních 7×24h high-res (bez dřívější purge) + nulová změna výpočtu, vč. DST |
| `priority.recent`, `control_journal` | až 14d přehledy | permanentní denní souhrny a poslední události, žádná potřeba všech raw |
| `shadow.py` | až 21d sample historie | hodiny/dny s min/max/coverage, nikoli fiktivní hladké raw |
| `calibration.py` | 45d surových `samples` | hodinový residual house-minus-EV/HP/immersion včetně úplnosti ≥90 %, dostupnost vzorků |
| `standalone_context.py` | 60d EV high-res stream | kompletní významné EV relace: start/end edge, čítače, ∆SOC, AC kWh, mezery |
| `analytics.py` | 45/90/366d sekvence a tarify | hodinové kWh a kvalita, 90d modelové statistiky, časově verzované tarify a denní řady |
| `soc_runtime.review` | předpověď vydaná před 03 a actual hourly | permanentně vybraný původní plán + hodinové counter/coverage; nelze si vymýšlet historické forecast |
| Lovelace karta | historie Recorder; někdy vymazané staré dny | čtecí vrstva pro 7d raw + trvalý denní přehled, explicitně „detail po 7 dnech expiroval“ |

**Nezbytné nové kompaktní datové produkty:**
1. `energy_hourly`: hodinové energetické součty W→kWh přes pokryté úseky, oddělené AC/DC, měřený max/min/rms, hodnota chybějících sekund, směr toku, časové hranice UTC/DST, kvalita a jednotky; 45–366d dle klienta.
2. `ev_sessions`: skutečně ucelené EV nabíjení (start inactive→active, ukončení, SOC a counter delta, AC kWh, počet výpadků a max gap), držet výsledek trvale.
3. `battery_cycle_evidence`: SOC změny, DC nabito/vybito, round-trip a bezpečnostní validace; trvale každou ověřenou kalibrační relaci.
4. `pv_forecast_scores`: předpověď *as-of*, skutečnost, clipping/limit, coverage, MAE a verzovaná korekce; permanentně denní/parametrizovaný výsledek.
5. `night_result`: 03–05 cílový a skutečný SOC, EV/baterie kWh, fázové špičky, náklady z ověřeného `sensor.cez_indi_cenik`, korektní HDO a original decision hash; permanentně.
6. `exception_ledger`: nové a změněné chybové kódy, stale timestamp, restart/lease, unapplied shadow command, unacked/loss, všechna relevantní prahy; trvale.

**Nulová, neznámá a nedostupná nejsou totéž.** Souhrn s nekompletním coverage se nesmí použít jako ověřená energetická skutečnost. Původní smluvní ceník ČEZ INDI je ověřený, ale jeho minulou platnost je nutné držet ve verzích při změně tarifu.

## Konkrétní sedmidenní retence

- **HOT RAW:** pouze 7×24h high-resolution dat; po 05:05 a uzavření noci spustit neblokující návrh GC. Když je aktivní/neuzavřená relace, pending queue nebo chybí validovaný agregát, danou část **neodstraňovat ani po 7 dnech**, zaznamenat důvod.
- **WARM:** hodinové zdrojově-kvalitní agregáty alespoň **366 dní**, ale jen z veličin nutných pro analytiku. Před 366d pak mohou expirovat hodinové řady, pokud jsou finální výsledky, trvalá EV/battery session evidence a denní souhrn uložené.
- **PERMANENT:** denní/roční agregáty, vybraná rozhodnutí a závislé verze, výsledky fitů/holdout, ceny a ekonomické výsledky, alarmy/incidenty, auditní hash a původ měření, dokončené EV/bateriové cykly.
- **PENDING:** vysoce prioritní výjimka. FIFO, nepotvrzený journal/outbox/analytic evidence a aktivní state nejsou časovou retencí kráceny.
- **BACKUPS:** retence záloh je oddělená od SQL raw retence: záloha může obsahovat sedmidenní stav k datu jejího pořízení; nechat platit existující RPO 6h až do otestované alternativy. Pokud si uživatel přeje sedmidenní maximální dobu zachování *i ve všech zálohách*, jde o samostatný datový/obnovovací kontrakt.
- **SQL kompaktace:** `DELETE` samo neudělá menší soubor. Ověřený rollover se sestaví do samostatné nové DB/SQLite VACUUM INTO až mimo 02:55–05:05, s ochranou WAL/ACK, předchozí zálohou, hash kontrolou, volným místem a bezpečným rollbackem.

**Retence není náhradou za snížení objemu nově zapisovaných dat.** Pouze omezuje dlouhodobou velikost DB, ne počet write operací za den.

## Odhady úspor – přísně oddělené důkazy od cílů

### Doložené izolované simulace

- SOC reference: **56,4 %** (11.11) / **72,0 %** (8.11) při započtení jedinečných objektů.
- RAM input reference: **1,027 MB** (11.11) / **1,084 MB** (8.11) na den; 100% přímá rekonstruovatelnost ze současného `priority_samples.inputs`.
- Priority `session` ref: cca **4 %** v priority tabulce.
- Přesun 15 bezpečně vybraných fázových měření se zachováním `value/quality/age_seconds/last_reported`: `priority_samples` 11.11 **5,577→3,212 MB**, ale **zatím inkompatibilní** s požadavky všech 24 RAM vstupů bez společného kanonického frame. Tuto úsporu **nesčítat** s RAM referencí.
- Trojí `variants` sdílená pole (jen tam, kde opravdu identická): 11.11 `priority_samples` **5,577→5,458 MB**, 8.11 **5,734→5,686 MB**. Poměrně malý přínos; není priorita.
- Špatný přístup: samostatné `manual_control`+`owner_reports` SHA objekty **zvýšily** `ram_control_samples` o **25–27 %**.
- Hrubé signatury vydání SOC (nezaměňovat s úplnou ekvivalencí rozhodnutí): 8.11 **644 záznamů/23 hrubých signatur**; 11.11 **139/28**.

### Co není zatím měřenou úsporou

- Odstranění **7,77 MB/den** durable ACKed outboxu je konstrukční **potenciál** pro trvale držené řádky *a* pro nové zápisy jen při změně FIFO spool protokolu. Předtím musí být funkční read-through a reprodukovatelný wire hash; jinak by se ztratila historie nebo možnost resend.
- Výběr jen materiálních SOC rozhodnutí je potenciál; vyžaduje oddělení 30min lease, invalid/revoke a as-of validity.
- Všechny MB sumy z různých experimentů nejsou automaticky sčitatelné (někdy mění stejný zdroj). **Není poctivé slibovat finální velikost bez kompletního multi-table benchmarku a replay testů.**

### Cílový rozpočet, nikoli slib

| Etapa | Očekávaný denní přírůstek nové logické evidence | Stav tvrzení |
|---|---:|---|
| Dosavadní verze 0.6.31 | **29,90 MB/den** (7d průměr) | **ZMĚŘENO** |
| Po normalizaci SOC + pointer-based ACK a kanonickém sdílení | **přibližně 12–18 MB/den** | orientační konstrukční odhad, nutné celkové měření |
| Po změnovém logování diagnostiky, odlehčení 5s řádků a modelových vydání | **cíl 5–8 MB/den** | akceptační cíl, zatím **neprokázaný** |
| Ambiciózní druhá iterace | **pod 5 MB/den**, pokud replay a peak coverage PASS | aspirace, při rozporu se safety nesnižovat data |

Při cílových 5–8 MB/den a 7d hot retenci by nový raw segment představoval přibližně **35–56 MB**, plus indexy, verze, summary, čekající fronty a ostatní permanentní data. **Není to prognóza finální SQLite file size** bez vykonané migrace, SQL compaction a konkrétních denních výsledků.

Plné portable kopie dnes každých 6h zapisují teoreticky při 502,5MB souboru 4×502,5 = **cca 2,01 GB/den disk copy I/O**; jejich velikost automaticky klesne až po úspěšné kompaktaci. Není bezpečné je teď vypnout jen kvůli I/O.

## Doporučený bezpečný realizační plán

1. **Fáze A – zdrojový kontrakt a zlatý replay:** zafixovat vybrané historické dny (zdravý 11.11, problémový 8.11, anomalie a změny fází), full byte-hash, night_summary, SOC decision verify, prahové chyby, ACK stream, dashboard. U každé nové položky měřit fyzické BLOB, indexy, transakce a čas zapisování.
2. **Fáze B – úsporné schéma bez retence:** canonical frame pro priority+RAM+night, vyřešit redundantní `input_reports` a `session`, dedup verzované SOC, event-only změny a lehké snapshots. Běh přes *stejné* historické vstupy; diff souhrnů a safety musí být 0, nové BLOB bajty skutečně méně.
3. **Fáze C – retention readers:** implementovat hodinové/denní quality-preserving agregace a přesměrovat `calibration/shadow/analytics/soc review/EV session/phase_budget`. Test 366d hranice, DST, nekompletní data, tariff versions, observed vs projected. Permanent records se podpisují a ověřují.
4. **Fáze D – 7denní GC shadow dry-run:** plán purge vypíše přesně všechny dotčené řádky, závislé modely a referenční objekty; simulace nad izolovanou kopií prokáže identické výstupy a dostupné historické výsledky. Pak teprve povolit skutečné mazání po 05:05; chránit pending a staré unclosed sessions.
5. **Fáze E – bezpečné fyzické zmenšení file:** atomic migration/compact mimo kritické okno, nativní Backup + test izolované obnovy, DB integrity/foreign_key_check, žádný WAL loss a žádné unACKed ztráty.
6. **Fáze F – dohled:** dashboard `bytes_db_total`, `bytes_rows_new_24h`, `estimated_net_growth_7d`, `portable_backup_bytes_per_24h`, `oldest_raw`, `pending_chunks`, `retention_block_reason`, `latest_validated_aggregate_day`; alert na 60/75/90 % i nekompletní výpočet.

## Stop/go kritéria

**GO pro 7d data purge až když** (1) SQL/ACK FIFO nikdy neztratí pending, (2) modely s 45/90/366d historií běží ze souhrnů stejně nebo přísně zdokumentovanou, opětovně validovanou metodou, (3) permanentní SOC rozhodnutí jsou rekonstruovatelná s původním SHA, (4) starší denní výsledky se zobrazují i po purge HA Recorderu, (5) záloha a izolovaná obnova jsou ověřené, (6) správně fungují UTC hranice/DST a 02:59–05:00, (7) nejsou nové chyby Phase/Quality/Lease, a (8) aplikace zůstává `observe_only`.

**Není implementováno:** tento report a 407položková matice jsou **návrh**, ne aktivace retenční politiky. Neprovedly se žádné mazací SQL, VACUUM, změny konfigurace, snížení sběru, změna tarifu ani fyzické zásahy. Úplné soukromé auditní agregáty a interní 2 935položkový inventář zůstávají pouze na Raspberry Pi v `/share/hec-recovery/analysis-20261112/field-audit/`.

# Mapa chyb, testů a důkazů

Cesty jsou skutečné součásti repozitáře. Tabulka není tvrzení, že každý
historický nález měl úplnou provozní diagnostiku nebo že syntetika
nahrazuje fyzický test. Staré historické smyčky slouží zachování starých
protipříkladů; důkaz dnešního runtime musí procházet produkční entrypoint.

| Oblast / vada | Spustitelná regrese | Požadovaný invariant |
|---|---|---|
| RET-01: dlouhodobá evidence proti 2 GiB limitu | [audit a stav SQL](DEEP_AUDIT_0631_20261112.md) | Před kvótou alarm, immutable archive/restore + SHA a úplné denní počty. |
| HIST-01: starší den bez HA Recorderu | [auditní SQL/GET reprodukce](DEEP_AUDIT_0631_20261112.md) | Prázdný Recorder, přesto úplný den ze skutečné archived source. |
| UI-02: neplatný plan timestamp | [audit-only counterexample](../scripts/audit_ui02_invalid_plan_time_0631.mjs) | Aktuálně RangeError; po opravě doNotThrow card.render a čerstvý DOM. |
| SUP-01: celkový výpadek PID1 | [audit](DEEP_AUDIT_0631_20261112.md) | Po testovacím pádu obnovený Supervisor started, durable ACK a žádný fyzický povel. |
| START-02: nedeterministická 02:59 úloha | [audit](DEEP_AUDIT_0631_20261112.md) | Integrační 61s drift, validace po 03 a obě DST varianty. |
| UI-03: zobrazení preflight | [audit](DEEP_AUDIT_0631_20261112.md) | Viditelné ready/waiting/reason bezpečně v HA kartě. |
| QA-01: místní Node ICU | [audit](DEEP_AUDIT_0631_20261112.md) | Podpora cs-CZ pro locale testy na všech ranerech; CI není lokální test. |
| PRICE-01: ceník vs odlišný tržní senzor | [test_preflight_0631](../priority_shadow/tests/test_preflight_0631.py) | Ceník NT 03–05 s 1,8078 Kč/kWh, ověřený uživatelem podle smlouvy ČEZ a ceníku INDI; odlišný senzor se nesmí zaměnit. |
| START-01: předvalidace v 02:59 | [test_preflight_0631](../priority_shadow/tests/test_preflight_0631.py) | Analytická session připravená před 03, bez aktivní relace, správná DST fold; RAM diagnostika s chybnou fází/model, 2 nové rámce až po 03. |
| SOC, energie, dostupnost předpovědi, stejné horizonty | [SOC](../priority_shadow/tests/test_soc_fixes.py), [navazující SOC](../priority_shadow/tests/test_soc_fixes_062.py), [planner](../priority_shadow/tests/test_soc_planner.py) | Žádná budoucí znalost, dvojí energie ani nepřiznaný chybějící vstup. |
| Částečně dosažitelný cíl EV | [0.6.3](../priority_shadow/tests/test_partial_063.py) | Rozlišit žádoucí cíl a dosažený výsledek. |
| Fáze a okamžitá alokace | [fáze](../priority_shadow/tests/test_phase_064.py), [regrese rozpočtu](../priority_shadow/tests/test_phase_budget_regressions_065.py), [instant fill](../priority_shadow/tests/test_instant_fill.py) | Dodržet potvrzené meze a nesčítat dům/EV dvakrát. |
| Souhrny při chybějící fázi / další noc | [0.6.6](../priority_shadow/tests/test_summary_066.py) | Explicitní phase ID, izolace chyby, zachování historie. |
| Virtuální vlastník, převzetí a předání | [deník](../priority_shadow/tests/test_control_journal.py), [RAM](../priority_shadow/tests/test_ram_control.py) | Bez fyzických zápisů, respekt cizímu zásahu a expiraci. |
| TTL, owner reporty, outbox a čas integrace | [audit 0.6.9](../priority_shadow/tests/test_audit_069.py) | Nový neplatný návrh odvolá starý, původní reporty se neomlazují. |
| HTTP integrita a pořadí JSON | [0.6.10](../priority_shadow/tests/test_audit_0610.py), [HTTP JS](../scripts/test_http_integrity.mjs) | Hash i bez WebCrypto, žádná falešná kolize pořadím klíčů. |
| Atomický sběr, metadata, WAL/SHM | [0.6.11](../priority_shadow/tests/test_night_fixes_0611.py), [live reports](../priority_shadow/tests/test_live_reports.py) | Nedoložená dostupnost není nový report ani nula. |
| Obnova lease a původní deadline | [0.6.12](../priority_shadow/tests/test_lease_0612.py) | Nepřenášet staré reporty do nové platnosti. |
| Energie přes stop / loader / obnova vlastnictví | [0.6.13](../priority_shadow/tests/test_deep_fixes_0613.py), [0.6.14](../priority_shadow/tests/test_independent_fixes_0614.py) | Zachovat platný úsek, nepokračovat přes stop nebo unknown. |
| P/UI a sběr nezávislý na analytice | [0.6.15](../priority_shadow/tests/test_night_fixes_0615.py) | Šum a rozpor se nerozhodují kosmetickou úpravou dat. |
| Výjimky, původní časy chyb a další krok | [0.6.16](../priority_shadow/tests/test_audit_fixes_0616.py), [0.6.17](../priority_shadow/tests/test_audit_fixes_0617.py) | Nejstarší pending chyba se neztratí za sekundární výjimkou. |
| Nenulová práce, cache a čas rozhodnutí | [sběr 0.6.18](../priority_shadow/tests/test_collection_fixes_0618.py), [kontext](../priority_shadow/tests/test_collection_context_0618.py), [audit](../priority_shadow/tests/test_night_audit_0618.py) | Skutečný čas rozhodnutí, atomická provenience, bez prodlužování TTL. |
| Writer gate a skutečný SQLite lock | [0.6.19](../priority_shadow/tests/test_sqlite_writes_0619.py) | Omezené čekání; local_writer není nativní SQLITE_BUSY ani I/O. |
| Nesmí čekat regulátor na disk/publisher | [0.6.20](../priority_shadow/tests/test_control_isolation_0620.py) | Produkční run_loop nepoužije diskový Store ani blokující IPC/HTTP. |
| Preflight a pracovní režim | [preflight](../priority_shadow/tests/test_preflight_audit_0620.py), [Manual Mode](../priority_shadow/tests/test_manual_mode_0621.py) | Uložený podrežim není sám aktivní ruční řízení; neznámý/stale report blokuje. |
| Výpadek, nový frame, durable ACK, pád workeru | [0.6.22](../priority_shadow/tests/test_recovery_0622.py), [společné poruchy](../scripts/robustness/test_contracts.py) | Stop při vadných datech; obnova nečeká na disk; idempotentní FIFO bez duplicit. |
| EV startup, overflow, retry a procesní reap | [0.6.23](../priority_shadow/tests/test_night_fixes_0623.py) | Feasible rozběh zůstává; skutečný curtail má ochrany; ACK nečeká na analytiku; živý snapshot nereapuje proces. |
| N06-01 záloha a obnova | [0.6.24](../priority_shadow/tests/test_native_backup_0624.py) | Blokovaný hook nezastaví smyčku; živý restart nevrátí DB; ověřený archive→restore→seed. |
| DB-02 / MON-02: transport a projekce | [0.6.25](../priority_shadow/tests/test_monitor_sqlite_0625.py), [JS návaznost](../scripts/test_journal_transport.mjs) | Komprese neblokuje analytiku; souběh/rollback neztrácí řádky, plné detaily jsou ve streamu a karta je načte. |
| BACKUP-02 / DB-03 | [0.6.26](../priority_shadow/tests/test_backup_idle_0626.py) | Holder přežije pre-hook/worker close, neblokuje zápisy; tar→restore, stopped WAL a idle reads zachované. Nativní Supervisor důkaz zvlášť. |
| Neměnná původní noc a rekonstrukce | [archiv](../priority_shadow/tests/test_archived_replay.py), [zabalený replay](../scripts/verify_packaged_shadow.py), [stejný den JS](../scripts/test_same_day_reconstruction.mjs) | Oddělené zdroje/provenience; kolize ID nesloučí dvě historie. |
| UI refresh, scroll, fokus, stránkování | [updates](../scripts/test_card_updates.mjs), [partial card](../scripts/test_partial_card.mjs), [deep JS](../scripts/test_deep_fixes_0613.mjs), [browser](../scripts/test_card_scroll_browser.mjs) | Zachovat čtenou polohu a DOM; DOM test sám není měření v HA shellu. |
| Testovací brána nesmí zamaskovat FAIL | [gate policy](../scripts/robustness/test_gate_policy.py), [runner](../scripts/verify_robustness.py) | Odmítnout FAIL, skip, expectedFailure i prázdnou sadu; nebrat poslední úspěch místo prvního pádu. |

## Příkazy a rozsah

Z kořene repozitáře, syntetická data:

```sh
python3 scripts/validate_versions.py
python3 scripts/verify_documentation.py
python3 scripts/verify_packaged_shadow.py
python3 scripts/robustness/test_gate_policy.py
python3 scripts/verify_robustness.py --repetitions 3
(cd priority_shadow && python3 -m unittest discover -s tests -q)
(cd energy_coordinator && python3 -m unittest discover -s tests -q)
```

Aktuální seznam povinných Node sad a verzí Pythonu určuje
[workflow](../.github/workflows/validate.yml). Samostatné browser měření se
provádí jen při změně relevantního UI a s hlídanou pamětí; nepouštět ho
souběžně s velkým readerem na RPi. Sady pouštět sériově.
Počet scénářů runneru se může měnit; opakování není počet různých testů.

## Co je jiný důkaz

- Jednotka/reprodukce: konkrétní mechanismus, často syntetický čas.
- CI: přesný commit a podporovaná verze Pythonu, nikoli nasazení.
- Provozní záloha/obnova: skutečný archiv a skutečná obnova do odděleného místa.
- Recorder/karta: původní řádky a jejich zobrazení, nikoli modelová očekávání.
- Celá nová noc: skutečný čas/pokrytí/verze, nikoli urychlená smyčka.
- Fyzické řízení: samostatně potvrzené zařízení, watchdog, fáze a souběhy;
  žádná zde uvedená sada sama nepovoluje fyzický adaptér.


## 0.6.27 · standalone and storage boundaries

Source contract, regressions, rejected fixtures and limits: STANDALONE_0627.md. No native acceptance is implied by this source record. DB-01 historical cause and N06-02 remain open. No physical control.


##0.6.28 · EV-01/PLN-01/DB-05

[test_wallbox_0628.py](../priority_shadow/tests/test_wallbox_0628.py): contradictory Tessie and actual wallbox in checked_points, RAM loop, lifecycle and SOC input boundary; settled EV lag plus real house steps and no future leak; from_db→full planner→immutable sealed decisions; packing outside gate, durable pre-send earliest time, bounded metadata commits, FIFO fairness and timeout cleanup. [Contract](../priority_shadow/docs/WALLBOX_WRITES_0628.md). Native operation and a new complete night remain separate validation.


## DB-06 · 0.6.29

test_analytics_admission_0629.py: real long local writer, normal FIFO/fast priority, cancellation and preserved durable queue, partial-commit continuation without replay, genuine SQLite errors, schema no-op reads and missing index/table repair. Existing recovery/FIFO/partial rollback gates remain. [Contract](../priority_shadow/docs/ANALYTICS_ADMISSION_0629.md). Private night replay is separate from synthetic CI and future native validation.


## Audit 0.6.29 · protipříklady připravenosti

[Audit a přesná kritéria](READINESS_AUDIT_0629.md). test_readiness_audit_0629.py: N06-03 přes reálný SnapshotCollector a produkční run_loop; N06-04 smrt sběrného vlákna; REC-02 skutečný evidence_worker s lokální contention plus WorkerGuard bez ACK-progress podmínky; DATA-03 kolizní batch přes persist_batch/SQLite; DATA-04 record_decision→SQL→session_plan; LIVE-03 run_loop→publisher a neúspěšné HTTP; MON-03 rozdílné chyby ztracené v failure_result. scripts/test_readiness_audit_0629.mjs: UI-01 skutečný card.render s unknown časem a zachovaným starým DOM. Mode live je testem výslovně odmítnut. PASS těchto protipříkladů znamená potvrzenou současnou mezeru. DOC-01: verify_documentation kontroluje verzi registru a souvislou Markdown tabulku.

## 0.6.30 · sedm diagnostikovaných softwarových vad

[Kontrakt](../priority_shadow/docs/READINESS_FIXES_0630.md), [Python akceptace](../priority_shadow/tests/test_readiness_audit_0629.py), [asynchronní kontext](../priority_shadow/tests/test_collection_context_0618.py) a [skutečný render](../scripts/test_readiness_audit_0629.mjs). N06-03/04, REC-02, DATA-03/04, MON-03, UI-01: dokladovat konzervativní stop, neproměnit monitor v povel. Historické negativní reprodukce jsou [Python](history/readiness_counterexamples_0629.py) a [JS](history/readiness_counterexamples_0629.mjs).


## Po instalaci 0.6.31 – samostatný provozní důkaz

[Instalační report a naměřené meze](../priority_shadow/docs/DEPLOYMENT_0631_20261112.md):
zdroj/CI PASS, nativní záloha před aktualizací, verze 0.6.31/started/observe_only,
kolekce/storage/monitor/journal `ok`, nová persistentní potvrzení 3→4,
žádná ztráta či restart pracovníků. Regrese 02:59 je syntetická; skutečná
preflight noc 13.11. se zatím neověřila.

# Dokončení souhrnů a zdraví sběru · 0.6.6

Alokátor může při chybě vstupů vrátit jen podmnožinu fází. Pořadí v seznamu proto není mapování L1–L3. Souhrn používá explicitní `phase`, u chybějících měření vrací `None` a zveřejňuje `phase_observation_counts`. Maxima platí jen pro dostupná měření, nikoli nepřetržité pokrytí. Dvojznačné a nečíselné proudy se do maxim nezahrnou.

Každá uzavíraná noc má samostatný try/except. Výjimka z `finish` je diagnostika `collection_health.summary_errors`, nikoli důvod přerušit `priority.observe`. Ostatní noci ve stejné dávce pokračují. Stav `degraded` znamená aktuální sběr s chybou souhrnu; `failed` znamená neúspěšný cyklus. Při selhání cyklu publisher zneplatní výkonové návrhy a zveřejní čas posledního úspěchu; historický souhrn ponechá. Pokud není dostupná ani HA publikace, karta sama odvozuje zastaralost z posledního časového razítka.

Nový souhrn se ukládá také do append-only `priority_summary_revisions` pod `night-summary-v2-phase-ids`. Původní vzorky, rozpracované relace a existující souhrny se nepřepisují. Doplnění souhrnu používá původní verzi alokační policy; opravou diagnostiky se nemění modelové energetické výsledky.

Soukromá retrospektivní rekonstrukce noci bez uložených živých vstupů musí uvést jinou kvalitu: recorder obsahuje změny stavů, nikoli fyzický heartbeat. Rekonstrukce nesmí být vložena do provozní tabulky jako původní živý běh ani použít budoucí model jako tehdejší znalost.

Ověření: `test_summary_066.py` a `scripts/test_partial_card.mjs`. Syntetické testy dokazují návaznosti a zpracování chyb; neověřují fyzické řízení. Verze neobsahuje akční adaptér.

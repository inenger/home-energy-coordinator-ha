# 0.6.33 – Zpětná úspora SQLite a odstupňovaná retenční politika

## Co se mění

Pouze samostatný stínový doplněk Home Assistantu. Režim zůstává `observe_only` a fyzické akce `device_actions=0`. HEC LIVE package zůstává odpojený od HA; noc 13.–14.11. nebude ostrá.

- Starší `soc_decisions` se zpětně převedou do již podporovaného bezztrátového formátu `soc-deduplicated-fields-v1`. Každá původní hodnota, hash a metadata řádku zůstávají zachovány.
- Opakované identické `session` ve `priority_samples` jsou uloženy jen jednou podle SHA-256. Všechny čtecí cesty (výpočet denního souhrnu, poslední vzorky a fázové statistiky) rekonstruují původní datovou strukturu. Žádné snížení frekvence sběru.
- Migrace funguje pouze jednorázově na explicitní `REQUEST.json` na RPi a provádí se při startu doplňku **před spuštěním zapisujících procesů**. Nejprve založí konzistentní aktuální SQLite backup, pak pracuje na kopii, porovná přesně všechny SOC a priority záznamy, hlídá ACK, high-water značky i rowid FIFO, provede `VACUUM`, zkontroluje `quick_check` a `foreign_key_check` a až pak nahradí produkční soubor. Při chybě ověření po výměně provede obnovu z originálu, při jakékoli jiné chybě nespustí zapisující procesy. Starší snapshot z 11:33 se **nepoužije**, jinak by byly ztraceny nové záznamy.

## Retence

| Doména | Doba | Podmínky |
|---|---|---|
| `priority_samples`, `night_samples` | 14 úplných dnů | Jen uzavřené dny s uloženým konečným souhrnem |
| `ram_control_samples` | 14 úplných dnů | Jen uzavřené dny, s přesným queued cursor/session hash a potvrzenými všemi journaling chunks |
| `journal_transport_outbox` a jejich `journal_transport_receipts` | 14 úplných dnů | Všechny chunks musí být ACKed, staré denní sekvence se souhrnně uloží s SHA-256 digestem do trvalého `journal_transport_archive` |
| `soc_observations` | 90 dnů | Zachovají se rozhodnutí SOC, recenze, dlouhodobé výsledky i jejich verzované důkazy |
| `soc_decisions`, `soc_decision_parts`, `priority_summaries`, `night_summaries`, `priority_summary_revisions`, `soc_reviews`, `calibration`, `objects`, `versions`, `analytics_versions` | Bez časového omezení | Důležité závěry a jejich kontext |
| `ram_control_events`, `control_events`, `priority_events` | Bez časového omezení | Bezpečnostní události, změny stavu a rozhodnutí |
| Nedokončené dny a nepotvrzené přenosy | Nikdy automaticky | Podmínky pro retenci nejsou splněny |

Retence běží pouze v pomalém maintenance workeru, nejvýše jednou za 12 hodin, nanejvýš tři uzavřené dny v jedné dávce, **nikdy v časovém okně 02:55–05:05 Europe/Prague**. Nebude existovat nucený limit MB/den. Uvolněné stránky SQLite se mohou znovu využít; přímé `VACUUM` se neprovádí ve sběrné smyčce.

## Omezení

Potvrzení HA Recorderem dokazuje doručení, nikoli neomezené uchování všech atributů v HA. Po uplynutí 14 dnů zůstává trvalý souhrnný hash potvrzených přenosů, denní výsledky a úplná historie významných událostí, nikoli původní každosekundový stream. Původní starší SOC hashe se nepřepisují ani nedoplňují domnělou validitou.

### Výchozí test mimo produkci, 13.11.2026

Starý částečný experiment SOC na snapshotu: 529 084 416 B → 409 628 672 B (−22,58 %), 7 200/7 200 identických SOC záznamů. Nejde o novou produkční databázi a **nezahrnuje** novou deduplikaci priority ani retenci. Soukromé JSON důkazy jsou pouze na RPi v `/share/hec-recovery/db-retro-optimization-20261113/`. Přesný výsledek produkční 0.6.33 je nutno měřit až po dokončení čerstvé migrace.

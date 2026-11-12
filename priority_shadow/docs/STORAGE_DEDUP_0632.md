# Bezztrátová deduplikace velkých SOC rozhodnutí – 0.6.32

Datum: 12. 11. 2026 · Komponenta: `priority_shadow` · Režim: **`observe_only`**.

## Rozsah

Uživatel výslovně odmítl optimalizovat za každou cenu a požaduje
pragmatický kompromis: **neomezovat zatím data pevnou retenční dobou ani
cílovou velikostí**, zachovat všechny vstupy pro současné a budoucí
7/14/45/60/90/366denní analýzy a odstraňovat především skutečné
redundance.

0.6.32 z tohoto důvodu zavádí **jedinou úzce ohraničenou runtime změnu**:
opakovaně kompletní obsah `forecast_versions`, `calibration_summary`,
`calibration_context`, `house_validation`, `battery_energy_model`,
`history_source` a `assumptions` u rozsáhlých SOC rozhodnutí ukládá
jednou do tabulky `soc_decision_parts` a v rozhodnutí zachová SHA reference.
Přesný historický původ i `available_at` jsou součástí odkazovaných
hodnot. Pokud by kompaktní inline rekord nebyl aspoň o 512 B menší,
zůstane originální formát.

- Kód: `energy/soc_storage.py`, čtecí a zapisovací body
  v `energy/soc_runtime.py`; `record_decision` zapisuje obsahové
  objekty a nový immutable záznam **v jedné transakci**.
- Legacy zlib BLOB čte stejný decoder bez změny. Běžné krátké
  evidence rovněž zůstávají v historickém formátu.
- `soc_storage.read` ověřuje každý SHA-256, jeho konkrétní field typ,
  existenci a úplnost obalu. Vrací celý původní kanonický JSON,
  nikoliv částečnou projekci. `session_plan` dále ověřuje
  `soc_evidence.verify`, původní `decision_hash`,
  `issued_at`, 30min čerstvost a pravidla revokací.
- Poškození nebo chybějící sdílený objekt vede k neplatnému
  rozhodnutí (`session_plan=None`), **nikdy k aktivaci starého
  plánu nebo fyzické akce**. Samostatná diagnostika SQL je vhodná
  pro následné sledování integrity; plán se nesmí „dohledat“
  jako platný bez kompletních podkladů.
- Řízený offline downgrade převodník:
  `priority_shadow/scripts/materialize_soc_decisions_0632.py`.
  Tvoří novou ověřenou SQLite kopii, nikdy nepřepisuje původní DB.
  Starší verze 0.6.31 neumí nový ref-obal sama rekonstruovat;
  při rollbacku je potřeba kontrolovaně materializovat kopii
  a až poté bezpečně přejít ke starému readeru.
- Bez zásahu do tabulek `priority_samples`,
  `ram_control_samples`, `journal_transport_outbox` a
  `control_evidence_batches`. Neprovádět samovolné
  odstranění ACKed řádků, nerecyklovat stare seq/epoch.
- **Bez retence či mazání**, bez úpravy ceny z `sensor.cez_indi_cenik`,
  FVE priorit, fázových limitů, SOC rezerv, stínové 02:59
  předvalidace či stávajících automatizací.

## Naměřená úspora na RPi (skutečné historické záznamy)

Zdroj: izolovaná read-only `evidence.sqlite` portable kopie z
12.11. 07:24, beze změny originálních bajtů. Použit skutečný
0.6.32 `prepare/read/store_objects` kód, nové objekty v
izolované `:memory:` SQLite, znovu sestavený payload
**783/783 bitově totožný** po `pack` a původní `decision_hash`
**783/783 platný**.

| Den | Rozhodnutí | Historický BLOB součet | Nové BLOB + unikátní objekty | Úspora |
|---|---:|---:|---:|---:|
| 8.11.2026 | 644 | 15,9543 MB | 4,4791 MB | **71,93 %** |
| 11.11.2026 | 139 | 5,4401 MB | 2,3770 MB | **56,31 %** |

Náklad na jednorázový test RPi: 129,63 s a 39,21 s
CPU-bound běhu všech původních záznamů včetně **dekódování,
znovu komprese a dvojitého SHA ověření**. Nejde o čas pro
jedno běžné rozhodnutí produkční maintenance a nelze ho
přenášet na SSD write I/O. Normalizace snižuje objem
konkrétního typu nově ukládaných SOC záznamů. **Nezměřil
se tím nový 24h objem celé DB, WAL zápisy ani průměr měsíce.**

## Regresní kontrakty

- `priority_shadow/tests/test_storage_dedup_0632.py`:
  reprodukovaná celá větev `record_decision→SQLite→session_plan`,
  idempotence stejného `issued_at`, rozdílný payload a bezpečná
  revokace, 30min lease, fail-closed při odstraněném či
  poškozeném SHA objektu, writer-fault rollback obou tabulek,
  starý nekompaktní formát, offline vytvořená downgrade kopie.
- Původní `test_soc_fixes.py` testuje stejné F07
  původní `decision_hash` přes oficiální dekodér, místo
  předpokladu neměnné fyzické komprese.
- `scripts/replay_partial_night.py` a
  `scripts/verify_soc_deployment.py` používají stejný
  ověřený čtecí kontrakt.
- Úplná Python testovací sada, dokumentace, package gate,
  CI a nová provozní evidence po nasazení musí být
  dokumentovány jednotlivě; regresní PASS není automatická
  záruka 100% bezchybnosti.

## Omezení a rozhodnutí, která zůstávají otevřená

**DATA-05 částečně optimalizováno**, nikoli uzavřeno celé.
Související DATA-06/07 (duplicitní priority/RAM input), RET-01/02/03/04
a HIST-01 zůstávají otevřené. Přesné zdrojové časy a
hash starších let a důkaz zálohy se nesmí tiše zahodit.
Časté 6h přenosné zálohy nadále existují; jako samostatný
I/O problém budou vyhodnoceny teprve po měření.
Při přetrvávajících DB-01/N06-02 a LIVE-01/02/03
**není povoleno fyzické řízení**.

Nezavádí se předem slíbených 5–8 MB/den ani tvrdá
7denní hranice. Na další úplné noci 0.6.32 se mají
změřit 24h logické nové řádky, skutečný růst SQLite
souboru a copy/IO, plus nové SOC shared parts. Teprve
potom určit případnou další optimalizaci.

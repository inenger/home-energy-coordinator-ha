# Datový a AI kontrakt

Soukromá data, analýzy a replay se skutečnou historií patří na RPi.
Veřejný Git obsahuje implementaci, obecná zjištění a syntetické regrese.
Tento dokument umožňuje výsledek vysvětlit a ověřit bez opakovaného
vymýšlení modelu; nenahrazuje samotnou lokální evidenci.

## Zdroje a jednotky

| Veličina | Zdroj/implementace | Význam a omezení |
|---|---|---|
| SOC | `sensor.solax_battery_capacity`, % | Pozorovaná souřadnice; není lineární energie |
| Dům | `sensor.solax_house_load`, W | Obsahuje EV a teplo; pro profil odečíst EV právě jednou |
| EV | `sensor.solax_api_charge_power_total`, W; `sensor.solax_api_charge_added_total`, kWh | AC příkon a kumulativní dodaná energie |
| FVE skutečnost | `sensor.solax_today_s_solar_energy`, kWh | Nativní DC čítač; pro AC porovnání pouze označená aproximace ×0,966 |
| FVE prognóza | Solcast today/tomorrow/day_3 | Detailní výkon `pv_estimate` v kW; integrovat podle délky intervalu |
| Tarif | `sensor.cez_indi_cenik` | Řady `today`/`tomorrow`, start/end a nákupní cena v Kč/kWh |
| Slunce | `sensor.sun_next_rising` | Kontextový čas, bez vlastní přímé SOC podmínky |
| Počasí | Archiv hodinové prognózy s °C a `available_at` | Budoucí skutečná teplota nesmí nahradit tehdejší předpověď |
| Fáze/limity | `night.IDS`, `priority.EXTRA`, `soc_runtime.IDS` | Ověřit znaménka, jednotky, stáří a fyzické mapování |

Úplný seznam entit má kód, protože je pro tento konkrétní HA systém.
Při přenosu na jiné zařízení nestačí změnit pouze `config/entities.json`.
Žádné tokeny se kvůli analýze nečtou z registrů nebo nepřidávají do reportu.

## Uložení

SQLite payloady jsou kanonický JSON komprimovaný zlib (`store.pack/unpack`).
Dotazy pro audit otevírat `mode=ro`; nevytvářet `Store` nad cizí portable DB,
protože jeho konstruktor vytváří schema a zapíná WAL.

| Tabulka/soubor | Obsah |
|---|---|
| `objects` + `versions` | Obsah předpovědi/tarifu, hash, první zachycení verze a entita |
| `soc_observations` | Minutový pozorovaný stav s verzí software |
| `soc_model_versions` | Modely, období, původ, počty podkladů, holdout a hash |
| `soc_decisions` | Plné rozhodnutí, vstupy, alternativy, časový profil a hash |
| `soc_reviews` | Denní review, společné pokrytí a omezení; žádné realizované úspory |
| `priority_sessions`, `priority_runs`, `priority_samples`, `priority_summaries`, `priority_events` | Relace, dvojí replay, pokrytí, souhrny a preference |
| `soc-history.json.gz` | Privátní seed: `schema_version`, `source`, `house_hours`, `pv_pairs`, `battery_model`; průběžně aktualizovaný kontext |
| `priority-live.json` | Poslední výstup pro provozní diagnostiku |

Rozhodnutí a verze se přidávají, staré důkazy se při opravě nepřepisují.
Seed a živý JSON se atomicky nahrazují; nelze je vydávat za neměnný archiv.
Verzované modelové manifesty a plná rozhodnutí v SQLite zachovávají kontext
jednotlivých výpočtů. Samotný hash ověřuje obsah, nikoli fyzickou pravdivost.

## Kalibrace

Baterie se importuje z auditované místní analýzy přes `soc_history.import_analysis`.
Požaduje `history.json.gz`, `audit.json` a `battery_deep.json` ve stejném
RPi pracovním adresáři. Současný import je účelový: červenec 2026 slouží
k fitu směrových křivek, pozdější období k oddělenému porovnání. Není to
univerzální import libovolných exportů. Vstupní SHA-256 a metoda jsou v seedu.
Z tohoto fitu nelze tvrdit zjištěnou jmenovitou kapacitu nebo SOH.

FVE korekce oddělují sezónu, čtyřhodinový blok a předstih prognózy.
Model potřebuje alespoň 28 dnů, časově oddělený test a nejméně 3% zlepšení
MAE. Omezené a neznámé intervaly se pro fit nepovažují za neomezenou výrobu.
Bez dostatku důkazů je korekce 1 s výslovným stavem nedostatečné validace.
Poskytované spodní/horní prognózy nejsou kalibrované pravděpodobnosti.

Profil domu vybírá stejnou hodinu, přednostně sezónu a typ dne; při nedostatku
dat používá zdokumentované širší skupiny. Teplotní kandidát musí zlepšit
chronologický holdout nejméně o 3 % a mít alespoň 72 srovnatelných hodin.
Používá tehdy zachycené počasí. EV kalibrace vyžaduje souvisle pozorovanou
relaci včetně začátku a konce; po mezeře se starý vzorek nepřipojí znovu.
To vše upravuje stínový model, nikoli tarif, rezervu nebo fyzické ovládání.

## Postup nezávislé verifikace

1. Zapsat commit/verzi, politiku, den a `issued_at`; načíst plné rozhodnutí
   z `soc_decisions`, nikoli pouze zkrácený stav senzoru.
2. Přes `soc_evidence.verify` ověřit `soc-decision-canonical-v2` nad celým
   payloadem bez `decision_hash`; porovnat i hash ve sloupci tabulky.
3. Dohledat modelový manifest a zdroje. U každé předpovědi ověřit
   `available_at <= issued_at`, pokrytí horizontu, jednotky a zdrojový hash.
4. Reprodukovat scénáře se stejnými vstupy. Porovnat energie, SOC na
   hranicích, splněnou EV potřebu a ocenění konečné zásoby, ne jen cíl v %.
5. Ve review spojit předpověď a skutečnost na stejných pozorovaných
   intervalech. Chybějící pokrytí není nula; neznámé omezení není `false`.
6. Uvést měřicí hranici. DC skutečnost ×0,966 je AC proxy, ne nezávislý
   AC elektroměr. Clipping/exportní omezení oddělit od chyby Solcastu.
7. Zveřejnit pouze obecné závěry a syntetický regresní případ. Skutečná
   pozorování, plné lokální reporty a seed ponechat na RPi.

AI zlepšení přijímat jako změnu kódu s reprodukcí, odděleným holdoutem
a regresí. Runtime neprovádí libovolné AI návrhy a sám nepřepíná politiku.
`plan_executed=false`, `measured_savings_czk=null` jsou záměrné: skutečný
SOC původních automatizací není chybou plánu, který se fyzicky neprovedl.

## Evidence od 0.6.3

Také odmítnuté plány uchovávají `input_snapshot`, `forecast_versions`,
zdroj historie a po dostupnosti modelu `calibration_context`, mapu baterie
s předpoklady a vypočtené `forecast_periods`. Ty obsahují predikce spotřeby,
FVE a ceny používané v simulaci. Výjimka před získáním vstupů je ukládá jako
nedostupné, nevymýšlí je. Starší chybějící snímky se zpětně nedoplňují.

`scripts/replay_partial_night.py` provádí pouze rekonstrukci na RPi přes
SQLite `mode=ro`. Pro staré odmítnuté plány výslovně uvádí přenesená pole,
čas základního snímku a shodu domácího profilu s původním manifestem.
Odděluje as-of scénářový plán od následného replay na skutečně pozorovaných
výkonech. Výstupy ukládá do nového privátního adresáře; není to tehdy vydané
rozhodnutí a nelze z něj vyvozovat naměřené úspory.

## Evidence 0.6.4

Rozhodnutí schéma 4 obsahuje `power_budget` (25 A, reserve_a, power_factor,
house_phase_shares, source_hash, dostupnost a období), `attainable_soc_05`,
`target_shortfall_soc_pct` a `target_reached_all_scenarios`. Tyto hodnoty
procházejí kompaktním pohledem i alternativami priorit. Plné scénáře a
kandidáti zůstávají v rozhodnutí. Úplná splnitelnost cíle a splnitelnost
EV/modelové rezervy jsou dvě různé příznakové hodnoty. Staré záznamy se
nepřepisují; chybějící pole nejsou zpětně domyšleným měřením.

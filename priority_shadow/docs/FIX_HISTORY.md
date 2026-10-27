# Historie chyb a regresní důkazy

## 0.6.1: opravy prvního SOC auditu

| Oblast | Pravidlo | Regrese |
|---|---|---|
| Teplota | Holdout používá tehdy dostupnou předpověď | `test_soc_fixes.py` F01 |
| EV | Nulový nebo fyzicky přípustný proud v každém úseku | F02 |
| DC port | Jeden součet nabíjení ze sítě a PV | F03 |
| Návrh | Novější neplatný návrh odvolá starý; TTL a restart | F04 |
| Limity | Nabíjení a vybíjení mají vlastní vstupy | F05 |
| PV | Integrace předpovědi na stejných měřených intervalech | F06 |
| Hash | Hash plného payloadu bez samotného hashe, až po metadatech | F07 |
| Čas SOC | Výchozí bod a koncový čas energie | F08 |

## 0.6.2: opravy následného auditu

| ID | Poučení | Regrese v `tests/test_soc_fixes_062.py` |
|---|---|---|
| N01 | Osiřelá stará relace nesmí obejít povinný nový plán | `SessionRecovery` |
| N02 | Po mezeře se nesmí znovu připojit předchozí vzorek | `EVContinuity` |
| N03 | Konzervativní fázový rozpočet není nákupní AC bilance | `ACBalance` |
| N04 | AC výstup měniče sdílí PV a vybíjení | `ACBalance` |
| N05 | Replay a review potřebují stejné brány; společné intervaly | `ReviewValidity` |
| N06 | DST ověřovat přes celou review cestu, nejen pomocnou funkci | `ReviewValidity` |
| N07 | Neznámá PV metadata nesmí zahodit platný profil domu | `IndependentQuality` |

Původní tvrzení „vše opraveno“ bylo po prvním průchodu příliš široké.
Od nynějška uvádět rozsah důkazu: jednotkové testy, nezávislé sondy,
provozní kontrola a dosud neověřené fyzické předpoklady. Nový nalezený
protipříklad rozšiřuje regresní sadu; historické důkazy se nepřepisují.

Privátní auditní zprávy, logy, seed a časové řady zůstávají na RPi.
Veřejné příklady a testy nesmějí obsahovat kopie naměřených řad.

## 0.6.3: nedosažitelný EV cíl a význam stavů

Regrese jsou v `tests/test_partial_063.py` a `scripts/test_partial_card.mjs`.

- Žádoucí EV cíl není potvrzené minimum do odjezdu. Nedosažitelný cíl
  vytváří výslovně částečný plán a uchovává deficit, nikoli falešný úspěch.
- Obě priority mají vlastní cíle, stejné limity a výslovně přiznanou různou
  službu autu. Částečná relace musí projít stejnými branami jako úplná.
- Zamítnuté rozhodnutí uchovává vstupy; snapshot se nesmí měnit po výpočtu.
- Provozní `sensor.solax_run_mode` a volba `select.solax_charger_use_mode`
  jsou samostatné údaje. Jejich rozdíl sám neprokazuje závadu či zastaralost.
- Přítomná předpověď s odmítnutým plánem není missing_forecast. Bez platného
  modelového pokrytí nepublikovat nulové energie ani výchozí SOC jako výsledek.
- Staré důkazy zůstávají zachované; opravený diagnostický pohled na historický
  souhrn uchovává i jeho původní diagnostický kontext.

## 0.6.4 · výkon a nedosažený cíl

Pevný limit 22 A × účiník 0,9 snižoval rozpočet a přísné odmítnutí cíle
v jediném scénáři zaměňovalo nedosažitelnost požadavku za ekonomickou
nevýhodnost. Nový odhad po fázích má zdrojové období a explicitní fallback;
vyšší cíle zůstávají v porovnání s dosaženým SOC a skutečně modelovanými
náklady. `tests/test_phase_064.py` ověřuje časovou kauzalitu, chybějící
a rozporné proudy, rezervy, nejslabší fázi, zbytek výkonu po EV, zachování
cíle s deficitem, průchod do view a letní vynechání nabíjení. Renderer
ověřuje rozdíl cíl/výsledek i zobrazení fázových rezerv.


## 0.6.5
- Ekonomické odmítnutí neblokuje alokaci: test_full_observer_path_without_soc_plan.
- Proudové vstupy, slabá fáze, minimum EV, DC/AC limity a bilance: test_instant_fill.
- Opožděný DST reset: test_calendar_reset_preserves_prefix a test_sparse_night_counters_dst.
- Oddělení deficitů a kvantování: test_deficit_dictionary a test_rounding_regression.

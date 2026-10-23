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

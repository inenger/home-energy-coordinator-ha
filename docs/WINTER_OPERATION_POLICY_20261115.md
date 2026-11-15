# WIN-01 — Zimní energetická politika (schválené zadání, 15. 11. 2026)

**Stav:** produktové požadavky potvrzeny, **zatím NEIMPLEMENTOVÁNO** do runtime `priority_shadow 0.6.33`. [GitHub issue #52](https://github.com/inenger/home-energy-coordinator-ha/issues/52). Pozorovací režim `observe_only` beze změny; HEC LIVE nesmí být automaticky aktivován.

## Oprava interpretace nočního auditu 14.–15.11.2026

1. **SolaX X3-Hybrid G4: `Back Up Mode` je zamýšlený a správný režim.** Umožňuje běžné použití FVE a baterie nad nastavenou minimální rezervou a zálohování EPS. Na RPi zjištěno `number.solax_backup_discharge_min_soc=20` a baterie 19 % / 0 W během 03–05: nevybíjení pod rezervou samo není porucha. Nezaměňovat **discharge Min SOC** (rezerva) s **nightcharge Upper SOC** (cílová mez nabití ze sítě); druhá entita `number.solax_backup_nightcharge_upper_soc` měla 70 % při auditu. Vybraný režim není důkaz povoleného síťového nabíjení v konkrétním časovém rozvrhu; k tomu samostatně zkontrolovat konfiguraci/omezení měniče.
2. **EV/Tesla:** primární levné nabíjení 03:00–05:00. Cílových 80 % je preferovaný stav, nikoli povinnost dosáhnout ho za dvě hodiny ani automaticky pokračovat po 05:00. Uživatel může nabíjení mimo okno sám ručně spustit. Skutečná noc Tesla 43→69 %, přibližně 22,33 kWh AC na 11kW EVC; nedosažení 80 % **není závada ani alarm**.
3. **Zima:** 15,30 kWh denní predikce FVE při venkovní teplotě kolem 0 °C / pod nulou a významné spotřebě TČ **neznamená dostatečnou denní výrobu**. Schválený *požadovaný* zimní cíl domácí baterie pro tento scénář je **100 % SOC**, i když nemusí být dosažitelný za levné okno. Vyjadřovat odděleně požadavek, odhad dosažitelného SOC po 05:00 a konečný fyzický povel, nikdy nevydávat cíl za skutečný výsledek.

## Důkazy na Raspberry Pi (read-only, 15.11.2026)

- Shadow doplněk `0.6.33`, `observe_only`, 1 443 vzorků 03–05, žádné fyzické akce.
- Solcast pro 15.11. archivováno ~15,3046 kWh; aktuální odečet ~15,2584 kWh (hodnoty jsou předpověď, ne realizovaná výroba).
- V HA aktuálně `sensor.current_outdoor_temperature_bt1_30002=-1,8 °C`, `sensor.outdoor_temperature_eb101_bt28_31622=-3,3 °C`; historické `soc_observations.outdoor_c` ve sledovaném okně cca −2,5 až +2,8 °C (odlišný zdroj/charakter: nejde automaticky o totožný fyzický BT1 sensor).
- `sensor.tepelne_cerpadlo` je k dispozici; ověřit jednotky, kontinuitu a oddělení elektrického příkonu TČ od celkové spotřeby domu před kalibrací, aby se TČ nezapočítávalo dvakrát.
- Baterie 19 % / 0 W; běžný on-grid Backup Min SOC 20 %. EV spotřeba ~22,33 kWh, import ~24,27 kWh, nejvyšší naměřená fáze 19,7 A při jističi 25 A. Vzorkovaná maxima nejsou certifikací ochrany jističe.
- `priority_shadow/energy/instant_fill.py` v aktuální verzi používal `target_soc_pct=100` jako **max-fill stínový modelový cíl**, nikoliv skutečný setpoint měniče. `soc_planner.py` aktuálně zkouší hodnoty po 5 % pouze do **95 %** a pro noc v odlišném ekonomickém modelu vybral 30 %. **Původní auditní tvrzení, že samotný modelový cíl 100 % je kritická chyba, se odvolává.** Jde o rozdílné účely dvou modelů a nedostatečnou zimní logiku v ekonomickém plánovači.

## Požadovaná implementace — další verze, ne tato dokumentační změna

1. Zavést semantiku tří oddělených výstupů: `desired_target_soc_pct`, `attainable_soc_05_pct`, `physical_charge_target_soc_pct` (poslední pouze v explicitně schváleném live režimu a při ověřených schopnostech měniče). Stávající názvy převádět s explicitním původem/model tagem.
2. Cílový SOC odvozovat z hodinové spotřeby bez EV, příkonu TČ a ověřených teplotních dat; zohledňovat COP/odmrazování/patronu pouze v míře podporované skutečnou historií, hodinový Solcast, čas výroby, sezónu, očekávanou bilanci do dalšího levného okna a nejistotu. Vysokou spotřebu TČ netvrdit jen podle stupňů bez modelu. Při mrazu a ~15 kWh PV musí zimní fixture podporovat požadavek 100 %.
3. Zajistit shodu nebo vysvětlitelný rozdíl mezi `soc_planner`, `instant_fill`, `priority`, zápisem návrhů, preflight, souhrnem a UI. Ekonomický SOC model nesmí omylem omezit zimní požadavek na 95 % bez explicitního rozlišení fyzického a ekonomického cíle.
4. Respektovat preference priorit EV/baterie a bezpečné limity 3×25 A. Maximální zimní cíl **neimplikuje** nucenou alokaci všech kW baterii, potlačení EV nad rámec zvolené priority, ani prodloužení levného okna. Modelovat a zobrazovat nedosažitelnost, nepovažovat ji za chybu.
5. Udržet `Back Up Mode`, běžnou rezervu 20 % a oddělené `nightcharge_upper_soc=70 %` jako **aktuální stav** do případného samostatně schváleného řízení. Při budoucím live nabíjení ověřit správný register / write-readback a návrat původních hodnot, nesplést Min SOC s cílem nabití, netvrdit možnost dobíjení pouze z výběru Back Up Mode.
6. Negativní testy: obleva se slabým TČ, vysoká FVE při mrazu, chybějící/zastaralé BT1/BT28, výpadek TČ snímače, měnící se tarif, EV nezapojeno/zapojeno a 43→69 % bez alarmu, baterie těsně pod rezervou 20 %, kapacita jističe a BMS nižší než požadavek. Syntetické replay testy i skutečná další noc v observe_only. Žádný automatický live cutover bez nového souhlasu.

## Akceptační kritéria WIN-01

- Studená referenční noc s ~15 kWh FVE / funkčním TČ produkuje **desired target 100 %**, a zvlášť **attainable target <100 %**, pokud 2h souběžný výkon EV/baterie nestačí.
- Nezaměňuje se maximum modelového plnění s ekonomicky vybranou nebo fyzicky nastavenou hodnotou; ochrana 20% Min SOC funguje správně a 70% parametr nightcharge se reportuje odděleně.
- Nenastane 80%-SOC fault u EV pro běžné dvouhodinové okno.
- Všechna doporučení a zápisy správně zachovávají `observe_only` a `device_actions=0` v aktuálním buildu.
- Regrese pokrývají produkční tok; výsledky CI, merge a fyzická nasazení se reportují odděleně.

**Rozsah změny dokumentace:** žádná změna runtime verze, řídicí konfigurace, firmware, nastavení baterie nebo EV, žádný restart doplňku.

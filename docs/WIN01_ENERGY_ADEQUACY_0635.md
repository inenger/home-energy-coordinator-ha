**Nasazení potvrzeno 17.11.2026:** [Provozní evidence 0.6.35](DEPLOYMENT_0635_20261117.md). Publikované as-of vstupy a policy ověřeny, HEC LIVE odpojený. Historický replay není budoucí celá noc.

---

# 0.6.35 — WIN-01: nedostatek energie má přednost před teplotní hranicí

**Datum:** 17. 11. 2026. **Výchozí commit:** `41a57fdf3575f7fc954e7abb49d5693001be34b0`. **Rozsah:** výhradně `priority_shadow`. HEC LIVE stále odpojeno, `observe_only`, `device_actions=0`, žádné SolaX/Tesla fyzické setpointy.

## Reprodukovaná vada 0.6.34

`energy/winter_soc.py` vyžadoval **současně** venkovní chlad ≤2 °C a konzervativní energetický deficit ≥70 % využitelné energie baterie. Noci 16. a 17.11. byly teplejší (4,6–5,3 °C), i když predikce FVE byla jen 3–5 kWh proti domácí spotřebě ~17,8 kWh. Model tak v 02:55 SEČ zvolil ekonomický SOC 50 %, bez zdůraznění potřebné energetické rezervy.

## Oprava `energy-adequacy-v2`

Použij jen as-of hodinový model z období **05:00 až další den 03:00**, který již obsahuje vytápění a TČ; `sensor.tepelne_cerpadlo` je pouze podpůrná diagnostika, nikoli další součet. Bez úplného horizontu a ověřené referenční kapacity nevnucuj žádný zimní target.

- `E_central=max(0,house_central_kWh-PV_central_kWh)`.
- `E_stress=max(0,house_high_kWh-PV_low_kWh)`.
- `E_usable=Battery.available(100)-Battery.available(reserve_soc)` – referenční modelová dostupnost, nikoli uživatelem schválený fyzický Min SOC.
- **Energeticky výrazně deficitní den (nezávisle na počasí):** `E_central>=1.00*E_usable` a `E_stress>=1.25*E_usable`. Výsledek `severe_energy_deficit`, požadovaný SOC **100 %**.
- **Chladný den:** platná as-of BT1/BT28 nebo hodinová předpověď ≤2 °C a `E_stress>=0.70*E_usable`. Výsledek `cold_deficit`, požadovaný SOC **100 %**, i kdyby centrální deficit byl mírnější.
- Jinak platí `ordinary_economic_plan`; při nedostatku počasí s dostatečnou energií diagnostika `no_temperature_asof`; při chybějícím horizontu `insufficient_energy_forecast`. Hranice jsou **konzervativní stínové heuristiky**, nikoli pravděpodobnosti nebo fyzické regulátory.
- Stále rozlišovat `economic_target_soc_pct`, `desired_target_soc_pct`, `attainable_soc_05_pct` a `physical_charge_target_soc_pct=None`. Nenahrazovat nemožnost dosažení 100 % dalším nabíjením EV mimo 03:00–05:00; preferenci mezi EV/baterií neměnit.
- Důkazní `decision_reason` přejde z `minimum_scenario_regret` na `severe_energy_deficit` nebo `winter_cold_load_adequacy`. Stávající frozen sessions, historická rozhodnutí, jejich SHA a retenční uzávěrky se nemění. Dashboard nyní ukazuje energetický cíl i při +5 °C a vedle něj ekonomické optimum.

## Historický přepočet na RPi – pouze pro čtení

Vybrána **nejpozdější původní archived SOC decision před 03:00 SEČ** (01:55–01:57 UTC) jednotlivých dnů, včetně původních `input_snapshot`, `forecast_periods`, `battery_energy_model`, `window_end` a `horizon_end`. Žádná pozdější předpověď, odhadovaný reálný odběr či upravený hash.

| Noc (listopad 2026) | Původní SOC | T vzduchu | Model centrálního deficitu | E usable | Nové vyhodnocení |
|---|---:|---:|---:|---:|---|
| 12.11. | 35 % | +5,2 °C | 13,35 kWh | 8,8 kWh | severe_energy_deficit → 100 % |
| 13.11. | 75 % | +5,2 °C | 10,43 kWh | 8,8 kWh | severe_energy_deficit → 100 % |
| 14.11. | 50 % | +2,5 °C | 7,80 kWh | 8,8 kWh | cold_deficit → 100 % (as-of hodinové minimum ≤2 °C) |
| 15.11. | 25 % | −1,7 °C | 8,28 kWh | 8,8 kWh | cold_deficit → 100 % |
| 16.11. | 50 % | +4,6 °C | 14,12 kWh | 8,8 kWh | severe_energy_deficit → 100 % |
| 17.11. | 50 % | +4,9 °C | 15,27 kWh | 8,8 kWh | severe_energy_deficit → 100 % |

Tyto výsledky jsou **čistě výpočtem nové podmínky nad neměnnými původními forecast sloty a bateriovými modely**, nikoliv replay celé nové noční regulační smyčky ani důkaz skutečného dobití. V nově běžícím regulátoru musí navíc projít i celé serializace a dashboard.

## Regrese a negativní scénáře

Nová sada `test_winter_energy_0635.py` ověřuje celou cestu `planner.plan -> decision_hash verify -> soc_runtime.view`, zejména +5°C / nízkou FVE a nedosažitelné požadované SOC; dále mezní hranice, chybějící teplotu, chlad s mírnějším deficitem, neúplný forecast, chybějící energetický model a dostatečně slunečný den. Starší `test_winter_retention_0634.py` nadále ověřuje RET-05 a upravené očekávání důvodu zimního cíle.

**Dokumentovat i neúspěšné pokusy:** po první změně pravidla selhaly 3 původní testy, které považovaly vysoký SOC při +12 °C a bez teploty za chybu, protože vycházely ze staré teplotní podmínky; správně byly změněny regresní očekávání pro nový energetický kontrakt. Další jeden test porovnával starý text `winter_cold_load_adequacy`, ale nový správně vracel `severe_energy_deficit`. První edit dashboardu měl chybějící závorku a neprošel `node --check`; doplněna, následně všechny cílené UI testy PASS. Nezatajujeme tyto testovací neúspěchy ani je nevydáváme za runtime incident.

## Stále otevřené meze

- 2 °C / 70 %, 1× / 1,25× jsou transparentní stínové heuristiky, **nikoli empiricky kalibrovaná účinnost TČ/COP nebo garance úspory**; vyhodnocovat prognózu vs skutečnou spotřebu a FVE na dalších dnech.
- Výkonnost při souběhu EV / baterie, 3×25 A přechodové špičky, skutečné nabíjecí registry Back Up Mode a auto-restoration zůstávají samostatnými LIVE blokátory. Nic z toho se touto změnou neaktivuje.
- GitHub commit, CI a nasazení na RPi jsou různá stadia. V tomto dokumentu je záznam navržené verze; čas a výsledek skutečného deploy musí být doplněn až po ověření.

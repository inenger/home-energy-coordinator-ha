# 0.6.34 — WIN-01 zimní plán SOC a RET-05 noční retenční souhrny

**Rozsah:** samostatný `priority_shadow`, nadále výhradně `observe_only` a `device_actions=0`. HEC LIVE / aktivní HA automatizace, SolaX Back Up Mode, limity baterie, tarify, Tesla wallbox a hardware se **nemění**.

Výchozí veřejný commit: `f0154276de44783b96c18046a4c0784472547bfe`.
Původní zadání: [WIN-01](WINTER_OPERATION_POLICY_20261115.md), [issue #52](https://github.com/inenger/home-energy-coordinator-ha/issues/52).
Nový retenční nález RET-05 (původně slovně „RET-NIGHT-01“).

## WIN-01: rozhodnutí při mrazu

Nová politika `winter-cold-load-adequacy-v1` zůstává deterministická a poradní.

1. Z aktuálního HA snímku použije čerstvou venkovní teplotu NIBE BT1, při její nedostupnosti čidlo BT28; dále zaznamená čerstvý příkon TČ a dostupnou as-of předpověď hodinových teplot.
2. Nezdvojuje příkon TČ: historický profil `house_without_ev_kwh` již zahrnuje TČ/patronu. Příkon TČ je **podpůrný doklad provozu**, nikoli další přičtená energie. Dům je v jednotlivých hodinách modelován dosavadním konzervativním profilem, pokud vlastní teplotní kalibrace neprošla holdoutem.
3. Ze stejné as-of hodinové PV předpovědi a domácího profilu pro období **05:00 až následujících 03:00** vypočte energetické riziko `max(0, sum(high_house_kwh − low_PV_kwh))`. Srovnává je s energií baterie mezi referenční rezervou a 100 % na empirické SOC křivce.
4. Při teplotě **≤2 °C** (čerstvé BT1/BT28 nebo dostupná relevantní hodinová předpověď), úplném horizontu a při energetickém deficitu **≥70 %** referenčně použitelné energie nastaví `desired_target_soc_pct=100`. Jinak zůstává výběr dosavadního ekonomického minima regret. Jde o konzervativní **modelový práh**, nikoliv fyzikální klimatickou kalibraci nebo pravděpodobnost.
5. Plánovač počítá kandidáty po 5 % až do **100 % včetně**. Zvlášť ukládá `economic_target_soc_pct`, `desired_target_soc_pct`, `attainable_soc_05_pct`, `physical_charge_target_soc_pct=None` a důvod rozhodnutí. `target_soc_pct` je požadovaná hodnota pro navazující **stínové** priority. Nedosažitelný cíl se výslovně označí jako částečný; nemění EV prioritu, dvouhodinové okno ani fyzické limity.
6. Model `instant-max-fill` si ponechává svůj explicitně odlišný maximální cíl 100 % a starší zmrazená tabulka `night_sessions` se zpětně nepřepisuje; v nové analytické kartě jsou ekonomický a zimní cíl vysvětleny samostatně.

**As-of historický replay, 15.11.2026, původní rozhodnutí 02:55 SEČ:**
starý ekonomický návrh 25 %; původní as-of BT1 −1,7 °C, Solcast 15,3046 kWh,
uložený model domácího zatížení 20,60 kWh (centrální) / 35,39 kWh (stres),
nižší FVE 6,69 kWh, stresový deficit 28,70 kWh, referenčně použitelná energie 8,8 kWh.
Nové čisté poradní pravidlo správně určuje **požadavek 100 %**.
Nebyly použity později doplněné předpovědi ani změněn starý hash rozhodnutí.
Tento replay izolovaně ověřuje novou zimní politiku nad archivovanými sloty;
není to důkaz uskutečněného nabití či celé nové produkční noci.

## RET-05: bezpečné uzavírání noční evidence

- Dosavadní aktivní `priority_maintenance.Maintenance.compute` volala `priority.finish`, ale nikoli `night.summarize` (tu obsahovala pouze stará/neaktivní `runtime.night_loop`). Proto byly `night_summaries` prázdné a 14denní retention gate správně nepovolovala smazat stará `night_samples`.
- Nová pomalá údržbová cesta po aktuálním SOC výpočtu uzavře nejvýše **3 chybějící staré noci za jeden průchod**, pouze po 05:05 SEČ/SELČ a mimo sběrné okno. Stejný mechanismus zpětně uzavře staré úplné noci bez přepisování ostatních auditů.
- Souhrn obsahuje původní výpočty energetických toků a pokrytí, datum uzavření, počet surových řádků a **SHA-256 přes původní uložené bajty + přesné časy**, dále `status=sealed` pouze po ověření uloženého `night_sessions`, alespoň 400 aktivních vzorků, prvních/posledních minut v okně a alespoň 110 minut pokrytí.
- Neúplná noc má `status=incomplete` a **zůstává kompletně v raw historii**. Denní souhrn se ukládá `INSERT OR IGNORE`, nepřepisuje již uzavřené důkazy. Při retenci se SHA znovu přepočítá ze zdrojových řádků; při nesouladu je smazání odmítnuto.
- Stávající ACK/day/horizon/retention brány zůstávají. Nikdy se nemažou `night_sessions`, bezpečnostní události ani SOC rozhodnutí. Mazání se omezuje na již uzavřené staré detailní řádky, nikoliv aktuální či nepotvrzená data. SQLite automaticky nemusí zmenšit soubor, ale volné stránky znovu využije.

**Read-only soukromý replay na RPi:** nezávislá dočasná SQLite databáze z plných původních podkladů 23., 24. a 25. října. Uzavřeno 517 / 517 / 539 původních vzorků; pokrytí 119,75 / 119,75 / 119,61 minut; 3× shodný SHA-256 a pozitivní uzávěrová brána. Bez produkčního mazání.

## Regrese, odmítnuté pokusy a zbývající meze

- Syntetická sada `priority_shadow/tests/test_winter_retention_0634.py`: mráz/15 kWh, teplo, chybějící teplota, mráz/vysoká FVE, nedvojí příkon TČ, obě priority EV/baterie, sekundární čidlo, platnost as-of, uzavření 05:05, plný replay retence, částečná noc a úmyslně poškozená raw evidence.
- První syntetický test souhrnu očekával 120,00 minut, ale skutečná integrace oprávněně udala **119,75 min**, protože řada začíná v 03:00 a koncový vzorek 05:00 už nepatří do aktivního intervalu. Opraveno očekávání, nikoli algoritmus.
- Starý test retence s jedním libovolným „final” JSON zůstává historickým zápisem; nová bezpečnostní brána vyžaduje výhradně kompletní důkaz `status=sealed`.
- Hranice: zimní rizikový práh 2 °C / 70 % je zatím konzervativní **shadow heuristika**, ne samostatně kalibrované topné COP, odmrazování, spotřeba patrony ani přesný 3×25 A limit. Teplotní korekce samotného domácího profilu zůstává závislá na chronologickém holdoutu. Další noci ověřit proti skutečné spotřebě domu/TČ a časovým verzím Solcast.
- Verzování, Docker build, CI, aktuální lokální HA release a případné nasazení na RPi jsou různé stavy; žádný úspěšný test neznamená fyzický go-live.

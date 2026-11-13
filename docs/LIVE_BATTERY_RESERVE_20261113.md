# AKTUÁLNÍ PROVOZNÍ STAV 13.11.2026 09:10 SEČ: OSTRÉ ŘÍZENÍ POZASTAVENO

Výslovný požadavek: dnešní noc 13.–14.11.2026 musí zůstat jen pozorovací. Veškeré nové LIVE automatizace byly vypnuty, odpojeny od aktivní konfigurace Home Assistant Core a nesmějí se samy znovu zapnout ani následující noc bez nového schválení uživatele.

- 09:05: tři nové HEC LIVE HA automatizace vypnuty přes API. Stav vlastníka OFF, původní rezerva 20 % a limit EV 16 A potvrzen.
- 09:06: include hec_live_energy odstraněn z konfigurace; soubor package přesunut mimo /config do /share/hec-live-deploy-20261113/HELD_not_active_night_20261113.yaml (SHA-256 baeee4a14756747e23a6838d1a4feb37c80d1794e632156cb49abfd554f37708).
- Kontrola HA Core konfigurace PASS, restart Core PASS. Po restartu všechny tři nové automation entity hlásí unavailable, protože jejich zdroj již není aktivně načten.
- Původní addon local_energy_priority_shadow 0.6.32 je started / observe_only. Původní jiné HA automatizace zůstaly beze změn.
- Automatická reaktivace NEEXISTUJE. Další ostré nasazení teprve po novém výslovném rozhodnutí.

Zbývající text této stránky popisuje historickou implementaci a reálné krátké HW pilotní testy z rána 13.11., NIKOLI současný běžící režim.

---

# HEC LIVE v1 – skutečné noční řízení rezervy SolaX a proudu EVC

**Nasazení:** 13.11.2026, Raspberry Pi / Home Assistant Core 2026.11.1.  
**Aktivní doba:** od 02:59:40 příprava, 03:00–05:00 Europe/Prague fyzické řízení, po 05:00 vrácení převzatých limitů.  
**Zdroj:** `ha_packages/night_live_coordinator.yaml`, v HA `/config/hec_live_energy.yaml`, include `homeassistant.packages.hec_live_energy`.  
**Stávající doplněk** `local_energy_priority_shadow 0.6.32` nadále nezapisuje do zařízení; není vydáván za fyzický aktuační modul. Novou skutečnou akční vrstvu vykonává **Home Assistant automation engine** a zveřejňuje `sensor.hec_live_skutecne_rizeni`. Obě vrstvy jsou záměrně oddělené, takže lze zpětně hodnotit chyby fyzických změn proti stínovým výpočtům.

## Schválená funkce

Automatizace vychází ze skutečných entit:
- `number.solax_backup_discharge_min_soc` – minimální on-grid SOC v `Back Up Mode`, rozsah podle aktuální integrace 15–100 %, běžně před instalací **20 %**. Podle návodu SolaX se při dosažení minimálního SOC vybíjení do sítě/domácnosti zastaví, mimo-grid EPS rezerva se nastavuje samostatně. Proto v zimě lze chránit baterii i před domácím odběrem během levného nočního okna.
- `number.solax_api_max_charge_current_setting` – skutečně zapsaný limit SolaX EVC 6–16 A (před instalací **16 A**); stabilizace při 12 A, další regulace podle L1–L3.
- `sensor.solcast_pv_forecast_forecast_today` – forecast denní FVE. Starší než 30 hodin nebo chybějící se vyhodnotí konzervativně jako slabý den.
- `sensor.solax_inverter_solax_grid_current_l1/l2/l3` – reálné proudy po fázích, zvyšování proudu EV jen při dostupných údajích novějších 65 s. V ostatních případech se proud snižuje do 6 A; při naměřených **≥24,5 A** se wallbox přepne do Stop a vyžaduje ruční opětovné spuštění.
- `number.solax_main_breaker_current_limit=25 A` jako provozní předpoklad. Není to certifikovaný hard-real-time jističový regulátor.

Při převzetí je povinné: měnič v `Back Up Mode`, baterie a wallbox dosažitelné, EV zatím nenabíjí (méně 100 W), obě původní battery grid-charge automatiky neaktivní, správná hodnota nastavení jističe. Nepřevzít rozehraný `Manual Mode` nebo `Force Charge`.

### Rezerva podle predikce FVE

| Denní predikce | Minimální SOC během 03–05 | Ekonomická logika |
|---|---:|---|
| ≤15 kWh (nebo nedostupná/starší) | **100 %** | Nevybíjet baterii při levném nočním odběru; Tesla ze sítě |
| 25 kWh | ~79 % | Konzervativně chránit většinu zásoby |
| 35 kWh | ~57 % | Ponechat část kapacity pro ranní spotřebu |
| ≥50 kWh | **25 %** | Povolit využití domácí baterie v EV při předpokládaném doplnění ze slunce |

Vzorec v intervalu 15–50 kWh je interpolace `ceil(100−75×(PV−15)/35)`. Jde o **první reálně zapnutou heuristiku**, ne ekonomicky optimální model dokázaný pro každou domácí spotřebu. Stínový plán a pozdější měření se používají k další kalibraci. Předchozí pevný univerzální 7denní retention návrh se nevrací.

### Rozdělení výkonu / bezpečnost

1. První převzetí proběhne již **02:59:40**, ještě před obvyklým startem wallboxu ve 03:00. Nejdříve se limit EV nastaví nejvýše na 12 A; potom bateriová on-grid rezerva. Je-li EV už aktivní, regulátor rezervu **nepřepíná pod zátěží**.
2. Každých 30 s při nabíjení a validní vlastnické konfiguraci kontroluje proudy všech tří fází: při ≥22 A sníží limit EV na 6 A nebo o potřebný počet celých ampérů, při všech fázích <17 A zvyšuje postupně po 1 A, nejvýše na původní nastavení (max16 A). Neplatné/stará měření → snižovat, nezvyšovat.
3. Pokud některá fáze dosáhne 24,5 A, přepne nabíječku do `Stop` a vytvoří trvalé upozornění. Opětovné spuštění vyžaduje ruční zásah. Toto je nouzová ochrana, **nikoliv důkaz přesné reakce na milisekundové špičky**.
4. Neřídí nabíjení domácí baterie z distribuční sítě. Současný limit bateriového nabíjení 3 A byl ponechán; `Manual Mode/Force Charge` není bez fyzického dozoru aktivován. Existující denní automatizace 11–12 a 13–14 jsou beze změny.
5. Neovládá nastavení jističe, technické napětí sítě, bateriové DC proudy, vzdálené VPP registry ani neověřenou entitu `Battery Charge EVC`, která je na aktuálním HA `unavailable`. Její výrobcem podporované chování bylo potvrzeno v oficiální dokumentaci, ale bez dostupného zápisového readbacku ji nelze použít.

### Vlastnictví a rollback

Před prvním fyzickým povelem se do perzistentních HA helperů uloží *původní i požadovaná* rezerva baterie a limit EV, potom se zapne `input_boolean.hec_live_owned`. Pokud se aktuální hodnota liší od posledního vlastního povelu, automatika už tento parametr nepřepíše – upřednostní zásah jiného vlastníka.

Nezávislá HA automatizace se v **05:00** a každou další minutu mimo 02:59:35–05:00 pokusí vrátit pouze hodnoty, které stále odpovídají poslednímu vlastnímu povelu. Kontroluje fyzický stav 5 s po příkazu, po výpadku HA/konfiguračním restartu opakuje obnovu. Ruční zásah nepřepíše a vyvolá upozornění. Zůstane-li samotný HA vypnutý, nemůže zaručit obnovení v přesně 05:00; pokud původní nastavení zůstane zpřísněné, může tím dočasně omezit využití baterie. Upozornění: výrobce pro část těchto nastavení používá přetrvávající registry; neprovádět bez důvodu rychlé/příliš časté změny.

### Aktivace, rollback a důkazy

1. Před fyzickým testem:
   - Zdrojová konfigurace `/config/configuration.yaml` a `automations.yaml` uložena do `/share/hec-live-deploy-20261113/core-config-before.tgz`, SHA-256; nativní HA Supervisor partial backup **`492373aa`** obsahuje domácí konfiguraci bez databáze.
   - HW test za plně idle stavu: backup min SOC **20→25→20 %**, EV max current **16→15→16 A**; všechny čtyři nezávislé HA readbacky PASS; původní nastavení potvrzena.
   - `ha core check` s novým package PASS. Plný restart Home Assistant Core a kontrola entit/automatizací jsou samostatné validační kroky.
2. Pro emergency vypnutí automatizací lze HA vypnout entity `automation.hec_live_prevzeti_nocnich_limitu` a `automation.hec_live_fazovy_regulator_wallboxu`, ale **obnovovací automatizace musí zůstat zapnutá**, dokud není `input_boolean.hec_live_owned=off` a oba původní limity potvrzené. Po odpojení služby lze odstranit package include z `configuration.yaml` a restartovat Core. Uživatelská/ostatní původní automatizace se nesmí plošně přepínat.
3. Před restartem/downgrade HA nebo přesunem package musí být obnoveny všechny vlastní fyzické změny. Jednoduché přepsání na `20/16` bez porovnání není bezpečné, pokud jiný vlastník nastavení mezitím změnil.
4. První reálná noc je **14.11.2026**, dosud neproběhla. Úplnou fyzickou účinnost nastavení rezervy a jeho reakci v reálném společném EV režimu proto nelze předjímat. Ověřit peak proudy, SOC baterie, výkon EV, stav starých automatizací, skutečné ACK/readback, příkazové časy, stop/watchdog a vrácení do baseline. Při odchylce okamžitě vypnout převzetí a uvést parametry do bezpečného stavu.

**Otevřená omezení:** software není bezpečnostní zařízení místo 3×25 A jističe nebo SolaX DLB; fázové senzory nejsou atomický rychlý wattmetr, full physical battery charge není validovaný. Závěr o „100% funkčnosti“ lze udělat až po porovnání reálné noci. Nyní je řízení fyzických dvou parametrů přímo aktivované v HA a stínový doplněk pouze sbírá nezávislý důkaz.

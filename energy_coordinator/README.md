# Energetický koordinátor 0.5.0

Lokální aplikace Home Assistant OS pro Raspberry Pi 4 (aarch64). Runtime, data,
modely a přehledy zůstávají uvnitř HA. Režim je výhradně `observe_only`.
Žádný tento modul neovládá wallbox, baterii, vytápění ani staré automatizace.

## Stínový scénář 0.5

Přehled **Stínový plán** zobrazuje skutečný výkon domu a podmíněný výpočet
spotřeby domu při jiném čase nabíjení auta. Pokud je auto potvrzeně připojené,
algoritmus porovná hodinovou předpověď Solcastu, historický profil domu a
archivované nákupní ceny do zadaného času odjezdu. Všední den ani noční okno
nejsou tvrdým pravidlem: výrazný předpovězený přebytek může vyhrát i při
home office. Čas, kdy bude auto příště doma, systém nepředpovídá; scénář
předpokládá, že od chvíle výpočtu zůstane připojené do odjezdu.

Pro číselný návrh jsou potřeba tři **ověřené** hodnoty v možnostech aplikace:
`shadow_ev_ac_kwh_per_soc_pct` (dodaná AC kWh na jeden procentní bod SOC),
`shadow_ev_charge_power_kw` (dostupný výkon wallboxu v kW) a
`shadow_ev_ready_by_local` (čas HH:MM v Europe/Prague). Výchozí nuly/prázdný čas
nepředstírají kalibraci; graf do nastavení zobrazuje pouze naměřenou část a
důvod, proč nelze vydat scénář. Cíl SOC se čte z auta a zpřesňuje potřebu energie.

Plán se ukládá jako neměnný záznam s časem vydání a dostupností předpovědi.
Historický profil potřebuje aspoň dvě pokryté hodiny pro daný typ dne a hodinu;
neúplné tarify, neplatné stavy či stará data plán zablokují. Odhad přebytku
neověřuje, že ho domácí baterie nepohltí, ani cenu prodeje. Stínový scénář
nesmí být vydáván za prokázanou úsporu nebo bezpečný limit jističe. Jednou za
ukončený týden se porovná jeden archivovaný návrh za den s pokrytým měřením;
odchylka je popisná a nezměří úsporu. Hloubková AI analýza, návrhy automatizací
a společná optimalizace baterie a tepla vyžadují další kalibraci a nejsou
součástí 0.5.0.

## Co přidává 0.4

- Široký typovaný sběr: teploty/vlhkost, energetická a elektrická měření,
  meteorologické veličiny, sluneční geometrie a vybrané provozní stavy.
- Role místnost / venek / topná voda / elektronika nejsou odvozovány jen z jednotky.
  Neověřené role se archivují, ale automaticky neřídí domácnost.
- Metadata oblastí a zařízení, historie změn mapování; žádné GPS, kamery, osoby,
  zámky, soukromé kalendáře ani přihlašovací údaje.
- Verze hodinových/denních předpovědí `weather.*` přes `weather.get_forecasts`.
  Čas přijetí se nezaměňuje za čas vydání. Provider current není lokální měření.
- Porovnání hodinové teploty s vybraným místním čidlem: MAE, bias a RMSE po předstihu.
  Ostatní veličiny se archivují, jejich ověření bez lokálních čidel není předstíráno.
- Kalendář: den týdne, víkend, Workday/svátek podle HA, offset, DST fold,
  kalendářní sezóna oddělená od tarifní sezóny.
- Oprava EV/spotřebičových cen: konzervace kWh a dělení na tarifních, denních
  a měsíčních hranicích. Uvnitř intervalu jde o časové rozdělení; dlouhé mezery
  uchovají známé kWh jako neoceněné. Tarifní ekvivalent není faktura za síť.
- Oprava klasifikace notebooku v pracovně a průměru cyklů za skutečně pokryté dny.
- Solcast: hodinová realita, jednotný význam předstihu, oddělené pozdější testovací
  dny. Historické korekce mají označení holdout replay; skutečně publikované
  předpovědi se uchovávají zvlášť. Stav omezení výroby zatím není ověřený.
- Responzivní Ingress přehled: počasí, teploty, katalog, energie, EV a spotřebiče.
  Žádná externí knihovna/CDN a žádné vykreslování názvů čidel jako důvěryhodného HTML.
- 5 nových monitorovacích entit `sensor.energie_v4_*`, staré entity zůstávají.

## Nasazení

Zdroj v aktuální terminálové aplikaci SSH patří do `/local_apps/energy_coordinator` se slugem
`local_energy_coordinator`. Neodinstalovávat aplikaci a nemazat `/data/evidence`.
Před změnou vytvořit zálohu aplikace v HA. Kompilace a testy běží v Docker buildu,
ne v core-ssh, kde nemusí být Python. Změna GitHub větve sama nic v HA neinstaluje.
Interní GitHub updater je vypnutý; aktualizace repo aplikace obstará Supervisor.

Přechod ze staré lokální aplikace vyžaduje dvě instalace s odlišnými Supervisor ID.
Po ověřeném spuštění lokální verze 0.4.1 počkej na konzistentní zálohu
`/share/home-energy-coordinator/evidence.sqlite` a `evidence.json`. Přidej
`https://github.com/inenger/home-energy-coordinator-ha` do HA App Store.
Před prvním startem nové repo aplikace zastav `local_energy_coordinator`, aby
oba procesy současně nezapisovaly monitorovací entity a sdílenou portable zálohu.
Nainstaluj repo verzi a spusť ji; při prázdném novém volume sama převezme portable
databázi. V logu ověř `portable_restore` se stavem `restored`, verzi 0.4.1 a čerstvý sběr.
Teprve po ověření dat zapni automatické aktualizace u repo aplikace v HA.
Původní lokální aplikaci zatím neodinstalovávej; její Supervisor backup uchovej.

Nová karta v `dashboard/automatizace_v040.yaml` patří do záložky **Automatizace**
jako jedna ruční karta, nikoli do `configuration.yaml`. Grafy jsou v Ingress.

## Nastavení

`weather_enabled`, `weather_interval_seconds` (výchozí 3600), `weather_reference`
(výchozí NIBE BT1). Používají se již nastavené HA weather entity: nový externí
provider, geolokace ani API klíč není potřeba. Metadata se obnovují maximálně
jednou za šest hodin, stejně tak se při chybě nepokoušejí načítat každou minutu.

Výchozí role jsou v `config/telemetry.json`. Volitelné lokální změny lze uchovat v
`/data/evidence/telemetry-overrides.json` pod klíči mappings, appliances, include,
exclude. Obsah nepatří do veřejných exportů bez souhlasu. Označení oblasti v HA
není důkaz kalibrace čidla. API přístup má technicky širší práva než sběrná logika.

## Archiv a výkon

Původní tabulky zůstávají. Migrace pouze přidává tabulky; automatické mazání není
implementováno. Celý kontext se komprimuje, předpovědi/mapování deduplikují;
teplotní graf používá jednou zachycené hlášení, ne minutu starou kopii jako nový vzorek.
Limit DB zůstává 2 GiB a lze jej zvýšit v možnostech aplikace. Po dosažení limitu
se sběr zastaví s chybou, data se nemažou. Dlouhodobá automatická archivace,
událostní rychlý sběr a import staré HA historie jsou další práce, ne hotové funkce.
Při běžné analytice se čte omezené období, nikoli celá roční rozšířená telemetrie.
Minutový sběr není ochrana jističe.

## Co zatím netvrdíme

Nemáme ověřený celkový tepelný model domu, autonomní optimalizátor, prokázané úspory,
ani přesné SoH baterie. Katalog 11.5/10.4 kWh a 95% round-trip zůstává vstupem,
nikoli měřenou účinností celé sestavy. Pozorované kWh/změna SOC nejsou samy degradace.
Běžící 0.2/0.3 historie se neztrácí, nové environmentální časové řady začnou až
nasazením 0.4. Počty nalezených čidel se ověří na konkrétní instalaci.

## Ověření

`python -m unittest discover -s tests -v`

`python scripts/validate_release.py`

CI navíc sestaví a spustí kontrolu image pro skutečný cíl linux/arm64 pod emulací
(a linux/amd64), nikoli pouze nastaví štítek BUILD_ARCH. To stále nenahrazuje
kontrolu nasazení na fyzickém RPi4. Stav ověření je v docs/VALIDATION_V040.md.

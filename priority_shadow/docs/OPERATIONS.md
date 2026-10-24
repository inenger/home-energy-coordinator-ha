# Provoz, aktualizace a obnova

Tento postup popisuje runtime 0.6.4 na RPi/HA OS. Žádný zdejší krok se
neprovádí automaticky publikací do GitHubu. Pro aktuální identitu doplňků
a poslední ověření čti [projektovou paměť](../../MEMORY.md).

## Konfigurace

`config.yaml` je HA katalog a schéma; runtime čte `/data/options.json`.
`config/settings.example.json` je historický příklad společných modulů,
včetně starého updateru. Shadow entrypoint jej jako nastavení nenačítá.

| Volba | Výchozí hodnota | Význam |
|---|---|---|
| `mode` | `observe_only` | Jediný povolený režim |
| `planner_enabled` | `true` | Zapne výpočet SOC, nikoli řízení zařízení |
| `planner_approved_reserve_soc` | prázdná | Výslovná modelová rezerva 0–95 %; prázdná používá referenčních 15 %, které nejsou schválenou provozní politikou |
| `planner_inverter_ac_limit_kw` | prázdná | Potvrzený AC limit, číselný řetězec v kW, více než 0 a nejvýše 100; prázdná zůstává neověřená |
| `storage_limit_mb` | 2048 | Rozpočet SQLite souborů, schéma 512–8192 MB |

Překročení rozpočtu ukončí daný sběr s chybou; data se automaticky nemažou.
Neplatný řetězec fyzického parametru nenahrazovat domnělou hodnotou jen
kvůli zelenému stavu. Výchozí `boot: auto` se týká tohoto stínového doplňku,
nikoli doplňku InfluxDB v2, který má zůstat nespouštěný s `boot=manual`.

## První instalace a dashboard

Repozitář pro HA App Store je
`https://github.com/inenger/home-energy-coordinator-ha`. Stínový doplněk
podporuje `aarch64` a sestavuje se ze svého adresáře. Nová instalace má
vlastní `/data`; již existující lokální shadow se instalací nepřevede.
Před prvním startem vyřešit níže uvedenou migraci, pokud lokální shadow běží.

Potřebné entity a jednotky popisuje [datový kontrakt](DATA.md). Privátní seed
`soc-history.json.gz` musí vzniknout z auditované analýzy na stejném RPi.
Nevytvářet univerzální seed z katalogové kapacity. Pomocník musí být
`input_select.nocni_stinova_priorita` s přesnými možnostmi `Elektromobil`
a `Baterie SolaX`. Karta je `dashboard/night-priority-card.js`; její instalace
vyžaduje aktuální zálohu Lovelace a zachování ostatních karet a zdrojů.
Runtime sám kartu ani helper neinstaluje.

## Běžná diagnostika

Na RPi lze pouze číst metadata a logy přes `ha apps info <skutečný_slug>`
a `ha apps logs <skutečný_slug>`; používat slug ověřený na dané instalaci.
Nedokládat běh jen verzí ve staženém souboru. Ve výpisu začátku procesu
ověřit `version=0.6.2`, `mode=observe_only`, `device_actions=0` a následné
čerstvé `priority_collection=ok`. `soc_planner` má vlastní stav; úspěšný
sběr může současně nést nedostupný výpočet, proto kontrolovat obojí.

| Projev | Co ověřit |
|---|---|
| `waiting_for_inputs` | `missing_inputs`, jednotky, stáří, profil, pokrytí tarifu/FVE |
| `calculation_unavailable` | Seed a lokální schema, `error_code`; přesný důkaz v RPi, ne odhad příčiny z typu výjimky |
| `no_comparable_feasible_plan` | Společná potřeba EV/baterie a limity v dostupném okně |
| Neúplný horizont | Náhled nesmí vstoupit do noční relace jako platný plán |
| Chybějící/neplatný plán v relaci | Nejnovější rozhodnutí, den, TTL 30 minut, hash a úplný horizont |
| `STORAGE_BUDGET_EXCEEDED_NO_DELETE` | Velikost DB/WAL a volné místo; žádná automatická purge |
| Zastaralá karta | Stav senzorů, HTTP obsah/hash JS, resource URL a skutečné načtení v prohlížeči |

Rozlišovat úmyslné ukončení SIGTERM/143 od nové poruchy. Potvrdit očekávaný
stav služby a nový důkaz; historická chyba sama není nový incident.

## Záloha

- Autoritativní DB shadow: `/data/evidence/evidence.sqlite` uvnitř doplňku.
- Živý výstup: `/data/evidence/priority-live.json`; jde o poslední stav,
  nikoli náhradu plné rozhodovací evidence.
- Portable DB: `/share/home-energy-priority-shadow/evidence.sqlite`,
  konzistentní SQLite backup po úspěšném sběru přibližně jednou za hodinu
  a pokus při řádném ukončení procesu.
- Privátní seed/modelový kontext: `/share/home-energy-priority-shadow/soc-history.json.gz`.
- Projektová paměť na RPi: `/share/home-energy-priority-shadow/PROJECT_MEMORY.md`.

Portable kopie může být starší než aktivní DB a při selhávání sběru nemusí
vzniknout nová. Před aktualizací vytvořit HA backup doplňku, zálohu zdrojů,
voleb, konzistentní evidence i seedu a zapsat čas, verzi a SHA-256. Nekopírovat
samotný živý SQLite soubor bez WAL/backup API. Kopie i kontrola integrity
zůstávají na RPi. Hourly backup není potvrzením obnovitelnosti celého HA.

## Migrace lokálního shadow na repozitářový

Jde o samostatnou provozní změnu. Nynější dodávka do main ji neprovádí.
Repozitářový slug má jiný prefix, HA automaticky nepřenese privátní `/data`.
Shadow navíc při startu neimportuje portable DB automaticky: bez přenosu
by založil novou DB a následný backup mohl přepsat sdílenou portable kopii.

1. Načíst skutečný stav obou doplňků a připravit nezávislé časově označené
   zálohy DB, seedu, voleb a dashboardu mimo sdílené cíle zálohování.
2. V řízeném přechodu ukončit pouze lokální pozorovací proces; ověřit konec
   a konzistenci finální kopie. Původní koordinátor 0.5.3 tím není dotčený.
3. Přenést finální evidence do odpovídajícího `/data/evidence` nového
   doplňku ještě před jeho prvním startem; volby přenést přes ověřené HA
   rozhraní. Zachovat seed i původní nezávislé kopie v `/share`.
4. Na RPi ověřit integritu DB, počty a časové rozsahy relevantních tabulek,
   hash seedu a důležitých historických rozhodnutí před/po přenosu.
5. Spustit jediný publisher; ověřit verzi, sběr, plán, hash, monitory,
   dashboard a zachovanou historii. Starou instalaci zatím ponechat pro návrat.

Toto je kontrolní postup, nikoli hotový automatický migrační nástroj.
`scripts/migrate_local_to_repo.sh` patří starému původnímu doplňku a čeká
pevnou verzi 0.5.0. Pro shadow jej nepoužívat. Přenos do izolovaného `/data`
musí respektovat konkrétní možnosti Supervisor zálohy/obnovy; nehádat host cesty.

## Aktualizace a návrat

HA aktualizace z GitHubu se řídí verzí v katalogu a instalovaným zdrojem.
Lokální `local_...` instalace se mergem nestává repozitářovou. Dokumentační
commit bez změny 0.6.2 není nová runtime verze ani pokyn k restartu.
Při návratu obnovit odpovídající zdroje i konzistentní evidence z vlastní
zálohy; nespojovat souběžně dva publishery, nemaž původní historii.

# Vývoj, paměť a dokončené vydání

## Než začneš

Přečti kořenové [AGENTS.md](../../AGENTS.md), [MEMORY.md](../../MEMORY.md),
README a pravidla daného balíčku. Ověř současnou větev, commit, čistotu
pracovní kopie a skutečný stav RPi. Paměť uchovává předchozí rozhodnutí,
nepotvrzuje však dnešní stav služby. Pro tento projekt není cílovým strojem
`tds-dev`; skutečná data a provoz patří na RPi.

Nový shadow vyvíjej v `priority_shadow/`. `energy_coordinator/` je původní
samostatný doplněk 0.5.3; nekopírovat tam automaticky novější runtime.
Historické skripty `audit_soc_060.py`, `audit_soc_061.py` a `verify_soc_061.py`
mají verzi/metodu v názvu a mohou očekávat starší integrační rozložení.
Nejsou univerzální certifikací aktuálního veřejného balíčku.

## Přiměřené kontroly

Z kořene repozitáře:

```sh
python3 scripts/validate_versions.py
bash -n scripts/upgrade_local_app.sh
bash -n scripts/recover_missing_local_source.sh
bash -n scripts/migrate_local_to_repo.sh
bash scripts/test_local_source_paths.sh
(cd energy_coordinator && python3 -m unittest discover -s tests -q)
(cd priority_shadow && python3 -m unittest discover -s tests -q)
node --check priority_shadow/dashboard/night-priority-card.js
```

Skořápková simulace upgradu používá dočasné soubory a náhradu HA; neprovádí
živý upgrade RPi. Spouštět ji sekvenčně vůči testům, které mění pracovní strom
o `__pycache__`, aby se během tar archivace neměnil obsah zdrojů.

Ověřené počty pro 0.6.2: 285 syntetických testů shadow a 158 původního
doplňku. CI `.github/workflows/validate.yml` kontroluje obě sady, verze,
shell cesty a syntaxi karty při PR i po push do main. Zelené CI neprokazuje
fyzickou kapacitu baterie, úsporu ani vizuální správnost v HA prohlížeči.

Původní balíček má známý dluh: katalog/runtime 0.5.3, starší Python
metadata 0.5.2. Validator to u něj uvádí, nový shadow kontroluje přísně.
Neskrývat tento rozdíl tvrzením, že všechny verze původního balíčku souhlasí.

## Oprava a vydání

1. Uchovat protipříklad a původní důkaz. Přidat regresi přes celý dotčený
   tok; mapa chyb je v [FIX_HISTORY.md](FIX_HISTORY.md).
2. Opravit implementaci, aktualizovat dokumentaci a paměť. Při změně runtime
   sjednotit katalog, `core.VERSION`, Python metadata a changelog.
   Pouhá dokumentace nevytváří novou runtime verzi.
3. Ověřit relevantní kontroly. Pro skutečná data na RPi zaznamenat commit,
   hashe, období, metodu a omezení; privátní evidence nepatří do veřejného PR.
4. Zveřejnit větev/PR a ověřit jeho přesný head, změny a CI. „Lokálně
   commitnuto“, „na GitHubu“, „v main“ a „běží v HA“ jsou odlišné stavy.
5. Při zadání dokončit v main převést připravené PR z draftu, sloučit
   ověřený head a potvrdit `merged=true`, cílový obsah main a výsledné CI.
   Neponechat splněné zadání pouze jako návrh ke sloučení.
6. Nasazení/migraci posuzovat zvlášť. Merge nezmění zdroj lokálního
   `local_...` doplňku; nevytvářet kvůli němu druhý souběžný publisher.
7. Při provozní změně provést [zálohu a ověření](OPERATIONS.md), potom
   aktualizovat stav v paměti a oznámit přesně dosažený výsledek.

Publikační dodávka je [PR #4](https://github.com/inenger/home-energy-coordinator-ha/pull/4).
Obsahuje celý build context, testy, dokumentaci a paměť; soukromá historie
pracovních integračních větví se nezveřejňuje. Lokální integrační commit
`e469e51` identifikuje dřívější ověřený zdroj 0.6.2, není náhradou GitHub SHA.

## Jak aktualizovat paměť

`MEMORY.md` má zůstat stručný vstupní kontext: aktuální verze/zdroj, přijaté
podmínky, autorita uživatele, nejdůležitější chyby a otevřené předpoklady.
Podrobné postupy patří do této dokumentace, reprodukce do testů a mapa
nálezů do FIX_HISTORY. Při změně závěru zachovat vysvětlení, proč dřívější
test nestačil. Soukromé důkazy zůstanou na RPi; jejich místní identifikátory
nejsou veřejnými naměřenými daty.

RPi kopie `PROJECT_MEMORY.md` je provozní kopie, nikoli další nezávislý
zdroj pravdy. Aktualizovat ji po ověřené dodávce. Žádný soubor nezaručuje,
že jej jiná AI automaticky načte; proto na něj odkazují pravidla AGENTS.

## Otevřené úkoly před fyzickým řízením

| Úkol | Kritérium dokončení |
|---|---|
| Rezerva a EV potřeby | Výslovně potvrzené hodnoty a odjezdy, bez odvozování z registrů |
| Fyzické limity a fáze | Ověřené znaménko, mapování, limity BMS/měniče a proudové měření |
| AC účinnosti a FVE hranice | Nezávisle identifikovaný převod a označené omezené intervaly |
| Společná ekonomická validace | Reálné noční relace, shodné pokrytí, potřeby a konečná zásoba |
| Dashboard v prohlížeči | Doložené vizuální ověření skutečného HA zobrazení |
| Migrace lokálního shadow | Ověřená obnova celé evidence a jediný publisher, zvláštní provozní dodávka |
| Budoucí koordinace automatizací | Jediný vlastník zásahů a kontrolovaný návrat stavů po okně |

Dokud nejsou vyřešené relevantní podmínky a výslovně zadané ostré řízení,
zůstává `observe_only`, bez fyzického adaptéru.

# Jak se vybírá cílové SOC

Implementace: `soc_planner.py`, politika
`soc-energy-scenarios-v3-conserved-ac-flows`. Výpočet je deterministický,
bez volání AI. AI může na RPi kontrolovat důkazy a navrhovat změny kódu;
není součástí rozhodování ani podmínkou běhu.

## Vstupy a jejich skutečná role

| Vstup | Použití v 0.6.2 |
|---|---|
| Aktuální SOC SolaX | Výchozí zásoba, převedená přes empirickou mapu energie/SOC |
| Hodinová/půlhodinová FVE | Rozložení výroby v čase, pokrytí domu, dobití a volné místo |
| Východ slunce | Uložený a zobrazený kontext; samostatná podmínka podle sunrise není implementovaná |
| Roční období | Sezónní výběr profilu domu a korekce FVE, nikoli pevný zimní/letní cíl |
| Historická spotřeba domu | Profil domu po odečtení EV, zahrnuje vytápění i patronu |
| Teplota a počasí | Teplotní výběr pouze po úspěšném kauzálním holdoutu; jinak sezónní profil |
| Hodinový nákupní tarif | Již vypočtená smluvní cena z `sensor.cez_indi_cenik`; algoritmus ji nepřepočítává |
| EV | Zbývající potřeba do cíle, připojení, proudové limity a zvolená preference |
| Výkonové limity | Oddělené nabíjení/vybíjení, společný DC port a potvrzený společný AC limit |

Využitelný začátek výroby se tedy neodvozuje jen z astronomického východu.
Výstup `first_sustained_pv_cover_at` označuje první alespoň hodinové souvislé
pokrytí modelové spotřeby FVE po 05:00. Je diagnostickým výsledkem simulace;
není samostatnou optimalizační podmínkou.

## Postup výpočtu

1. Určí nejbližší okno 03:00–05:00 v `Europe/Prague` a horizont do
   následujících 03:00. Po 05:00 plánuje další noc. Časy ukládá s offsetem;
   pět reálných minut před oknem počítá v UTC i při změně času.
2. Vybere předpovědi a tarif, které byly skutečně zachyceny nejpozději při
   rozhodnutí. Nepoužije verze starší 30 hodin; rozporné shodně nové údaje
   nejsou považované za platnou informaci. Kontroluje součet denní FVE.
3. Rozdělí horizont po nejvýše půlhodinových úsecích a hranicích vstupů.
   Doplní domácí profil, korekci FVE a spodní/horní varianty obou profilů.
4. Vyzkouší variantu bez síťového dobíjení (`target_soc_pct=0`) a cíle
   po pěti procentních bodech od zaokrouhlené modelové rezervy do 95 %.
   Nula neznamená vybití na nulu, ale nulový požadavek na síťové dobíjení.
5. Každý cíl simuluje pro centrální scénář, slabou FVE/vysokou spotřebu
   a silnou FVE/nízkou spotřebu. Pravděpodobnosti scénářů nepředstírá.
6. Vyřadí cíle, které ve všech scénářích nesplní EV potřebu (tolerance
   0,05 kWh), modelovou rezervu a požadovaný SOC v 05:00 (tolerance 0,5 bodu).
7. Porovná nákupní náklad po odečtení stejného ocenění konečné zásoby.
   Konečná energie nad rezervou se oceňuje nejnižší nezápornou cenou
   nočního okna. Příjem z přetoků se v této účelové funkci neoceňuje.
8. Vybere nejmenší nejhorší rozdíl vůči nejlepšímu přípustnému cíli
   v každém scénáři (minimax regret). Při shodě preferuje menší nákup
   na dobíjení a pak nižší cíl. Uloží varianty, důvody a hash rozhodnutí.

Letní kombinace časné silné výroby a dostačující zbylé zásoby může zvolit
žádné dobíjení; zimní pozdní slabá výroba může vybrat vyšší SOC. Konkrétní
20 % + 50 kWh ani den s 6 kWh nejsou pevná pravidla zaručující daný cíl:
rozhodují časový průběh, spotřeba, cena, EV a limity společně.

## Fyzikální model a priority

SOC není lineární kapacita v kWh. Model používá směrové empirické křivky
nabíjení/vybíjení, DC ztráty a obálku nejistoty. Nejde o měření jmenovité
kapacity ani SOH. AC→DC účinnost ze sítě 0,90 (citlivost 0,85–0,95),
AC výstup 0,977 a PV převod 0,966 jsou modelové předpoklady, nikoli úplná
nezávislá kalibrace celého řetězce. Původ i hodnoty jsou v uloženém modelu.

Během levného okna se modelově nevybíjí do domu. EV i baterie sdílejí
konzervativní rozpočet odvozený z 22 A/fázi, napětí a účiníku 0,90.
Budoucí dům je ve výpočtu rozdělen po fázích odhadem; to není ochrana jističe.
EV má buď nulový příkon, nebo alespoň proud odpovídající 6 A na třech fázích.
Dokončení EV nebo cíle baterie rozděluje úsek na skutečné dílčí intervaly.
PV a síť nesmějí překročit společný DC nabíjecí limit; PV a vybíjení sdílejí
potvrzený AC limit měniče. Chybějící potvrzení AC limitu vytváří varování.

## Reference, platnost a chybějící data

| Denní FVE v referenční tabulce | Referenční SOC |
|---|---|
| méně než 5 kWh | 90 % |
| 5 až méně než 10 kWh | 80 % |
| 10 až méně než 15 kWh | 70 % |
| 15 kWh a více | 30 % |

Tabulka je srovnávací/legacy reference. Nenutí scénářový optimalizátor
vybrat 30 %. Starý YAML `night-charge-shadow.yaml` je také samostatná
tabulková reference, nikoli náhrada aktuálního Python plánovače.

Chybějící vstup není nula. Bez historie, profilu, EV potřeby či souvislého
tarifu/FVE nemusí vzniknout návrh. Zkrácený horizont může být náhled, ale
noční relace přijímá pouze úplný, hashově platný návrh pro daný den,
nejvýše 30 minut starý. Novější neplatný návrh odvolává předchozí.
Při chybě se zobrazí pouze referenční tabulka; nevzniká fyzický povel.

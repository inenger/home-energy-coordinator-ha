# Projektová paměť · Home Assistant / energie

Aktualizace: 23. 10. 2026. Tento soubor je verzovaný pracovní kontext;
nenahrazuje čerstvé ověření zařízení, GitHubu ani konfigurace.

Dokončená publikace ověřena 23. 10. 2026: [PR #4](https://github.com/inenger/home-energy-coordinator-ha/pull/4)
je sloučený do `main`, merge commit `841921123c9a1da41c9923c6338334bdf8a90f9a`.
CI PR i [CI hlavní větve](https://github.com/inenger/home-energy-coordinator-ha/actions/runs/40006366562)
prošly. V main ověřeny dokumentace, paměť a katalog shadow 0.6.2.
Tato publikace neprovedla migraci ani restart běžících HA doplňků.

## Stav a zdroje

| Oblast | Poslední ověřený stav | Pravidlo |
|---|---|---|
| Původní doplněk | RPi: `6696af1a_energy_coordinator`, 0.5.3, běží | Při vývoji nového stínového doplňku jej neaktualizovat |
| Stínový doplněk | RPi: `local_energy_priority_shadow`, 0.6.2, běží, observe_only | Počítá návrhy; fyzické povely se neposílají |
| Repo | `inenger/home-energy-coordinator-ha`, veřejné | Kód a obecná dokumentace; soukromá evidence zůstává na RPi |
| Integrace | `main`, [PR #4 sloučený](https://github.com/inenger/home-energy-coordinator-ha/pull/4) | Samostatný kompletní balíček `priority_shadow/`, původní balíček beze změny; dnešní nový head vždy ověřit |
| Zdroj před publikací | Lokální integrační commit `e469e51` | Obsahoval i privátní auditní zprávy; celá tato historie se veřejně neposílá |
| Veřejné zdroje | `priority_shadow/{energy,config,tests,dashboard}` | Autoritativní adresář dalšího vývoje stínového balíčku |

Starší integrační větve měly nový kód ve sdíleném `energy_coordinator/energy`;
na RPi se balíček sestavoval jeho kopírováním. Před další úpravou vždy ověř
větev a skutečný build context. Pouhé tři soubory v `priority_shadow/` nestačily
pro instalaci z GitHubu. Nový veřejný balíček obsahuje potřebné zdroje přímo.
Jedinou úpravou Python modulu při zabalení je sjednocení `energy.__version__`
s existujícím `core.VERSION`; funkční moduly odpovídají ověřené 0.6.2.

Publikační větev sama nepřepíná RPi na repozitářový doplněk. Repozitářová
instalace má jiný Supervisor slug a oddělené `/data`. Před migrací jsou nutné
záloha, kontrolovaný přenos evidence a ověření, že neběží dva publishery
stejných monitorovacích entit. Existující lokální doplněk se tímto PR nemění.

## Cíl a neměnné podmínky

- Dobít SolaX během levného okna 03:00–05:00 Europe/Prague na účelný cíl;
  zachovat prostor pro pozdější FVE. Celodenní soběstačnost není požadavek.
- Zohlednit SOC, načasování využitelné výroby, hodinovou prognózu FVE,
  sezónní spotřebu domu bez EV, potřebu auta a známý nákupní tarif.
- Tarif byl uživatelem potvrzen. Nevytvářet paralelní odhad tarifu ani měnit
  jeho kalendář podle počasí.
- Srovnávací tabulka od verze 0.5.9: pod 5/10/15 kWh cíle 90/80/70 %;
  od 15 kWh včetně 30 %. Primární návrh nové verze je scénářový optimalizátor.
- Referenčních 15 % není schválená provozní rezerva. Účinnost AC→DC,
  BMS, topologie měniče a mapování fází nejsou automaticky ověřené.
- `live_ready=false`, žádný fyzický akční adaptér. Syntetický test není
  naměřená úspora a skutečný SOC není realizovaný výsledek neprovedeného plánu.

## Poučení z oprav

1. Předpověď musí být zachycená nejpozději při rozhodnutí. Při holdoutu
   nepoužívat skutečnou budoucí teplotu místo tehdy dostupné prognózy.
2. Plánovač a replay sdílejí okamžitou alokaci. Auto má nulový nebo přípustný
   minimální proud; krátká relace musí mít skutečný časový úsek.
3. Síť a PV sdílejí DC nabíjecí port. PV a vybíjení sdílejí potvrzený AC
   limit měniče. Nabíjení a vybíjení mají nezávislé registry.
4. Fázový rozpočet není ekonomická AC bilance. PV pro auto se musí odečíst
   od skutečného nákupu a nesmí se současně vykázat jako stejný přetok.
5. Ověřovat poslední návrh, TTL, hash i úplný horizont. Nový neplatný návrh
   odvolává starý. Osiřelá legacy relace není již rozběhnutý legacy model.
6. Po výpadku nepřipojit znovu předchozí vzorek do nové EV relace. Pro
   kalibraci potřebujeme souvisle pozorovaný začátek a konec.
7. Kvalita domu/EV, PV čítače a znalosti omezení jsou samostatné masky.
   Neznámé omezení není False; neúplné podklady nejsou nula.
8. PV předpověď i skutečnost integrovat na stejných pozorovaných intervalech.
   Replay a review potřebují stejné brány platnosti návrhu.
9. DST testovat přes celou cestu review, nikoli pouze časovou pomocnou funkci.
   Pět reálných minut před 03:00 počítat v UTC.
10. Hash plného rozhodnutí vytvořit až po metadatech, bez pole samotného hashe.
    Graf SOC má výchozí bod a skutečné koncové časy úseků.

Konkrétní regresní mapování: `priority_shadow/docs/FIX_HISTORY.md`.
První závěr „vše opraveno“ byl příliš široký; další audit odhalil obnovenou
relaci a jiné návaznosti. Netvrdit absenci všech chyb jen z počtu testů.

## Poslední ověření a otevřené věci

- 0.6.2 na RPi: 285 testů, sedm opakovaných nezávislých reprodukcí opraveno,
  5 000 kontrol bilance baterie; po nasazení zdravé sběry, čerstvý návrh,
  ověřené hashe a zachovaná historie. Jde o stav ověřený 23. 10., ne trvalý slib.
- Karta: HTTP/hash a renderer s náhradním DOM ověřeny. Vizuální kontrola
  skutečným prohlížečem dosud není doložená.
- Úplná společná ekonomická validace EV a baterie v reálných nocích stále
  chybí; historický replay bez EV ji nenahrazuje.
- Před ostrým řízením vyřešit potvrzené rezervy, fyzické limity, fáze,
  reakce starých souběžných automatizací a realizovanou validaci.
- Dosavadní lokální commity a nasazení nebyly automaticky publikací na
  GitHubu. Od nynějška ověřit GitHub head/PR a CI zvlášť a uvést přesný stav.
- Uživatel 23. 10. výslovně zadal dokončit sloučení do `main` a kompletní
  dokumentaci s pamětí. Nenechávat hotovou dodávku pouze v draft PR. Merge
  ověřit přes stav PR, obsah `main` a CI; změna zdroje lokálního HA doplňku
  není součástí tohoto sloučení.
- Původní balíček má již na main starší `pyproject`/`__init__` metadata 0.5.2,
  zatímco runtime a katalog jsou 0.5.3. Tato větev do původního balíčku
  nezasahuje; nový stínový balíček má verze sjednocené a kontrolované CI.

## Postup další práce

1. Přečíst paměť a pravidla; zjistit branch, verze a poslední GitHub/HA stav.
2. Reprodukovat problém před opravou a zachovat původní důkaz.
3. Opravit relevantní celek a přidat regresní protipříklad.
4. Spustit přiměřené syntetické kontroly; skutečná data zpracovat jen na RPi.
5. Při schváleném nasazení ověřit zálohu, aktuální konfiguraci, source hash,
   runtime, čerstvý návrh a zachování starých dat.
6. Aktualizovat paměť/changelog, publikovat povolený obsah do pracovní větve,
   ověřit GitHub/CI. Nezaměnit commit, PR, merge a skutečné nasazení.

## Dokumentace a dokončování dodávky

- Rozcestník je v kořenovém README; technická dokumentace v
  `priority_shadow/docs/{ARCHITECTURE,ALGORITHM,OPERATIONS,DATA,AUTOMATIONS,DEVELOPMENT}.md`.
- Paměť je soubor v repozitáři, nikoli příslib automatické paměti všech AI.
  Každý další agent ji musí nejprve načíst spolu s pravidly.
- Východ slunce je dnes zaznamenaný kontext. Výpočet spotřeby před využitelnou
  FVE řeší časový profil výroby; nepřisuzovat sunrise samostatnou rozhodovací
  podmínku, která v kódu není.
- Tabulka ≥15 kWh → 30 % je reference, ne tvrdý limit scénářového návrhu.
- `config/settings.example.json` je sdílený historický příklad, nikoli
  provozní nastavení tohoto entrypointu. Aktivní volby určuje `config.yaml`.
- `scripts/migrate_local_to_repo.sh` je starý postup pro původní doplněk
  s pevnou verzí 0.5.0; není migrací stínového doplňku. Shadow při startu
  automaticky neobnovuje `/data` z portable kopie v `/share`.
- Poučení z této dodávky: „na GitHubu“ není „v main“. Při zadání dokončit
  publikaci provést také autorizovaný merge a ověřit hlavní větev; uvést
  přesný dosažený stav a zbývající provozní kroky.
- Dokumentační doplnění nemění runtime 0.6.2; nevydávat kvůli němu novou
  provozní verzi doplňku. Původní automatizace ani data se tím neupravují.

## Opravy připravené 24. 10. 2026 · 0.6.3

Nový zdroj je v `priority_shadow/`, politika SOC v4 a priority v9. Nedosažitelný
žádoucí cíl EV vede k přiznanému částečnému plánu podle preference, ne ke
zrušení celého plánování baterie. Minimum a odjezd zůstávají nepotvrzené;
neodvozovat je z nastaveného cíle. Obě priority přebírají vlastní cílové SOC.
Částečné varianty mají různé splnění EV potřeby, nejsou důkazem úspory.
Zamítnuté plány nově archivují vstupy i kontext předpovědí a modelů.

Poučení z chybného reportu: `sensor.solax_run_mode` je oddělený od
`select.solax_charger_use_mode`. Nesoudit celý režim z hodnoty selectu.
Podrobná oprava a privátní report zůstávají na RPi. Historické chyby
nepřepisovat; při změně diagnostického pohledu uchovat původní kontext.

Read-only replay nové verze proběhl na RPi. Je označený jako rekonstrukce,
protože původní zamítnuté plány neměly úplné vstupy; přenesené pole limitu
má uvedený starší zdroj. Skutečné záznamy ani původní relace se nepřepisují.
Tato dodávka sama nepřevádí lokální doplněk na repozitářový; poslední ověřený
běžící shadow je stále 0.6.2. Nasazení zdroje 0.6.3 není prokázané mergem.

# Projektová paměť · Home Assistant / energie

Aktualizace: 24. 10. 2026. Tento soubor je verzovaný pracovní kontext;
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

## Opravy dodané 24. 10. 2026 · 0.6.3

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

Publikace 0.6.3 dokončena: [PR #5](https://github.com/inenger/home-energy-coordinator-ha/pull/5)
sloučen do main, merge `6199c1be72c1b182f0e9f5f4dff74eff40939f8e`.
[CI hlavní větve](https://github.com/inenger/home-energy-coordinator-ha/actions/runs/40064317074)
prošlo; 296 testů shadow, 158 původního balíčku a spustitelný test karty.
Finální zdroj byl znovu přehrán na RPi; soukromé důkazy jsou v recovery
adresáři analýzy, nikoli ve veřejném repozitáři. Provozní addon ani dashboard
nebyly touto dodávkou aktualizované; stále rozlišovat publikaci a nasazení.

## 0.6.4 · maximální účelné využití přípojky

Uživatel výslovně požaduje využívat přípojku 3×25 A, při prioritě auta
ponechat EV požadovaný výkon a pro Solax využít zbytek až do účelného cíle.
Původní závěr o nízkém cíli nelze vydávat za čistě ekonomické optimum:
vyšší cíle byly předem vyřazené kvůli pevnému rozpočtu 22 A / 0,9 a
povinnému dosažení cíle i v nepříznivém scénáři. Nově jsou požadovaný
cíl a dosažitelné SOC oddělené; nedosažený cíl může být ekonomicky vybrán.

Nový modul `phase_budget.py` počítá kandidáta z předchozích nočních měření
U/P/I a domu bez EV; archivuje zdroj a počty vzorků. Používá 25 A minus
pozorované kladné skoky zátěže a odhad účiníku; explicitní starý fallback
zůstává pouze při nedostatku měření. Rozpočet sdílí plán, relace a replay.
Nesmí být prezentován jako certifikovaná jističová ochrana: vzorkování
neověřuje rychlé špičky, latenci ani nový spotřebič a model zůstává
observe_only. Ověření rezerv, AC limitu a fyzického řízení zůstává otevřené.

Validace: 306 syntetických testů shadow, 158 původního balíčku, renderer
karty, metadata a simulace upgrade cest. Read-only přehrání finálních
zdrojů na RPi uchovává staré důkazy a vlastní manifest 36 modulů. Dostupná
historie neobsahuje předokenní vstupy pro plnou rekonstrukci další starší
noci; nepoužívat pozdější návrhy jako tehdy dostupné vstupy. Výsledek je
rekonstrukce, ne uskutečněné nabíjení ani prokázaná úspora.

Při této práci ověřeno: runtime lokálního shadow stále 0.6.2, původní
doplněk 0.5.3; žádná aktualizace, restart ani změna starých automatizací.
Publikaci 0.6.4 ověřit samostatně na GitHubu a CI; tato poznámka sama
neznamená merge ani nasazení.


## 0.6.5 · okamžitá stínová alokace
Implementováno oddělení okamžitého max-fill od ekonomického SOC, explicitní
mapování proudů a kalendářní audit opožděného DST resetu. Viz
priority_shadow/docs/MAX_FILL_065.md. Starší relace se nepřepisují.
Testy ani merge nedokazují fyzickou odezvu; nasazení a CI ověřovat zvlášť.
Soukromé podklady zůstávají mimo veřejný checkout na RPi.


Stav dodávky 0.6.5: nasazení lokálního shadow na RPi bylo ověřeno přes
Supervisor a čerstvé monitory; režim observe_only, bez akčního adaptéru.
325 syntetických testů, metadata a renderer karty prošly. Původní koordinátor
a provozní automatizace zůstaly beze změny; stará noční evidence zachována.
Uživatel výslovně schválil veřejnou publikaci kódu a obecné projektové paměti.
Soukromé měřené řady a reporty nejsou součástí publikace. GitHub CI a merge
ověřovat samostatně; další provozní změna není součástí publikace.


## 0.6.6 · Odolnost souhrnů a zdraví sběru

Neúplná pole fází vyžadují párování podle explicitního phase ID, nikoli indexu. Souhrn publikuje počty dostupných proudových měření; neznámé fáze nejsou nula. Chyby uzavření jednotlivé noci jsou izolované od dalšího sběru/alokace/publikace. Nové souhrny mají append-only revizi; existující evidence se nepřepisuje. Při selhání sběru se zneplatní návrhy a zobrazí poslední úspěch, při úplném výpadku publikace funguje časová kontrola karty.

Ověření: 331 syntetických testů a renderer karty, včetně observe→finish→restart/další noc→publisher. Samostatná lokální instalace0.6.6 byla ověřena v observe_only s čerstvými monitory a dokončením dříve nedokončeného souhrnu. Původní koordinátor0.5.3 zůstal beze změny. Kontrola původních řádků evidence a konfigurace je oddělená od CI. Soukromé rekonstrukce a číselné provozní výsledky nejsou součástí veřejného repozitáře. Recorder změn stavů neověřuje heartbeat; jeho retrospektivní scénář musí tuto nejistotu uvést a nesmí se vložit jako původní živá relace. Stav veřejné publikace této verze ověřit zvlášť.


## 0.6.7 · Stínový řídicí deník celé relace

Implementován oddělený persistentní control_journal: snapshot vyjmenovaných automatizací a parametrů, virtuální převzetí, změny A DC dle aktuálního výkonového návrhu, stop a předání. Původně vypnutá automatizace se nezapíná. Ruční/cizí změny a chybějící stavy se rozlišují; restore_pending se dohání po restartu bez zpětného datování. Dokud je předchozí návrat nedokončený, nevznikne druhý virtuální vlastník. Výpadek kolekce zapisuje virtuální stop, nikoli pokračující domnělé nabíjení.

Karta má časovou osu, graf navrženého a skutečného limitu a naměřeného proudu, statistiky a porovnání návratu. HA history API vyžaduje explicitní significant_changes_only=0 a plné atributy bez minimal_response; jinak se ztratí změny deníku při neměnném stavovém textu. Přenos je přírůstkový a události se deduplikují podle ID.

357 Python testů a Node renderer prošly, včetně celé syntetické120min relace, restartu, výpadku, konfliktů a skutečných dat monitoru při renderování. Lokální HA instalace0.6.7 ověřena started/observe_only s novým čerstvým monitorem, historií recorderu, shodou zdrojů/karty a zachováním všech kontrolovaných původních řádků evidence. Původní0.5.3 a provozní automatizace beze změny. Žádný fyzický akční adaptér nebyl přidán.

Seznam automatizací vychází z kontrolované konfigurace, ale změny definic YAML nejsou automaticky ověřovány za běhu; config_live_validation=false a live_ready=false. Neověřené dopady na tepelnou zátěž, účinnost, reakční rezerva a fyzický návrat se nesmějí vydávat za vyřešené. Soukromé důkazy zůstávají na RPi. Veřejná publikace0.6.6 byla blokována a další souhlas k veřejnému obsahu zatím nepřišel; tato0.6.7 je lokální pokračování a nebyl proveden další pokus o publikaci.


## Frontend0.6.7-r1 · zpětný deník
Karta přijímá výslovný samostatný archiv rekonstrukce přes autentizovaný recorder. Události mají původní modelové časy, záznam v HA má dnešní skutečný čas. Původní SQLite ani živá monitorovací entita se nepřepisují. Držení recorder hodnot a převzetí chybějících metadat z pozdějšího snímku musí být výslovně označené. Kontrola úplnosti částí/událostí/vzorků a oddělení živé relace ověřené Node testy i na soukromém archivu na RPi. Backend0.6.7 bez restartu; veřejná publikace neprovedena.


## Frontend0.6.7-r2 · neplést stav, nastavení a dostupnost
Normal Mode v run_mode a Back Up Mode v charger_use_mode mohou být současně platné. Ověřovat oba stavy i oddělené registry v aktuálně instalované integraci, nikoli nahrazovat jeden druhým. Rozporné P/U/I není výpadek sběru. Přesná příčina zařízení vyžaduje další důkaz; timestampy změn recorderu nejsou atomický fyzický snímek. Deník nyní uvádí entity, provozní kontext a konkrétní auditní důvod; původní důkazy zachovány.27control testů a UI regrese prošly. Zdroj backendu0.6.7 nezměněn, žádný restart/řízení/publikace.


## 0.6.8 · přechod na logický výkonový stín
Dynamický Battery Charge Max Current se nepoužívá jako budoucí akční návrh. Nové tabulky ram_control_* drží výkonové intent/wire_command=null, nula EEPROM zápisů. Persistentní nastavení se pouze čtou; snapshot/virtual pause/předání automatizací zůstávají. Explicitní Normal Mode a validace stáří/skew, dva nové snímky, rampa, logická10s platnost; cílový interval5s v nočním sběru. Planner/souhrny/audit/backup jsou v samostatném vlákně. Collector zachovává skutečný HA last_reported přes template; fyzický heartbeat se nepředstírá.
Před fyzickým adaptérem rozřešit Direct Mode8 mapování0xA6=ExecDuration,0xA7=NextMotion; místní direct entity označuje poslední jakoTimeout. Výrobce potvrzuje port baterie, fyzický AC/DC převod a vypršení je nutné ověřit. Čitelné readbacky ani verze firmware nejsou potvrzením řízení. live_ready=false. Soukromá evidence naRPi, veřejná publikace neprovedena.

Lokální nasazení0.6.8 ověřeno started/observe_only, původní0.5.3 beze změny.375syntetických testů, renderer a čerstvé monitory prošly; zachování všech baseline řádkůSQLite a chráněných konfigurací ověřeno. Novéprodukční RAM tabulky jsou před prvním oknem prázdné; modelové testy se do nich nevkládají. Veřejná publikace nebyla provedena.


## Frontend 0.6.8-r1 · verze a meze rekonstrukce
Archivní banner používá software_version z provenance, nikoli pevné označení0.6.7; starší manifesty mají fallback a hodnota je escapovaná. Renderer ověřuje celou cestu s0.6.8. Podmíněný 5s replay se ukládá odděleně od původní evidence a obsahuje explicitní předpoklad nových souvislých hlášení. Recorder změn nedokládá historické last_reported; přísný výpočet bez tohoto údaje nesmí převzít řízení. Nově zapnutá readback čidla se do starší noci nedoplňují dnešními hodnotami. Backend se kvůli této UI opravě nemění ani nerestartuje. Soukromé podklady zůstávají naRPi, veřejná publikace neprovedena.


## Audit 0.6.8 · 29. 10. 2026 · neopravené nálezy
Hloubkový audit přesného lokálního11835fb odhalil mezery přes úspěšných375 testů. Reprodukováno: nadlimitní monitorovací atributy a chybějící kontrola úplnosti živé historie; opožděná kontrola aktivního readbacku při prvním převzetí; společný podpis EV/SolaX dovoluje růst nad stejnými fázovými reporty; chybějící TTL vzdáleného vlastníka; vnitřní výjimka deníku neodvolá uložený intent a sběr zůstáváok; grid energie zůstává ideální při rampované baterii; vyřazené fáze mizí z proudových statistik; poslední úsek lease se při expiraci nezapočítá. Osm nových kontraktů na zmrazeném zdroji selhává, UI má další protipříklad. Recorder limit ověřen vHA2026.10.4 a skutečném provozním logu. Nejde o vydanou opravu. Runtime0.6.8/0.5.3 a archiv zůstaly beze změny, žádné fyzické povely ani veřejná publikace. Před ostrým řízením opravit a ověřit celé návaznosti. Audit samotný nemění runtime verzi.


## 0.6.9 · opravy auditu
Implementovány A01–A09. Nové owner_errors vyžaduje čerstvé Disabled z0x100 i0x1A0, dvě celé nové sady fázových hlášení SolaXu nezávislé naEV. Výjimka deníku vede do nulového intent/failed health; bilance sítě se shoduje s rampou a platným úsekem lease. Raw proudy mají samostatnou kvalitu. Monitorovací byte budget14k používá bezztrátové zlib JSON/SHA, ne tichý ořez. Trvalý journal_transport má per-day cursor, multipart, skutečné recorder receipts, opakování a oddělený worker; potvrzovací čas pro historii je HA timestamp. Frontend ověřuje hash/velikost/počty a rozbaluje nové i staré cesty. Nepotvrzené části zůstávají vSQLite, fyzické řízení stálefalse. Soukromé doklady naRPi. Stav nasazení a finální kontroly ověřit podle soukromého completion; tento záznam sám nepotvrzuje nasazení ani publikaci.


Ověřené dokončení0.6.9: lokální shadow naRPi started/observe_only, původní0.5.3 a automatizace zachované.394 Python testů, oba Node renderery a skutečný recorder roundtrip včetně multipart/SHA prošly. Čerstvé opravené monitory jsou v historii kompletní, po nasazení nebylo nové varování o nadlimitních atributech těchto monitorů. Původní řádky měření/modelů/deníku zachovány; pouze existující cache weather_attempts přirozeně obnovila čas posledního dotazu, původní hodnota zůstává v záloze. Nové produkční RAM/outbox/receipt tabulky před skutečnou nocí prázdné. Samostatná nová revize dnešního archivu455/1440 uvádí i předpoklad chybějícího readbacku; přísná historická varianta nepovoluje převzetí. Žádné fyzické povely či EEPROM zápisy, veřejná publikace neprovedena. Tři skutečné noci a hardwarové mapování/timeout zůstávají budoucím ověřením.


## Opakovaný audit0.6.9 · neopravené B01–B03
394 testů znovuOK,3 nové kontrakty selhaly: B01 HTTP frontend nemá SecureContext-only crypto.subtle, B02 odmítnuté budoucí časové razítko přesto posune accepted_solax_reports a blokuje obnovu, B03 jiné pořadí JSON klíčů vyvolá falešnou kolizi části. Jde o nové neopravené nálezy. Runtime zůstal0.6.9/observe_only, žádný restart ani fyzický povel.64 skutečných monitorovacích řádků je kompletních a podlimitem; to neověřuje HTTP browser. Podezření na minutový skluz03:00 se nepotvrdilo díky5s smyčce již od02:55. Podrobná soukromá evidence naRPi v/share/hec-recovery/audit-069-2026-10-29/REPORT.md. Audit runtime verzi nemění a veřejnou publikaci neprovádí.


## 0.6.10 · HTTP, časové reference a JSON části

Opraveny B01–B03: SHA-256 s ověřeným fallbackem i bez crypto.subtle, sémantické porovnání částí nezávislé na pořadí objektových klíčů a reference pouze z přijatých časově platných snímků. Neplatná reference starší verze se odvolá; návrat vyžaduje dva nové platné snímky. Bez fyzického adaptéru a EEPROM zápisů. Viz docs/HTTP_CLOCK_0610.md. Soukromé doklady zůstávají na RPi, veřejná publikace neprovedena.


## Ověřené lokální dokončení 0.6.10 · 29. 10. 2026
B01–B03 opraveny a nasazeny na RPi. Kód304d4c3, záloha fd7e06d5, soukromé důkazy /share/hec-recovery/fix-0610.399 Python testů a tři původní auditní kontrakty prošly; SHA vektory/náhodné délky do2MiB, transport HTTP/HTTPS a renderer prošly. Nasazený JS načtený skutečným HTTP má shodný hash a v Node VM bez crypto.subtle rozbalí oba skutečné velké monitory i původní archiv455/1440. Jde o ověření dat a schopností, nikoli vizuální test skutečným browserem. Runtime0.6.10 started/observe_only, původní0.5.3 zachován, healthok; baseline měření/modely/deník a konfigurace zachované, quick_checkok. Cache weather_attempts smí přirozeně obnovit čas dotazu; původní hodnota zůstává v záloze. Nové kompletní monitorovací řádky recorderu pod14kB, bez nových oversize varování. Archiv zůstává výpočtem0.6.9; žádná nová rekonstrukce ani testovací produkční RAM/outbox data. Fyzické řízenífalse,0povelů/EEPROMzápisů; veřejná publikace neprovedena. Skutečné noční chování a hardwarové mapování/timeout nadále vyžadují budoucí ověření.


## Audit noci 30.10.2026 · runtime0.6.10 beze změny
Potvrzené C01–C04: dvoukrokový REST/template join bez retry vyřazuje normálně aktualizované entity a missing chybně označí unit_mismatch; glob/stat nad SQLite sidecary má TOCTOU FileNotFoundError; přehled ideální alokace nedoplňuje odlišný souhrn RAM regulátoru; starší teplotní monitor překračuje recorder limit a ztrácí atributy. Noční FileNotFoundError i race jsou doložené odděleně; přesný stack noční výjimky není v logu.399 baseline testů OK,3 nové Python kontrakty FAIL, cílený UI a starší teplotní datový kontrakt FAIL. Recorder nového deníku je bezztrátový a shodný seSQLite; nesměšovat se starým teplotním monitorem. Zmrazené zdroje, podrobné soukromé podklady a REPORT.md naRPi v/share/hec-recovery/audit-night-2026-10-30. Žádná oprava/restart/změna automatizací/řízení/purge/publikace; runtime stále0.6.10 observe_only. Přechod na ostré řízení není ověřen. Verze se dokumentačním auditem nemění.


## 0.6.11 · konzistentní sběr a výsledek regulátoru

Rychlý HA snímek obsahuje hodnotu, jednotku, meze, kontext a původní report ze stejného State objektu. Komplexní prognózy mají omezené opakování a explicitní snapshot_race místo ztracené entity. Missing/unavailable se nevydává za chybu jednotky. SQLite kontrola ignoruje pouze neexistující dočasné sidecary; hlavní DB a ostatní I/O chyby zůstávají chybou. Log má bezpečně omezené místo výjimky. Přehled odděluje RAM regulátor, ideální alokaci a aktuální skutečnost; historie připojuje původní výsledek regulátoru bez přepisu dat. Pouze observe_only, žádný akční adaptér ani EEPROM zápisy.

Připravená oprava; nasazení a finální ověření se evidují samostatně. Soukromé podklady zůstávají naRPi.


## Ověřené dokončení 0.6.11 / 0.5.4 · 30. 10. 2026
Lokální RPi shadow0.6.11 started/observe_only; starší observer nově local_energy_coordinator0.5.4 started/observe_only po kompletní nativní migraci dat a nastavení. Původní6696af1a_energy_coordinator0.5.3 zůstává stopped/bootmanual jako rollback, nikoli porucha. Nespouštět oba publishery.408+164 Python testů, původní kontrakty, Node transport/HTTP a reálný recorder prošly.40 živých skalárních dotazů bez ztráty vstupu; noční886/1439 přesně zachováno a nasazený přehled odděluje RAM/ideální/skutečnost. Plné původní soubory i historické DB řádky při migraci ověřeny; živé cache se mohou přirozeně aktualizovat. Starší sběr měl při údržbě přerušení, které se zpětně nevymýšlí. Automatizace, tarif, priority a zařízení beze změny;0 fyzických povelů/EEPROM. Soukromý REPORT a důkazy na RPi ve fix-0611. Skutečná nová celá noc, fyzické mapování/timeout a vizuální browser nadále nejsou ověřené. Veřejná publikace neprovedena.


## Frontend 0.6.11-r1 · stejný den, dva zdroje deníku
Nasazená karta nabízí samostatnou rekonstrukci a původní živou relaci téhož dne. Výběr zdroje izoluje cache, kolidující ID i souhrn; neúplný archiv není živý fallback. Doložen obousměrný přechod přes skutečný recorder a úplná shoda obou zdrojů. Soukromé replay podklady a receipt jsou na RPi v reconstruct-2026-10-30-0611. Rekonstrukce zachovává dostupné původní reporty a u chybějících údajů výslovně uvádí předpoklady; původní evidence se nepřepisuje. Backend0.6.11 ani0.5.4 se nemění a nerestartuje, žádné fyzické povely/EEPROM. Změna je frontendová revize, nikoli další runtime verze. Veřejná publikace neprovedena; vizuální browser nebyl ověřen.


## 0.6.12 · obnova výkonu v mezích původní čerstvosti

Při asynchronním 5s sběru mohl opakovaný čerstvý snímek ponechat desetisekundový
intent bez obnovy. Následující nová sada pak dorazila o milisekundy po expiraci
a vyvolala zbytečné zastavení a novou rampu. Politika volatile-power-shadow-v2
odděluje zvýšení výkonu od držení: dvě nové celé sady jsou nadále podmínkou
převzetí/obnovy a pouze nová celá sada dovoluje zvýšení. Stále platná lease může
být obnovena na stejný či nižší výkon při úplných validních vstupech. Opakovaný snímek se nestává novým reportem ani good frame.

Platnost každého nenulového intentu je minimum z času vydání +10s, původních
deadline všech požadovaných rychlých vstupů, napětí/limitu/SOC baterie, stavu
měniče, obou vlastníků a konce nočního okna. Neprodlužují se reporty ani jejich
povolené stáří. Opakovaná data tedy nemohou výkon udržovat neomezeně. Skutečná
expirace, neplatné vstupy, cizí vlastník, výpadek sběru a mezera rychlé smyčky
nadále zastavují s nutností dvou nových sad. Integrace energie končí na skutečné
deadline; žádná mezera se neúčtuje jako nabíjení.

Vzorek ukládá intent_expires_at, input_valid_until a způsob obnovy. Událost
would_renew je v kartě označená jako podržení výkonu bez zvýšení. Původní živá
evidence a předchozí rekonstrukce zůstávají zachované; nový výpočet má vlastní
archiv a provenienci. Historicky nedoložené heartbeat časy zůstávají výslovným
předpokladem, nikoli změřenou skutečností.

Regrese: test_lease_0612.py pokrývá asynchronní celou noc, restart SQLite,
nezávislou integraci energie, souhrn a bezztrátový outbox; samostatně duplicity,
absolutní stáří, rollback, neplatné vstupy, skutečnou expiraci a výpadek.
Původní testy ukončení po pevných10s bez nových snímků jsou aktualizované
na nezměněnou15s mez čerstvosti zdroje. Privátní opakování původních pěti
selhání i dnešní noci běží jen na RPi. Fyzický adaptér a hardwarový timeout
nejsou touto opravou ověřené; observe_only zůstává zachované.

## Ověřené dokončení0.6.12 · 30.10.2026
Lokální shadow0.6.12 started/observe_only, nový samostatný archiv a karta nasazené.418 kompletních Python testů plus1 cílená regrese a Node renderery/transport/HTTP prošly. Celý historický replay už nemá falešné expirace ani výpadky proudu ve druhé hodině; nezávislá integrace energie/SOC souhlasí. Původní živý deník, předchozí archiv a baselineDB řádky zachované; skutečný recorder a obousměrná volba stejného dne ověřené HTTP načtenou kartou. Pět původních valid-input selhání reprodukovaných beze změny skalárních reportů je opravených. První meziverze byla odmítnuta celým replay a nebyla nasazena; důkazy zachované. Soukromá evidence v/share/hec-recovery/fix-0612. Historicky chybějící hodnoty/reporty zůstávají explicitním předpokladem a přísný replay nepřevezme vlastníka; rekonstrukce není skutečné nabití. Původní observer0.5.4 běží dál, rollback0.5.3 úmyslněstopped. Nativní záloha i zdrojový/DB snapshot zachované.0 fyzických povelů/EEPROM; nová celá živá noc, vizuální browser a hardwarový timeout nejsou tímto ověřené. Veřejná publikace neprovedena.


## Frontend0.6.12-r1 · stabilní čtení a stránkování deníku

Karta při každém HA hlášení nahrazovala celý shadow DOM, obnovovala scroll
podle indexu tabulky a otevření details podle společné CSS třídy. Doplnění
jiné tabulky tak přeneslo offset jinam a rozbalení jedné capacity otevřelo
i ostatní. Zobrazení celé relace současně vytvářelo stovky řádků; dekódovaný
monitor navíc dostával novou objektovou identitu i při nesouvisejícím HA
hlášení. Časovač i výškový ResizeObserver vyvolávaly další zbytečnou práci.

Nově se mění obsah stávajících DOM prvků podle stabilních klíčů. Zaniklé
prvky se odstraňují před vložením nových, aby nová výstraha nepřesouvala
všechny další panely. Zachovávají se jednotlivá details, focus, horizontální
offset, čtený řádek i vnější HA scroll. Při doplnění obsahu nad čteným místem
se kompenzuje pouze skutečná změna jeho polohy. Scroll tabulky se nesmí
kompenzovat o pohyb celé tabulky na stránce.

Deník uchovává všechny načtené události/vzorky, ale současně vykreslí nejvýše
50 událostí. Celý deník je dostupný po stránkách. Nové živé události neposunou
rozečtené okno; zobrazí se po výslovném kliknutí na tlačítko nových událostí.
Uzavřený kompletní stream se znovu nestahuje bez změny očekávaných počtů
nebo výslovného reloadu. Neúplné a aktivní streamy mají původní obnovu dat.

Dekódované State wrappery mají při stejném zdrojovém State stabilní identitu.
Externí změny se slučují do animation frame, stejné fragmenty se nepřekreslují
a formáty Intl se používají opakovaně. ResizeObserver reaguje jen na změnu
šířky; grafy mají vyhrazenou výšku.

Regrese: scripts/test_card_updates.mjs (identita, cache, explicitní reload,
úplnost všech stránek a stabilní živé okno) a test_card_scroll_browser.mjs
(skutečný Chromium, dvě šířky, načtení obsahu, geometrie, wheel, focus,
details a všechny události). Browser test přijímá PUPPETEER_MODULE_PATH,
CHROMIUM_PATH, CARD_SOURCE, CARD_FIXTURE a CARD_BROWSER_RESULT. Skutečná
data se předávají pouze na RPi; výchozí data jsou syntetická. Browser běží
na testovací stránce s vnořeným shadow scroll kontejnerem; není to přihlášený
HA shell. Načítání skutečného HA recorderu se ověřuje samostatně.

Jde pouze o frontendovou revizi. Backend0.6.12 ani observer0.5.4 se nemění
a nerestartují. Archivní manifesty a původní data se nepřepisují. Fyzický
adaptér zůstává vypnutý. Soukromá evidence v recovery adresáři na RPi.

## Ověřené dokončení frontend0.6.12-r1 · 30.10.2026
NasazenýJS/resource naRPi, backend0.6.12/observer0.5.4 bez změny a restartu. Prošel původní Node balík, nové regrese cache/identity/paginace i skutečnýChromium155 na finálnímHTTP artefaktu se skutečnými nočními daty.1280px/390px: zachovanéDOM/details/focus/offsety, při řízené aktualizaci0px posun a funkčníwheel. Všechny události dostupné po50 řádcích, vzorky bezztrátové. Původní verze stejný browser kontrakt nesplnila.100 nesouvisejících HA změn0renderů, relevantní dávka sloučená. Skutečnýrecorder ověřil původní i rekonstruovaný zdroj a přepínání bez smíchání; backend/automatizace hashově zachované, config/archivy/jinéresource shodné. Soukromé důkazy /share/hec-recovery/fix-ui-0612-r1. Browser běžel na testovací stránce se shadow scroll kontejnerem, nikoli přihlášenémHA shellu; nevydávat za ověření každého klienta nebo garantovaných60FPS. Žádné fyzické povely/EEPROM ani veřejná publikace.


## Hloubkový audit0.6.12 / frontend0.6.12-r1 · 30.10.2026 · otevřené nálezy
Audit přesného1494f78 odpovídajícíhoRPi potvrdil D01–D06:
P1 chybné indexové mapování proudů vUI; P1 synchronní monitoring blokuje
rychlou smyčku a uniká její metrice; P1 klouzavé časové okno ztratí potvrzení
při recorder commit zpoždění nad resend intervalem; P2 graf prodlužuje
požadavek za explicitnístop; P2 archiv přijme neplatné indexy/konfliktní
duplicity jako kompletní; P2 návrat hodin přes datum dovolí dalšího vlastníka.
Sedm nových kontraktů tyto chyby reprodukovalo přes dotčené celé cesty.
419+164 původních Python testů a Node regrese prošly; dalších1200 vzorků
ověřilo nezávislou energii, deadline a modelové fáze. UI mapování i graf
potvrdilChromium s RPi daty na testové stránce, nikoli přihlášenémHA shellu.
Reprodukce: scripts/audit_deep_0612.{py,mjs} s ENERGY_AUDIT_OUTPUT.
Soukromý REPORT a důkazy /share/hec-recovery/audit-0612-2026-10-30.
Audit runtime neopravuje ani nemění verzi; provozní zdroje/restarty/zařízení
beze změny. Livehealthok nepopírá chyby za reprodukovaných podmínek.
Žádná veřejná publikace ani fyzické povely/EEPROM.


## 0.6.13 · opravy D01–D06

D01: čtyři proudové údaje karty mají konkrétní pojmenované entity, jednotky
a timestampy. Seznam entit pro sledování změn neurčuje jejich význam.

D02: monitoring běží v samostatném vlákně. Čistá příprava ověřuje allowlist
a byte budget ještě ve fail-closed cestě; nahraditelná fronta drží nejvýše
poslední čekající snapshot každé entity a zachovává férové pořadí. Trvalý
deník má svůj původníSQLite outbox. Jednotlivé chyby monitorů drží degraded
do úspěchu dané entity. HTTP latence/počty/stav mají samostatnou metriku;
rychlá smyčka nevykonává HTTP publikaci ani v chybové větvi. Výpadek sběru
stále okamžitě odvolá uložený intent a prioritně zařadí nulové/unknown monitory.
Nejde o fyzickou real-time záruku; akční adaptér stále chybí.

D03: potvrzení recorderu se hledá od prvního možného přijetí s trvalým
cyklickým kurzorem a omezeným120s dotazem. Prohledávání se vrací ke starším
časům, zahrne pozdější retry a přežije restart i návrat hodin. Resend nemění
první mez. HTTP200 samotné nic nepotvrdí; bez skutečné shody recorderu
zůstává část v trvalé frontě a při dlouhém čekání je transport degraded.

D04: modelový graf zohledňuje explicitní stop i intent_expires_at; nenulový
požadavek nesmí přemostit odvolání nebo konec platnosti. Nejisté mezery se
oddělují. Skutečný měřený proud a trvalý proudový limit mají vlastní série
a virtuálním stopem se nemění.

D05: přesné indexy0..N−1, souhlas metadata a odmítnutí konfliktních duplicit
událostí/vzorků/session/částí. Přesná opakování a jiné pořadíJSON klíčů
zůstávají přípustné. Neúplný či vadný archiv neposkytne controllerSession
a nespadne do živého fallbacku. content_sha256 váže celý kanonický obsah:
{session, events seřazené numericky podleid, samples podle textovéhoat};
rekurzivně seřazené klíče, JSON.stringify, UTF-8, SHA-256. U starých
manifestů bez otisku je zachovaná pouze strukturální kompatibilita; nové
rekonstrukce musí mít otisk. Nasazené archivy je třeba ověřit z recorderu
a doplnit jejich manifestům checksum, bez přepisu původních řádků/provenience.

D06: vlastníka blokuje každá jiná otevřená relace bez ohledu na pořadí dat.
Návrat času pod last_processed_at odvolá výkon, zruší návaznost integrace
a čeká do dohánění původního času. Poté vyžaduje dvě nové platné sady.
Původní model/history se nezpětně nedatují a žádný interval se neintegruje dvakrát.

Regrese: test_deep_fixes_0613.py (skutečná souběžnost, Store, observer,
fronta, zpožděný recorder/restart/pozdní retry/časový návrat) a
scripts/test_deep_fixes_0613.mjs (čtyři různé proudy, grafstop/TTL,
indexy/konflikty/integrita a zamezení částečného modelu). Původní auditní
skripty jsou opakovatelným srovnáním; staré důkazy zůstávají zachované.
Starší test návratu hodin je zesílen na čekání do monotónního času.

Připravená oprava; nasazení a skutečný recorder/browser se ověřují samostatně.
Režim observe_only, žádné změny starých automatizací, priorit či tarifů.
Žádný akční adaptér, fyzický povel nebo EEPROM zápis.

## Ověřené dokončení0.6.13 · 30.10.2026
D01–D06 opravené a nasazené naRPi.429Python testů (10nových backendových),
původních7 auditních kontraktů a NodeUI/transport/HTTP/integrita prošly.
PomaléHTTP testované skutečným souběhem; recorderzpoždění/restart/retry/clock
ověřené izolovanými testy. Živý sběr/publikaceok, monitoringHTTP mimo sběr.
Celá baselineDB a chráněné soubory zachované, nativní záloha9007388f.
Oba skutečnéarchivy mají ověřený kanonický content_sha256 bez přepisu řádků,
archiveID nebo provenience; původní i rekonstruovaný deník se přepínají přes
skutečnýrecorder bezmixu. FinálníHTTP artefakt a Chromium s RPi daty ověřily
správnéproudy, přesnýstop a zachováníscroll/focus ve dvoušířkách.
Browsernení přihlášenýHA shell, další celáživá noc není ověřená. Rekonstrukce
zůstává podmíněnou0.6.12, runtime0.6.13; software_version nefalšovat.
Legacy0.5.4 běží, rollback0.5.3 úmyslněstopped.0 fyzickýchpovelů/EEPROM,
žádná veřejnápublikace. Soukromé důkazy /share/hec-recovery/fix-0613.


## Nezávislé ověření0.6.13 · 30.10.2026 · nové otevřené nálezy
Audit přesného b99ccd5 potvrzuje A13-01 až A13-05(P2) a A13-06(P3).
Ideální model při návratu hodin započte překryv a duplicitní krok zvýší počet
vzorků; chyba se dostane do souhrnu. record_failure ztratí krátký platný úsek
energie před explicitním stopem. Otevřený starý vlastník nemá dokončovací cestu
nového observeru. Chybějící stav nezměněného parametru falešně potvrdí přesné
předání. Browser drží geometrii, ale stránkování má zbývající synchronní blokování.
Starý otevřený řádek mimo14položek po importu/recovery se neobnoví a dál blokuje.
Viz docs/AUDIT_0613_20261030.md a scripts/audit_independent_0613.py.
429+164Python testů, původních7kontraktů a Node regrese procházejí; toto není
potvrzení absence dalších chyb. Skutečný recorder ověřuje oba manifestovéSHA,
odtřídění zdrojů a původní data; soukromé důkazy v recovery audit-0613-2026-10-30.
Audit provoz neopravuje, nemění verzi ani zařízení. Žádný restart/nasazení,
veřejnýpush nebo fyzické povely. Nová celáživá noc a přihlášenýHA shell nejsou
ověřené. Staré audity/důkazy zůstávají zachované; opravy musí mít vlastní revizi.


## 0.6.14 · implementace oprav A13-01–A13-06
Ideální model má watermark/idempotenci a po rollbacku přeruší návaznost;
nejisté intervaly nedopočítává. Failure stop účtuje krátkou původní platnost
před vymazáním previous. Legacy vlastník dostane pouze dokončení předání,
ne staré nové nabíjení; původní verze/evidence zůstává. Chybějící skutečný
stav blokuje přesné předání i u nezměněných parametrů. Obnova všech otevřených
relací nemá prezentační limit14. Karta má oddělený seznam po20událostech,
lazy úplné podklady a zdrojové klíče; stránkování nepočítá graf/celou kartu.
Viz docs/INDEPENDENT_FIXES_0614.md a nové backend/UI/browser regrese.
Připravená implementace; nasazení/finální počty testů a reálná evidence se
ověřují samostatně. Původní archivy/automatizace/provenience se nepřepisují.
Žádný akční adaptér nebo EEPROM. Veřejnýpush nebyl proveden.


## Ověřené dokončení0.6.14 · 30.10.2026
A13-01–A13-06 opravené a nasazené naRPi; source4110800, pouze lokální větev.
439shadow+164legacyPython testů, Node a původních5+7protipříkladů prošlo.
FinálníHTTP karta a Chromium s čerstvými monitory/celou nocí ověřily30stránek
po20událostech, všechny1440vzorky, scroll0px/wheel300px, focus/details,
0plných renderů při navigaci a max.79.4msvčetnělayoutu při limitu100ms.
Skutečnýrecorder potvrdil původní i rekonstruovaná data a obousměrnou volbu
bezmixu; obaSHA/provenience/archivnímanifesty zachované. Rekonstrukce zůstává
podmíněnou0.6.12, runtime0.6.14. Healthok, sourcehashes shodné, původní deník
achráněnésoubory zachované; živécache mohou přirozeněaktualizovat. Zálohaea15f2df.
Legacy0.5.4 běží; rollback0.5.3 úmyslněstopped. Dashboard konfiguracebezezměny,
jen novýJS/resourceURL.0fyzickýchpovelů/EEPROM, automatizace/tarif/prioritybezezměny.
Browsernení přihlášenýHA shell; nováceláživánoc/hardwarovýtimeoutnejsouověřené.
Žádný veřejnýpush/CI/merge. SoukromýREPORT a důkazy /share/hec-recovery/fix-0614.


## 0.6.15 · noc31.10.2026
Pevná dolní mez P/UI0.5 odmítala34dostupných měření. Pro nízký poměr nyní
platí původní konzervativní trojúhelníková proudová mez, nikoli domyšlený
účiník nebo chybějící proud. Horní kontrola P/UI1.05 a čerstvost zůstávají.
Modelový proud zahrnuje proudový offset i v RAM deníku. Základ nad rozpočtem
zablokuje alokaci. Není to fyzicky certifikovaná ochrana jističe.

Síťový sběr běží v samostatném workeru každých2.5s (proti aliasingu s5sHAreporty). Řídicí smyčka čte kopii
snímku s původními HA reporty; nevytváří nový heartbeat. Starší než7.5s nebo
explicitně selhaný snímek je odmítnut, platí stop a původní dvousnímková obnova.
Pouze při studeném startu čeká na první snímek nejvýše1s. Pomalý HTTP dotaz
neblokuje další řídicí kroky. Snapshot/HTTP/DB timing jsou oddělené metriky.
Přesná historická příčina obou nočních mezer není ze starých metrik doložená;
oprava odstraňuje blokující síťovou cestu a doplňuje diagnostiku ostatních příčin.

Původní noc a její31stopů se nepřepisují ani nevyplňují. Nezávislá původní
integrace souhlasí. Všech34původních odmítnutých allocator snímků nyní projde
bez nahrazení timestampů a s modelovou proudovou mezí≤25A. Nejde o novou
celou fyzickou nebo přehrávanou regulátorovou noc. Regrese test_night_fixes_0615.py
ověřují nízké/ nulovéP, horní rozpor, celýRAM/outbox průchod a zablokovaný HTTP
worker, stárnutí cache a selhání. Frontend0.6.14 a původní automatizace zůstávají.
Pouze observe_only, žádný akční adaptér, EEPROM, fyzickýpovel nebo veřejnýpush.

Řídicí DB spojení má busy_timeout250ms místo10s, včetně chybové větve. Pokud stop nelze zapsat, pamatuje se původní čas chyby a po zotavení se nejprve dokončí stop a dvousnímková obnova. Nezapsaný čas je i v priority-live.json pro restart. Rozlišené HTTP/cache/DB metriky umožní další mezery přiřadit ke konkrétní cestě; starý recorder nemá úplné rozlišení příčin. Nová regrese simuluje zamčenou SQLite i celémain zotavení bez zpětného prodlužování energie.


## Ověřené dokončení0.6.15 · 31.10.2026
Zdroj7afc43c nasazen naRPi, záloha10d838d7.447shadow+164legacyPython testů,
Node a opětovné5+7auditní reprodukce prošly.34původních low-P/UI snímků nyní
projde konzervativním proudovým modelem≤25A bez změny reportů. Worker2.5s
odstraňuje síť z řídicí smyčky a aliasing se5sHAcohortami, cachemax7.5s.
DBbusy250ms, nezapsaná chyba má původní čas/obnovu i po restartu. Nové8regrese
včetně celého main a skutečného SQLite locku prošly. Živýhealthok, hashe/evidence/
automatizace zachované. Frontend0.6.14 byteověstejný; browserneopakovaný.
Starý recorder neprokazuje přesný původ obou mezer; nově jsou oddělené metriky.
Původní noc31.10.(0.6.14,480/1435,31stopů) nepřepisována; nová celá noc0.6.15
zatímneověřená. Observe_only,0povelů/EEPROM. Žádný veřejnýpush/CI/merge.
Soukromé důkazy /share/hec-recovery/fix-0615 a původní update-2026-10-31.


## Úplná dohledatelná historie na GitHubu · 31. 10. 2026
Uživatel výslovně požaduje a autorizuje zveřejnění vývojové historie včetně slepých cest. Doplněn docs/history/DEVELOPMENT_HISTORY.md, původní commity a manifest všech nalezených přímých recovery REPORT souborů. Nezveřejňují se databáze, tajemství ani surové provozní řady; hashe nejsou jejich off-site záloha. Neuložené historické pokusy nelze zpětně zaručit. Publikaci/CI/merge ověřit odděleně; tato dokumentační změna nemění runtime.

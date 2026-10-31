# Stínový řídicí deník · 0.6.7

## Rozsah

Nový samostatný deník simuluje převzetí → změny limitu baterie → ukončení a předání. Nemá akční adaptér, nevolá HA služby a nemění automatizace, příznaky ani měnič. Výstupem jsou virtuální události a monitorovací entita `sensor.nocni_stinovy_ridici_denik`. Původní výkonový deník a historie zůstávají zachovány.

## Převzetí v 03:00 Europe/Prague

Po získání použitelných vstupů uloží první neměnný snapshot. Seznam MANAGED je explicitní: dvě varianty zapnutí EV priority, její vypnutí, start/stop levného nabíjení baterie, příznak EV priority, režim měniče, ruční volba a nabíjecí limit baterie. Původně vypnutá automatizace se virtuálně nezapíná. Převzetí existujícího Force Charge/Discharge neznámého vlastníka je zablokováno.

Virtuálně pozastaví pouze vyjmenované souběžné automatiky, ponechá příznak EV priority po dobu relace a navrhne nabíjecí limit ještě před Manual Mode / Force Charge. Neznámá data jsou blokování, nikoli nula. Při nulovém požadavku po převzetí zůstává virtuální baterie v Manual Mode / Stop Charge and Discharge, aby se nesimuloval souběžný odběr z baterie do auta. Pozdní start je přiznaný; předchozí průběh se nedoplňuje.

Seznam odpovídá ručně zkontrolované konfiguraci (hash v automation_context). Tato verze automaticky neověřuje změny definic YAML za běhu: `config_live_validation=false`, `live_ready=false`. To je omezení před budoucím ostrým řízením.

## Ampéry a měření

Převod P_AC × předpokládaná účinnost / napětí baterie dává A DC. Limit se ořízne podle zařízení a DC rozpočtu a zaokrouhlí dolů na krok skutečného registru. Následně se zkontroluje přepočtený fázový model do25A. Podporován je registr s minimem0A, protože virtuální zastavení používá nulový limit a samostatné Stop Charge and Discharge. Dostupný výkon i účinnost jsou modelové vstupy; převodní účinnost a reakční rezerva nejsou fyzicky ověřené.

Pokud by výpočet vyžadoval významné omezení EV, deník to označí jako `requires_ev_control_not_implemented` a nenavrhuje nabíjení baterie. Nesmí předstírat existenci ověřeného akčního řízení auta.

Vzorky ukládají skutečně hlášený limit, měřený proud a virtuální limit baterie v A DC. Události vznikají při změně nastavení, ne při opakovaném stejném vzorku. Statistiky uvádějí zvýšení/snížení, stop/blokování, min/max, časové pokrytí, maxima proudů a počet vzorků nad25A. Nejsou jističovou ochranou ani důkazem chování mezi vzorky.

## Ruční změny a výpadky

Cizí změna skutečně pozorovaného nastavení se zaznamená se známým uživatelským kontextem nebo s neznámým původem. Při konfliktu režimu či proudu se virtuální řízení pozastaví a cizí hodnota se při obnově nepřepíše. Uživatelský kontext není úplný detektor všech ručních zásahů.

Změny EV příznaku bez uživatelského kontextu se ve stínovém režimu evidují jako pozorování: původní automatiky stále skutečně běží. Nejde o ověření budoucího výhradního vlastníka. Dopady nového vypnutí automatik na teplo se fyzicky nesimulují; rozpočet vychází z měřeného domu.

Výpadek zdroje zaznamená virtuální stop, zneplatní pokračování časové integrace a počká na obnovu. Restart načte uloženou relaci. Konec okna po výpadku se zpracuje skutečným časem obnovy se samostatným plánovaným časem05:00; události se zpětně nedatují.

## Předání v 05:00

Nejprve virtuálně ukončí vlastní Force Charge, potom obnoví převzaté parametry a nakonec automatiky podle snapshotu. Obnova nezapne původně vypnuté automatiky. Konflikty zůstávají vyznačené.

Chybějící stav znamená `restore_pending`; zdravý další cyklus obnovu zkusí dokončit. Dokud zůstává předchozí vlastník nedokončený, nezačne nová virtuální relace. Opakování nevytváří zbytečné změny již obnoveného proudu.

Pokud auto stále odebírá alespoň50W nebo jeho skutečná priorita dosud zůstává aktivní, příznak EV priority se předá původním pravidlům a virtuálně se bezpodmínečně nevypne. Výsledek je `conditional_handoff`, nikoli tvrzení o přesném návratu všech hodnot. Bez známého stavu auta je návrat nedokončený.

## Uložení a karta

`control_sessions` drží snapshot a poslední stav; `control_events` je přidávaný deník, `control_samples` přidávané vzorky. Staré tabulky se nepřepisují. Nová monitorovací entita obsahuje posledních24událostí a2vzorky, přehled relací a přípravu dalšího okna. Celý původní deník je v SQLite.

Karta doplňuje chronologii a graf A DC z historie této monitorovací entity v HA; načítá změny přírůstkově s `significant_changes_only=0` a plnými atributy (bez `minimal_response`), deduplikuje ID a uvádí načtený počet vůči počtu událostí. Vyžaduje záznam nové entity v recorderu; chybějící historii hlásí. Nevyžaduje nové hostitelské porty ani veřejné API.

Ověření zahrnuje celou syntetickou dvouhodinovou relaci, restarty, chyby zdroje, ruční změny, pozdní obnovu, opakované zpracování a GET-only historii karty. Syntetický úplný návrat není důkazem fyzického obnovení zařízení.


## 0.6.7-r1 · zobrazení výslovných zpětných rekonstrukcí

Karta umí přes `control_archives` načíst samostatný archiv událostí a vzorků z monitoru `sensor.nocni_stinovy_denik_rekonstrukce`. Běžný deník a jeho SQLite se nepřepisují. Rekonstrukce se ukládá do recorderu v čase jejího doplnění; historické časy jsou uvnitř výslovně označených událostí. Karta uvádí původ, předpoklady a kontroluje počet částí, událostí i vzorků. Živá relace má vždy vlastní cestu načítání.

Soukromý výpočet používá neměněnou logiku `control_journal` 0.6.7 v oddělené SQLite. Recorder nemusí uchovat heartbeat ani min/max/step/options. Držení hodnot a doplnění metadat z pozdějšího snímku musí být přiznané; nesmějí se vydávat za původní živé pozorování. Výkonový scénář s cílem100% nepotvrzuje existenci tehdejšího platného SOC plánu.

Metadata v konfiguraci karty obsahují `day`, `archive_id`, `recorded_from`, `recorded_to`, `event_count`, `sample_count`, `chunk_count`. Načítání používá autentizovanou HA historii, plné atributy a `significant_changes_only=0`; provozní soukromá data nejsou veřejným souborem v `/local`. Recorder může archiv po době uchování smazat; karta pak hlásí neúplnost, úplný soukromý SQLite archiv na RPi zůstává.

Jde o revizi frontendové karty, runtime doplňku zůstává0.6.7. Žádný restart, akční adaptér ani veřejná publikace nejsou součástí. Node regrese ověřují označení, escapování, deduplikaci, úplnost a oddělení od živé relace.


## 0.6.7-r2 · provozní stav a důvod neplatného vzorku

Karta důsledně odděluje provozní stav `sensor.solax_run_mode` od nastavované strategie `select.solax_charger_use_mode` a ručního povelu. Normal Mode se nevkládá místo Back Up Mode; jde o různé registry. Události uvádějí přesné entity a lidské označení nastavovaného parametru.

Obecné invalid_charge_inputs znamená neplatné nebo neúplné vstupy, nikoli automaticky výpadek. Zpětná auditní revize může doplnit konkrétní diagnostiku rozporného P/U/I, původní důvod zachovává v original_reason. Hodnoty |P|/(U×I) mimo přijaté meze zůstávají odmítnuté. Časy rozporu v recorderu a krok15s rekonstrukce nejsou fyzická délka poruchy ani důkaz skutečného zastavení měniče.

Nová revize archivu má nové archive_id a výslovný odkaz na předchozí revizi; původní evidence se nepřepisuje ani nemaže. Backend zůstává0.6.7 a jeho rozhodovací logika je nezměněná. Ověření:27testů control_journal včetně průchodu konzistentní→rozporné→konzistentní vstupy, plus Node renderer s přesnými identifikátory a odlišením stav/strategie/chybějící/rozporná data.

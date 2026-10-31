# Opravy nízkého P/UI a neblokující sběr


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

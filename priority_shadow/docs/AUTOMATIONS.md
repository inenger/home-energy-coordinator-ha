# Aktuální doplnění0.6.7

Stínový deník nyní **virtuálně** eviduje převzetí a předání konkrétního seznamu automatizací a registrů. Žádné skutečné automatiky ani zařízení se nemění. Přesná implementace a její meze: [CONTROL_JOURNAL_067.md](CONTROL_JOURNAL_067.md). Následující text popisuje původní audit a budoucí fyzickou koordinaci.

# Co se děje s automatizacemi mezi 03:00 a 05:00

**V aktuální 0.6.2 se nevypíná ani neupravuje žádná provozní automatizace.**
Shadow čte jejich stav a zobrazuje vysvětlení. Preference na kartě mění
pouze stínový helper. Následující návrh koordinace je příprava budoucího
řízení, nikoli aktivní chování.

Popisy vycházejí z konfigurace zkontrolované 23. 10. 2026 v
`energy/automation_context.py`; hash tehdejší konfigurace je
`1f39eac7dd4662f91bb9c414db438f52e325a22258f0b2d6bade4c17e06a1dbc`.
Živé on/off stavy se načítají zvlášť. Statický popis po změně HA konfigurace
nemusí být aktuální; před úpravami je nutné znovu načíst skutečné definice.

| Skupina | Současné chování podle auditu | Budoucí koordinace 03–05 |
|---|---|---|
| Zapnutí EV priority, dvě varianty | Nad 300 W po minutě aktivuje prioritu, vypne patronu a čerpadlo, nastaví TČ MEDIUM a křivku 0 | Sjednotit vlastníka zásahů; zohlednit účinky i mimo noční okno |
| Vypnutí EV priority | Pod 50 W po 5 minutách vypne příznak; předchozí spotřebiče neobnoví | Konec nabíjení EV nesmí předčasně uvolnit výkon potřebný pro baterii |
| Levné nabíjení baterie: start | Povolení, SOC pod 50 %, FVE pod 15 kWh, bez EV priority; okna 03–05, 11–12, 13–14; Force Charge | Noční část nahradit platným scénářovým cílem a sdíleným rozpočtem; denní část posoudit zvlášť |
| Levné nabíjení baterie: stop | Mimo okna, při EV prioritě, odvolání povolení, FVE ≥20 kWh nebo SOC ≥97 % přepíná režim | Start i ukončení musí mít stejného vlastníka, aby staré pravidlo nepřepsalo nový cíl |
| Zvyšování ohřevu | Patrona od 09:00, křivka 07–20, TČ LARGE od sunrise +1 h; podmínka bez EV priority | Započítat běžící odběry a zabránit novému souběhu, nikoli plošně vypnout všechny automatiky |
| Čerpadlo bojleru | Start podle LARGE nebo patrony >100 W, bez EV podmínky; vlastní stop pravidla | Posoudit opětovný start a vazbu na odvod tepla |
| Návrat ohřevu do základu | Vypínání patrony, MEDIUM, křivka 0 dle výroby/SOC | Zachovat omezující funkce |
| Starší řízení měniče | Při auditu vypnuté; další časové/spotové přepínání | Nezapínat; ověřit jediného vlastníka měniče |
| Přetoky dle ceny | Samostatné povolení/zákaz exportu | Zachovat oddělené; limit zahrnout do hodnocení výroby |

Přesné entity každé skupiny jsou v `automation_context.GROUPS`, příznaky
v `FLAGS`; karta je uvádí z `automation_context` výstupu živého plánu.
Starý text `planned` u levného startu stále zmiňuje tabulku 90/80/70/30.
Jde o historický popis návrhu; aktuální SOC výběr je scénářový podle
[ALGORITHM.md](ALGORITHM.md), tabulka slouží jako reference.

## Podmínky budoucího ostrého řízení

Před implementací je nutné potvrdit provozní rezervu, proudová měření/fáze,
limity a bezpečný přechod měniče, odjezdy EV a reakce ohřevu. Návrh musí
evidovat, které stavy skutečně převzal, a jejich původní hodnoty. V 05:00
ukončí vlastní zásahy a vrátí pouze převzaté stavy podle aktuálních podmínek;
nesmí hromadně zapnout všechny automatizace nebo obnovit ohřev bez kontroly.

To je otevřená implementační práce, nikoli vlastnost současného modelu.
Model předpokládá držení baterie v levném okně a budoucí dům dle profilu;
novou odezvu tepelných automatizací po zásahu dosud nesimuluje.

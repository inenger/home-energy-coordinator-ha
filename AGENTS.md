# Trvalá pravidla projektu

1. Před úpravou přečti `MEMORY.md`, příslušné README a vnořený AGENTS.md.
2. Rozliš `energy_coordinator` (původní doplněk) a `priority_shadow` (samostatný pozorovací doplněk). Na publikační větvi má každý vlastní zdroje a Docker context; nesynchronizuj je slepě.
3. Uživatelské pokyny mají přednost. Provoz, soukromá data a simulace se skutečnými daty patří na RPi. `tds-dev` není cílový stroj tohoto projektu.
4. Bez výslovného zadání nepřidávej akční adaptér, neměň původní automatizace, tarif, rezervy ani priority. `observe_only` je provozní kontrakt.
5. Do veřejného Gitu patří kód, syntetické testy a obecné poznatky. Nikdy databáze, seed, tokeny, soukromé časové řady či plné provozní logy.
6. Každou nalezenou chybu převést na reprodukovatelný regresní případ přes celou dotčenou cestu. Výsledek pomocné funkce sám nepotvrzuje návaznosti runtime/replay/review/UI.
7. Na konci aktualizuj aktuální stav a poučení v `MEMORY.md`, verzi a changelog. Uveď provedená ověření a jejich meze.
8. Rozliš lokální commit, ověřenou GitHub větev, CI a nasazení na RPi. Nikdy nevydávej jednu z těchto věcí za ostatní. Před změnou main zvaž automatické aktualizace HA a rozsah uživatelova zadání.
9. Při opětovném auditu nepřepisuj starý nález ani jeho důkazy; přidej novou verzi výsledku a test pro nově objevený protipříklad.
10. Záměrně zastavenou službu ani ukončení SIGTERM/143 samo o sobě neoznačuj za novou poruchu; nejprve ověř požadovaný režim a nový důkaz chyby.

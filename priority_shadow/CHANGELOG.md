# 0.6.21 · oprava falešné blokace ručním podrežimem

Uložená Force Charge/Force Discharge při čerstvém známém Back Up Mode, Self Use Mode nebo Feedin Priority neblokuje stínové převzetí. Aktivní ruční nabíjení/vybíjení v Manual Mode, neznámé režimy, cizí vlastník a zastaralé vstupy dál blokují. Reporty pracovní strategie a podrežimu omezují platnost intentu. Pouze observe_only.

[Chování, regrese a meze](docs/MANUAL_MODE_FIX_0621.md).

# 0.6.20 · regulace oddělená od ukládání evidence

Řídicí smyčka používá soukromý stav v paměti. Diskové zápisy a analytika mají vlastní proces; příprava a HTTP monitorů další proces. Omezená fronta hlásí zpoždění a případnou ztrátu evidence, aniž by resetovala platný řídicí návrh. Skutečné vstupní a bezpečnostní poruchy nadále zastavují. Pouze observe_only.

[Architektura, syntetické regrese a historie pokusů](docs/CONTROL_ISOLATION_0620.md).

[Úplný předchozí changelog ve verzované historii](https://github.com/inenger/home-energy-coordinator-ha/blob/af73cb3c1df6827e9843677a9ce2161cccde07ba/priority_shadow/CHANGELOG.md). Předchozí historie zůstává zachovaná; do této změny nejsou znovu vkládány provozní dokumenty ani rozsáhlé logy.

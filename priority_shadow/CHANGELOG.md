# 0.6.20 · regulace oddělená od ukládání evidence

Řídicí smyčka používá soukromý stav v paměti. Diskové zápisy a analytika mají vlastní proces; příprava a HTTP monitorů další proces. Omezená fronta hlásí zpoždění a případnou ztrátu evidence, aniž by resetovala platný řídicí návrh. Skutečné vstupní a bezpečnostní poruchy nadále zastavují. Pouze observe_only.

[Architektura, syntetické regrese a historie pokusů](docs/CONTROL_ISOLATION_0620.md).

[Úplný předchozí changelog ve verzované historii](https://github.com/inenger/home-energy-coordinator-ha/blob/af73cb3c1df6827e9843677a9ce2161cccde07ba/priority_shadow/CHANGELOG.md). Předchozí historie zůstává zachovaná; do této změny nejsou znovu vkládány provozní dokumenty ani rozsáhlé logy.

# 0.6.25 · deník bez duplicit a komprese mimo writer

Velký živý náhled deníku používá existující úplný multipart stream; session a transport zůstávají v monitoru, vynechaný náhled je výslovně označen. Chybový plán neopakuje celý deník. Příprava transportu běží mimo writer gate, atomický commit kontroluje původní kurzory. Diagnostika rozlišuje držitele lokálního zámku a nativní SQLite chybu bez SQL parametrů. Pouze observe_only.

[Regrese, neúspěšné pokusy a meze](docs/JOURNAL_SQLITE_0625.md).

# 0.6.24 · záloha za běhu bez zastavení regulátoru

Nativní hot záloha s ověřeným SQLite snímkem a kontrolovanou obnovou před workery. Běžný restart nesmí vrátit novější živou DB ke starému snímku. Zachovaná cesta pro zálohu již zastaveného doplňku. Pouze observe_only.

[Kontrakt, regrese, odmítnuté varianty a meze](docs/HOT_BACKUP_0624.md).

# 0.6.23 · rozběh EV, odolná analytika a obnova monitorů

Plně proveditelný naměřený rozběh EV se zachová i pod 6 A. Přetečení jedné entity má úplný soukromý archiv a pravdivý malý doklad; ostatní monitory pokračují. Analytika má trvalou FIFO frontu s retry mimo potvrzování řídicí evidence. Dohled rozlišuje odpovídající HTTP výpadek od zamrzlého publisheru, používá tři obnovy za 300 s a omezuje opuštěná IPC vlákna. Pouze observe_only.

[Opravy, regresní případy, slepé cesty a meze](docs/NIGHT_FIXES_0623.md).

# 0.6.22 · nezávislá obnova a dohled pomocných procesů

Po převzetí chyby regulátorem v RAM se čerstvá cache obnoví nezávisle na trvalém potvrzení deníku. Produkční sběr nikdy nezapisuje chybu na disk ve vstupním vlákně. Pozdější ztráta evidence nepřepisuje uzavřenou relaci; má samostatný trvalý doklad. Pomocné procesy mají heartbeat a nejvýše tři automatické obnovy za běh; nepotvrzené dávky se idempotentně opakují. Zaseknutá publikace se hlásí jako degraded. Pouze observe_only.

[Opravy, reprodukce, slepé cesty a meze](docs/RECOVERY_FIXES_0622.md).

# 0.6.21 · oprava falešné blokace ručním podrežimem

Uložená Force Charge/Force Discharge při čerstvém známém Back Up Mode, Self Use Mode nebo Feedin Priority neblokuje stínové převzetí. Aktivní ruční nabíjení/vybíjení v Manual Mode, neznámé režimy, cizí vlastník a zastaralé vstupy dál blokují. Reporty pracovní strategie a podrežimu omezují platnost intentu. Pouze observe_only.

[Chování, regrese a meze](docs/MANUAL_MODE_FIX_0621.md).

# 0.6.20 · regulace oddělená od ukládání evidence

Řídicí smyčka používá soukromý stav v paměti. Diskové zápisy a analytika mají vlastní proces; příprava a HTTP monitorů další proces. Omezená fronta hlásí zpoždění a případnou ztrátu evidence, aniž by resetovala platný řídicí návrh. Skutečné vstupní a bezpečnostní poruchy nadále zastavují. Pouze observe_only.

[Architektura, syntetické regrese a historie pokusů](docs/CONTROL_ISOLATION_0620.md).

[Úplný předchozí changelog ve verzované historii](https://github.com/inenger/home-energy-coordinator-ha/blob/af73cb3c1df6827e9843677a9ce2161cccde07ba/priority_shadow/CHANGELOG.md). Předchozí historie zůstává zachovaná; do této změny nejsou znovu vkládány provozní dokumenty ani rozsáhlé logy.

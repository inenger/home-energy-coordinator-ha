# 0.6.24: záloha bez zastavení hlavní smyčky

## Problém a rozsah opravy
Audit N06-01 prokázal, že Supervisor při `backup: cold` zastaví celý doplněk.
Obnova pomocných procesů z 0.6.23 to nemůže vyřešit. Původní reprodukce
`scripts/audit_cold_backup_0623.py` zůstává historickým důkazem; její kladný
výstup znamenal reprodukci vady, nikoli připravenost.

Nový balíček používá `backup: hot`, `backup_pre` a `backup_post`.
Pre-hook je samostatný proces s nižší CPU prioritou. Nedává pokyn k zastavení
regulátoru, nemění vstupní TTL a nebere lokální aplikační writer gate.
Přes SQLite online backup vytvoří stránkovaný snímek potvrzené evidence,
zkontroluje integritu i cizí klíče a uloží neměnný ZIP_STORED balíček s
manifestem, časem dokončení snímku, velikostí a SHA-256. Balíček se zveřejní
atomickým rename a fsync. Nedostatek prostoru, chyba DB nebo překročení
časového rozpočtu kopie znamená chybu přípravy, nikoli úspěšnou prázdnou zálohu.

## Obnova a restart
V živé instalaci je navíc soukromý sentinel, který je z nativní zálohy
výslovně vyloučený. Normální restart, včetně restartu během přípravy zálohy,
proto nesmí obnovit starý snímek přes novější živou databázi.

Nativně obnovený archiv sentinel nemá. Před spuštěním jakéhokoliv workeru
se ověří členové ZIP, formát manifestu, velikost, SHA-256 a SQLite.
Teprve potom se obnoví ověřený snímek. Původní obnovené SQLite soubory a
sidecary se uchovají v soukromém `native-restore-original/<generation>`.
Přerušená obnova se opakuje z téhož balíčku; poškozený snímek nepřepíše DB.
Obnova neobnovuje platnost starého virtuálního povelu: standardní startup
stále vyžaduje nové platné vstupní sady a přiznává přerušení relace.

Živé SQLite soubory zůstávají v nativním archivu jako záložní cesta pro
zálohování již zastaveného doplňku. Supervisor tehdy pre-hook nespouští.
Při hot záloze jsou tyto soubory při obnově nahrazené ověřeným snímkem;
nekonzistentní samostatná kopie WAL není autoritativní zdroj.
Post-hook po dokončení archivu odstraní pracovní balíček, nejdřív ZIP
a potom sentinel. Úspěšná obnova také uklidí balíček před spuštěním workerů.

## Regrese a odmítnuté zkratky
`tests/test_native_backup_0624.py` ověřuje produkční run_loop, trvalé dávky,
frontu analytiky, outbox, nativní strukturu taru, obnovu a nový seed:
- blokovaný přípravný proces nezastaví hlavní smyčku;
- online snímek je konzistentní při souběžném WAL writeru;
- všechny potvrzené řádky snímku se po obnově shodují;
- živý restart nevrátí novější DB do minulosti;
- zastavený doplněk má cestu přes statickou SQLite;
- poškozený obsah a přerušení obnovy nesmažou původní data;
- chybějící zdroj a překročený rozpočet přípravy nejsou úspěch.

Pouhé cold→hot bez konzistentního snímku bylo odmítnuto. Vyloučení všech
živých SQLite souborů bylo odmítnuto kvůli zastavenému doplňku. Obnova ZIP
při každém startu byla odmítnuta kvůli ztrátě novějších zápisů. Kontextový
manager sqlite3 sám spojení nezavírá; nová kopírovací cesta používá
explicitní closing. První testovací běh prošel, ale dva testovací connecty
měly ResourceWarning; byly opravené bez oslabení testů.
Docker image nyní obsahuje i config.yaml, aby konfiguraci kontrolovaly také
povinné testy při skutečném nativním sestavení.

## Meze
Snímek obsahuje potvrzenou SQLite evidenci v čase uvedeném v manifestu,
nikoli dosud nepotvrzené RAM dávky či pozdější změny. Rozpracovaný nebo
opuštěný balíček po násilném přerušení zálohy může reprezentovat starší
výslovně uvedený čas; netvrdit nulové RPO. Původní soubory jsou zachované.
Stejně jako ostatní hot zálohy nemůže tato funkce garantovat nulovou latenci
při přetížení společného CPU/disku nebo výpadku celého RPi.
Testy obnovy běží do izolovaného adresáře; neprovádějí destruktivní obnovu
živého HA. Režim zůstává observe_only, bez fyzického adaptéru. Samostatný
nález zpoždění vstupů N06-02 touto opravou nemá prokázanou příčinu ani opravu.

Zdroj kontraktu Supervisor:
https://contributors.home-assistant.io/apps/reference/configuration/#backups
a supervisor/apps/app.py (begin_backup, _backup_command, backup,
_is_excluded_by_filter). Selhání pre-hooku ukončí zálohu aplikace před tarováním.

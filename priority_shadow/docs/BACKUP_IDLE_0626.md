# 0.6.26 · stabilní archiv a čtení bez no-op writerů

BACKUP-02 ([issue31](https://github.com/inenger/home-energy-coordinator-ha/issues/31)):
SQLite odstraní WAL/SHM při uzavření posledního spojení. Online SQL snímek
může být správný, ale nativní tar otevře mezitím zmizelé raw sidecary a selže.
Samotný výsledek API, velikost taru ani zachráněný SQLbundle neprokazují
platnou nativní obnovu doplňku. Je nutná kontrola addon metadata/komponenty,
manifestu a oddělené obnovy.

Pre-hook nově spustí samostatný časově omezený holder. Jeho SQLite spojení
přečte schéma a nezanechá transakci; neblokuje BEGIN IMMEDIATE ani zápisy.
Žije nezávisle na evidenčním workeru i rodiči pre-hooku a chrání životnost
WAL/SHM po dobu taru. Post-hook ukončí lease a čeká na uzavření. Žádné
signálování PID ani změny řídicího procesu. Flock dovolí pouze jednoho
holdera, připravenost má 10s mez a samotná lease nejvýše 30 minut. Výpadek
nebo expirace před finish se hlásí jako chyba, nikoli falešný úspěch.

Pomocné lease/ready/lock soubory pokrývá původní .native-backup-* exclusion.
Navíc se nearchivují rozpracované evidence/*.tmp a monitor-overflow/pending-*.
Dokončené soubory i raw hlavní DB/WAL/SHM zůstávají zahrnuté. Již zastavený
doplněk nemusí pre-hook spouštět: test zachovává také potvrzené transakce v
WAL po os._exit bez checkpointu. Raw fallback nelze rozbít plošným vynecháním
WAL. Autoritativní hot snímek je nadále ověřený online SQLbundle, nikoli
časově proměnlivé raw soubory.

DB-03: Store při každém otevření znovu získával writer gate pro PRAGMA/DDL;
i idle journal recorder a prázdná analytika tak vstupovaly mezi zapisovatele.
Nové spojení nastaví connection-local synchronous=FULL, přečte journal mode
a existenci potřebných objektů. Hotové schéma neprovádí znovu CREATE.
Transport a FIFO mají stejnou read-only kontrolu tabulek. Chybějící indexy,
studeno/legacy DB a skutečné zápisy nadále procházejí omezeným writer gate.
Neprázdná analytika před výpočtem ustoupí již obsazenému writeru; FIFO a
původní časy zůstávají. Cizí SQLite writer nebo I/O se neignorují. DB-01 není
uzavřený pro každý historický timeout; N06-02 také zůstává otevřený.

## Reprodukce, regrese a chyby pokusů

Veřejný základ PR30 / main a6215705d8bb86eac664288ff6ebe0a12486b90a,
local tree equivalent16cbf524921a5944c2216a74022cc819fed2d0d1.
[Nové testy](../tests/test_backup_idle_0626.py),
[původní nativní testy](../tests/test_native_backup_0624.py),
[SQLite](../tests/test_sqlite_writes_0619.py) a
[FIFO/recovery](../tests/test_night_fixes_0623.py).

Baseline0.6.25 selže na zmizelém WAL po uzavření pracovních spojení,
nečinném otevření pod writer gate a chybějícím zákazu druhé přípravy. Testy
nového holdera na baseline pochopitelně nemají nový modul; tyto import errors
se nevydávají za samostatné produkční vady. První kandidát prošel hlavní
archivní cestou, ale krátká testovací lease začínala před startem procesu a
vypršela ještě před ready. Časový limit se nyní měří od otevřeného spojení.
Použitý posix_spawn neforkuje vícevláknový proces a nevyžaduje Popen objekt,
který by chybně považoval úmyslně žijící child za neuklizený subprocess.

Regrese zahrnují opakované worker connection close/reopen mezi enumerací a
tarem, následnou obnovu přes produkční restore, přežití rodiče pre-hooku,
nezablokované zápisy, I/O selhání přípravy, odmítnutí druhé zálohy, zánik a
expiraci holdera, čistý i nečistý stopped fallback, nečinný publisher/analytiku
pod cizím writer gate, doplnění chybějícího indexu a zachování FULL sync.
Původní testovací fixture archivu nově modeluje pre-filter před stat/open
stejně jako securetar, a uklízí nové hook procesy; původní datové a řídicí
asserty zůstaly zachované. Oficiální kontrakt:
[securetar](https://github.com/home-assistant-libs/securetar).

## Meze

Kandidát není instalace ani úspěšná celá nová noc. Po instalaci vyžaduje
skutečný Supervisor hot archiv s addon v katalogu, ověřený bundle a izolovanou
obnovu při stejném primárním runtime a postupující evidenci. Není to zero RPO,
hard real-time ochrana jističe ani fyzická validace adaptéru. Výpadek celého
kontejneru/hostitele, externí smazání nebo explicitní truncation raw WAL během
archivace nejsou tímto holderem garantované. Taková porucha nesmí být vydaná
za ověřenou nativní obnovu. Původní koordinátor a automatizace se nemění.

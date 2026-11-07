# 0.6.26 · veřejný vývoj opravy

Veřejný základ je [PR30](https://github.com/inenger/home-energy-coordinator-ha/pull/30).
[BACKUP-02](https://github.com/inenger/home-energy-coordinator-ha/issues/31) má
syntetický reproduktor životnosti WAL; [kontrakt opravy](../../priority_shadow/docs/BACKUP_IDLE_0626.md)
obsahuje nový holder, DB-03, původní FAIL, první chybu krátké lease a meze.

Pokusy: 0.6.25 selhává při close posledního SQLite spojení před tar.add a při
nečinném otevření pod writer gate. První kandidát již uchoval WAL a prošel
obnovou, ale příliš krátká testovací lease začínala před ready; opraveno
měření od připojení. Plná historie již zveřejněných verzí zůstává beze změny.

Odmítnuté varianty: záloha zastavením regulátoru; plošné vynechání raw WAL,
které ztratí potvrzená data unclean stopped fallback; vydávání SQLbundle nebo
API úspěchu za úplný native archiv; změna timeoutu/reset counteru namísto
odstranění no-op writer scope. Nové testy zachovávají původní datové asserty.
Fixture archivu nově filtruje jména před stat/open podle securetar a uklízí
samostatné hook procesy.

Velké náhrady převzaté MEMORY/historie byly z publikovaného výběru vyloučené.
Tento nový záznam obsahuje pouze veřejné zdroje, syntetiku a postupy, nikoli
provozní řady, databáze či soukromé protokoly. Publikace, CI, merge a nativní
ověření jsou samostatné kroky; uvedení mechanismu jako opraveného v kódu
není tvrzení dokončeného provozního ověření.

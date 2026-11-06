# Uzávěrka dokumentace a poučení z posledních pokusů

Vstupní veřejný kód: PR #28, main
`02de19a4022678ec3e36b936dbe8544873450487`.
Tento záznam neobsahuje soukromé provozní hodnoty, jejich otisky ani raw logy.
Doplňuje dohledatelnou historii zveřejněného kódu a CI; nemaže původní záznamy a neprovádí nový deploy. Neexportuje provozní MEMORY ani soukromou chronologii.

## Nalezené mezery dokumentace

- Kořenový README uváděl starší verzi stínového balíčku než config/runtime.
- Hlavní chronologie měla podrobné odkazy jen po 0.6.17; následné mechanismy
  byly popsané v samostatných verzovaných dokumentech bez společného indexu.
- Chyběl jednotný registr otevřených příčin a kritérií jejich uzavření.
- Historický dokument robustness brány uváděl původní počet případů;
  pro současnou sadu bylo nutné číst runner a novější release dokumenty.
- Obecná poučení z chyb uzávěrky nebyla ve veřejném přehledu společně s kódem.

Náprava: současný PROJECT_STATUS, KNOWN_ISSUES, TEST_MATRIX a RELEASE_RUNBOOK,
doplněná chronologie, opravený README a automatická kontrola odkazů/verze.

## Veřejně doložené pokusy a obecná preventivní pravidla

| Pokus / závěr | Proč nestačí nebo selhal | Navazující pravidlo / důkaz |
|---|---|---|
| Obnova pomocného workeru vyřeší zastavení celého doplňku při cold backupu | Není živý hlavní proces, který by mohl pokračovat. | N06-01, hot hook a test přes produkční run_loop; [kontrakt](../../priority_shadow/docs/HOT_BACKUP_0624.md). |
| Jen změnit cold na hot | Kopie živého SQLite/WAL nemusí být konzistentní. | Online snapshot, validovaný archiv a ověřená obnova. |
| Vyloučit všechny raw SQLite soubory | U již zastaveného doplňku se pre-hook nespouští. | Zachovat statickou fallback cestu a samostatný test. |
| Obnovovat snapshot při každém startu | Mohl by přepsat novější živou databázi při běžném restartu. | Vyloučený source sentinel, validace před workery, regrese restartu. |
| Předpokládat, že context manager SQLite spojení zavře | Řídí transakci, ne životnost spojení. | Explicitní closing; první testovací ResourceWarning byl opraven. |
| Pevná /data v nové obnově | CI na neroot runneru s přesměrovaným DATA skončilo PermissionError. | Zachované první CI [42261279161](https://github.com/inenger/home-energy-coordinator-ha/actions/runs/42261279161), oprava v e77ef37, původní test neoslaben. |
| update_ref použít pro dosud neexistující větev; vytvořit PR bez platné větve | API422, nevzniklá publikace. | Nejprve create_branch a ověřit jeho výsledek, až potom závislý PR. |
| Z počtu zelených testů vyvodit „vše opraveno“ | Neověřená příčina, fyzická hranice nebo jiná cesta může zůstat otevřená. | Povinný registr a rozsah důkazu; N06-02 zůstává otevřený. |
| Vydávat existenci pravidla v AGENTS za automatické zabránění chybám | Textové pravidlo samo změnu technicky nezablokuje. | Nová kontrola dokumentace běží v CI; není to tvrzení o serverové branch protection. |

## Uchování historie

Veřejné implementační commity, původní neúspěšné CI a obecné odmítnuté
varianty jsou dohledatelné. Podrobné skutečné provozní podklady zůstávají
v soukromém prostředí. Neuložené staré kroky nelze zpětně zrekonstruovat
s jistotou: chybějící záznam se výslovně označí, nevymýšlí se.

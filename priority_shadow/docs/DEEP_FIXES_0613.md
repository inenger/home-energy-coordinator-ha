## 0.6.13 · opravy D01–D06

D01: čtyři proudové údaje karty mají konkrétní pojmenované entity, jednotky
a timestampy. Seznam entit pro sledování změn neurčuje jejich význam.

D02: monitoring běží v samostatném vlákně. Čistá příprava ověřuje allowlist
a byte budget ještě ve fail-closed cestě; nahraditelná fronta drží nejvýše
poslední čekající snapshot každé entity a zachovává férové pořadí. Trvalý
deník má svůj původníSQLite outbox. Jednotlivé chyby monitorů drží degraded
do úspěchu dané entity. HTTP latence/počty/stav mají samostatnou metriku;
rychlá smyčka nevykonává HTTP publikaci ani v chybové větvi. Výpadek sběru
stále okamžitě odvolá uložený intent a prioritně zařadí nulové/unknown monitory.
Nejde o fyzickou real-time záruku; akční adaptér stále chybí.

D03: potvrzení recorderu se hledá od prvního možného přijetí s trvalým
cyklickým kurzorem a omezeným120s dotazem. Prohledávání se vrací ke starším
časům, zahrne pozdější retry a přežije restart i návrat hodin. Resend nemění
první mez. HTTP200 samotné nic nepotvrdí; bez skutečné shody recorderu
zůstává část v trvalé frontě a při dlouhém čekání je transport degraded.

D04: modelový graf zohledňuje explicitní stop i intent_expires_at; nenulový
požadavek nesmí přemostit odvolání nebo konec platnosti. Nejisté mezery se
oddělují. Skutečný měřený proud a trvalý proudový limit mají vlastní série
a virtuálním stopem se nemění.

D05: přesné indexy0..N−1, souhlas metadata a odmítnutí konfliktních duplicit
událostí/vzorků/session/částí. Přesná opakování a jiné pořadíJSON klíčů
zůstávají přípustné. Neúplný či vadný archiv neposkytne controllerSession
a nespadne do živého fallbacku. content_sha256 váže celý kanonický obsah:
{session, events seřazené numericky podleid, samples podle textovéhoat};
rekurzivně seřazené klíče, JSON.stringify, UTF-8, SHA-256. U starých
manifestů bez otisku je zachovaná pouze strukturální kompatibilita; nové
rekonstrukce musí mít otisk. Nasazené archivy je třeba ověřit z recorderu
a doplnit jejich manifestům checksum, bez přepisu původních řádků/provenience.

D06: vlastníka blokuje každá jiná otevřená relace bez ohledu na pořadí dat.
Návrat času pod last_processed_at odvolá výkon, zruší návaznost integrace
a čeká do dohánění původního času. Poté vyžaduje dvě nové platné sady.
Původní model/history se nezpětně nedatují a žádný interval se neintegruje dvakrát.

Regrese: test_deep_fixes_0613.py (skutečná souběžnost, Store, observer,
fronta, zpožděný recorder/restart/pozdní retry/časový návrat) a
scripts/test_deep_fixes_0613.mjs (čtyři různé proudy, grafstop/TTL,
indexy/konflikty/integrita a zamezení částečného modelu). Původní auditní
skripty jsou opakovatelným srovnáním; staré důkazy zůstávají zachované.
Starší test návratu hodin je zesílen na čekání do monotónního času.

Připravená oprava; nasazení a skutečný recorder/browser se ověřují samostatně.
Režim observe_only, žádné změny starých automatizací, priorit či tarifů.
Žádný akční adaptér, fyzický povel nebo EEPROM zápis.

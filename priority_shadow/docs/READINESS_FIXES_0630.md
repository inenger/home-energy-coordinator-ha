# 0.6.30 · Opravy auditu připravenosti

Výchozí Git SHA: `dee01fc4dc096fd800a3bcf6cc7ec71f0fbc30e4`, verze 0.6.29.
Samostatná stínová implementace `priority_shadow`. Režim zůstává pouze `observe_only`, počet fyzických příkazů je nula. Historický [audit 0.6.29](../../docs/READINESS_AUDIT_0629.md) se nemění.

## Přijaté změny

- **N06-03:** komplexní REST /api/states běží v single-flight vlákně nezávisle na HA template; během čekání žádné omlazování komplexních atributů; na snapshot race explicitní příznak. Test blokovaného GET a opakovaných rychlých template dotazů.
- **N06-04:** watchdog sleduje skutečné vlákno, aktivní request a monotónní stáří. Mrtvé vlákno obnovuje maximálně třikrát v klouzavých 300 s a latchuje výpadek; živé uvízlé vlákno nikdy bezhlavě neduplikuje. Původní TTL 7.5 s zachováno. Python thread s uvázlou nativní operací nelze bezpečně zabít; další kroky vyžadují procesovou izolaci / hardwarovou diagnostiku.
- **REC-02:** pending durable sequence a monotónní ACK age jsou nezávislé na poslední IPC odpovědi. Při lokálním WriterTimeout je restart omezen existujícím WorkerGuard budgetem. Při známém plném disku/IOERR automatické restarty nerecyklují poruchu; stav zůstává degraded a vyžaduje zásah.
- **DATA-03:** obsah at, rows, loss, states, result a failure_generation je hashován a atomicky zapsán do nové tabulky receipt s původní dávkou. Přesná opakování jsou idempotentní. Kolize payloadu i historická potvrzení bez autentizovaného receiptu vrací explicitní konflikt; immutable rows se nepřepíší. Původní loss payload se nemění.
- **DATA-04:** konfliktní SOC návrh ve stejný čas nesmí vracet falešný hash. Neplatný protinávrh přidává revokaci do oddělené durable SQL tabulky; původní rozhodnutí zůstává neměnné, session_plan již dřívější validní návrh nevrací.
- **MON-03:** bezpečný reason_code má whitelist známých sémantických chyb sběru, raw výjimky a tokeny se nevystavují.
- **UI-01:** neplatná sunrise metadata zobrazí — místo RangeError. Testuje se skutečná card.render v Node VM i platné datum v Europe/Prague.

## Důkazy a slepé cesty

Staré protipříklady jsou bez úprav zachované v [Python](../../docs/history/readiness_counterexamples_0629.py) a [JS](../../docs/history/readiness_counterexamples_0629.mjs), stejně jako v původním Git commitu. Přepis na akceptační testy nemění jejich původní výsledek. První kandidát SOC revokace zvedal výjimku uvnitř transakce: SQLite vracelo rollback a starý validní plán zůstal; odmítnuto a opraveno explicitním commit před vyhozením konfliktu. První asynchronní implementace změnila synchronní testovací předpoklady 0.6.18; test byl aktualizován na dokončení workeru, nikoliv vypnut.

Cílené akceptační Python testy, asynchronní kontext a Node render byly spuštěny na izolovaném checkoutu na RPi a procházely. Původní kompletní historická unittest sada byla po více minutách zastavena, aby neomezila 4GB HA host; její PASS se **netvrdí**. GitHub CI, provozní noc, nativní archiv i instalace mají samostatný důkaz a musí být ověřeny pro konkrétní commit.

## Co zůstává otevřené

**NO-GO pro LIVE.** Neexistuje akční adaptér, readback ani nezávislý watchdog zařízení. LIVE-01/02/03, historická DB-01 a neprokázaná příčina N06-02 zůstávají otevřené. Nové softwarové opravy nejsou fyzickou certifikací ani automatickým nasazením.

## Dodatečné regresní zjištění

První hash implementace používala binární pickle včetně reference-aliasingu, který není stabilní po přenosu přes multiprocessing. Přepracováno na kanonický JSON obsah a HEX kódování SQL blobů. Starší ACK sekvence zůstávaly krátce v in-flight mapě po potvrzení, a jejich historický wall-clock čas okamžitě falešně spouštěl opakované restarty. Posuzují se nyní jen seq větší než durable ACK. Reálné spawn replay testy pro crash po commitu před ACK a zamrzlý writer následně prošly.

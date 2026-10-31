## 0.6.12 · obnova výkonu v mezích původní čerstvosti

Při asynchronním 5s sběru mohl opakovaný čerstvý snímek ponechat desetisekundový
intent bez obnovy. Následující nová sada pak dorazila o milisekundy po expiraci
a vyvolala zbytečné zastavení a novou rampu. Politika volatile-power-shadow-v2
odděluje zvýšení výkonu od držení: dvě nové celé sady jsou nadále podmínkou
převzetí/obnovy a pouze nová celá sada dovoluje zvýšení. Stále platná lease může
být obnovena na stejný či nižší výkon při úplných validních vstupech. Opakovaný snímek se nestává novým reportem ani good frame.

Platnost každého nenulového intentu je minimum z času vydání +10s, původních
deadline všech požadovaných rychlých vstupů, napětí/limitu/SOC baterie, stavu
měniče, obou vlastníků a konce nočního okna. Neprodlužují se reporty ani jejich
povolené stáří. Opakovaná data tedy nemohou výkon udržovat neomezeně. Skutečná
expirace, neplatné vstupy, cizí vlastník, výpadek sběru a mezera rychlé smyčky
nadále zastavují s nutností dvou nových sad. Integrace energie končí na skutečné
deadline; žádná mezera se neúčtuje jako nabíjení.

Vzorek ukládá intent_expires_at, input_valid_until a způsob obnovy. Událost
would_renew je v kartě označená jako podržení výkonu bez zvýšení. Původní živá
evidence a předchozí rekonstrukce zůstávají zachované; nový výpočet má vlastní
archiv a provenienci. Historicky nedoložené heartbeat časy zůstávají výslovným
předpokladem, nikoli změřenou skutečností.

Regrese: test_lease_0612.py pokrývá asynchronní celou noc, restart SQLite,
nezávislou integraci energie, souhrn a bezztrátový outbox; samostatně duplicity,
absolutní stáří, rollback, neplatné vstupy, skutečnou expiraci a výpadek.
Původní testy ukončení po pevných10s bez nových snímků jsou aktualizované
na nezměněnou15s mez čerstvosti zdroje. Privátní opakování původních pěti
selhání i dnešní noci běží jen na RPi. Fyzický adaptér a hardwarový timeout
nejsou touto opravou ověřené; observe_only zůstává zachované.

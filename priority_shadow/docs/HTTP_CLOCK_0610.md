# Opravy 0.6.10

B01: karta rozbalí monitor i části deníku přes HTTP bez WebCrypto subtle. Nativní SHA-256 zůstává preferovaná; fallback počítá stejný hash nad celým omezeným vstupem. Kontroly délky, SHA-256, maximální velikosti a úplnosti zůstávají povinné.

B02: odmítnutý snímek neposouvá accepted_solax_reports. Starší neplatná nebo budoucí reference vede k nulovému intentu a zaznamenané frame_reference_reset. Dva nové platné SolaX snímky jsou stále nutné; nesmí se obejít owner, freshness, skew ani Normal Mode.

B03: opakovaná část se stejným obsahem se přijme i při jiném pořadí objektových klíčů. Změna hodnoty, pole nebo skutečná kolize zůstává chybou.

## Ověření zdroje

399 Python testů prošlo. Tři původní auditní kontrakty nyní procházejí. Node ověřuje SHA proti nezávislé implementaci včetně známých vektorů, náhodných délek až 2 MiB, HTTP bez subtle, HTTPS s WebCrypto a prostředí bez crypto. Transport ověřen v obou režimech; změna klíčů i skutečná kolize pokryty. Renderer a konzistence verzí prošly.

Jde o VM test schopností browseru, nikoli vizuální ověření skutečným browserem. Na RPi není nainstalovaný browser. Skutečná nasazená karta, monitory a archiv musí být po nasazení znovu načteny a rozbaleny ve stejném omezeném prostředí.

## Provozní meze

Pouze observe_only. Žádný fyzický povel, zápis registru či změna automatizace. Stávající archiv zůstává s původní verzí výpočtu 0.6.9, bez nové rekonstrukce. Tato oprava sama nepotvrzuje ostré řízení, fyzický timeout ani mapování Direct Mode8. Nasazení a kontroly historie se evidují odděleně na RPi.

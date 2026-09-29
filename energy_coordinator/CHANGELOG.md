# 0.5.0
- Stínový scénář nabíjení auta porovnává slunečné všední dny, víkendy a noční tarif podle dostupných hodinových předpovědí a cen. Nemá pevně zakódované okno 03:00–05:00.
- Nový graf zobrazuje naměřený výkon domu a podmíněný scénář. Návrhy se ukládají s časem vydání a původem předpovědi; nejde o změřenou úsporu ani celé řízení baterie.
- Jednou za ukončený týden se archivované návrhy porovnají s překrývajícími se měřeními. Odchylka je popisná, nikoli výpočet úspory.
- Bez potvrzeného připojení, SOC, cíle auta, profilu domu a explicitních parametrů se číselný scénář nevytvoří. Žádná akční služba ani automatizace nepřibyla.

# 0.4.1
- Oprava zobrazení UTC časů v UI na Europe/Prague včetně DST regresních testů.
- Interní GitHub runtime updater je ve výchozím stavu vypnutý; cílem je jediný update kanál přes Home Assistant Supervisor.
- Připraven podklad pro standardní HA App Repository distribuci.

# 0.3.1
- Oprava publikování analytických senzorů při dosud nekalibrovaných hodnotách.
- Jedna chybná monitorovací entita už nezablokuje publikování ostatních.
- Regresní testy pro unknown/NaN/Inf stavy.
- Připraveno pro čistý reinstall/upgrade po nekonzistentním 0.3.0 rollout pokusu.

# 0.3.0
- Lokální analytická vrstva nad uloženými minutovými daty.
- Kalibrace Solcastu podle skutečné výroby, sezóny a předstihu forecastu; raw/corrected/reality metriky.
- Výrobní parametry SolaX T-BAT H 11.5: 11,5 kWh nominálně, 10,4 kWh využitelně, 95 % round-trip, 90 % DoD.
- Evidence degradace baterie: efektivní kapacita, throughput a ekvivalentní plné cykly; bez automatické změny řídicích limitů.
- Automatická discovery měřených chytrých zásuvek a rozpoznání cyklů myčky, pračky a 3D tiskárny.
- Spotřebičové statistiky kWh, tarif-equivalent Kč, trend 7/30 dní a jednoduché anomálie.
- EV domácí nabíjení: session, kWh, Kč podle skutečné ČEZ INDI ceny každého intervalu a vážená Kč/kWh.
- Tesla odometr + lifetime energy pro trend kWh/100 km.
- Nový lokální Ingress dashboard: denní energie, Solcast korekce, baterie, EV, spotřebiče, samokalibrace a anomálie.
- Bezpečný code-only updater pro privátní GitHub: explicitní release manifest, SHA256, test před aktivací, atomické přepnutí a rollback.
- Runtime zůstává observe_only; žádné fyzické ovládání zařízení.

# 0.2.0
- Přesun runtime do nativní aplikace Home Assistant pro aarch64 / Raspberry Pi 4.
- Interní Supervisor API a jeho token; odstranění provozní závislosti na tds-dev/Tailscale.
- Trvalá data /data/evidence, lokální webový přehled přes HA Ingress.
- Sezónní trendová samokalibrace zbytkové spotřeby pouze jako kandidátní model.
- 24 nových testů, osm explicitně povolených monitorovacích entit.
- Sběr stále bez ovládání zařízení; žádné tvrzení o reálných úsporách.

# PEAK-02 / MODBUS-02 (0.6.38) – čerstvost fází a měření Modbus skupin

Datum: 22. 11. 2026. Pouze Raspberry Pi Home Assistant, pozorovací doplněk. AC hlavní jistič 3×25 A, Modbus FAST 1 s, MEDIUM/DEFAULT 5 s, stínové řízení 5 s. Žádný fyzický povel ani změna limitů zařízení.

## PEAK-02 – bezpečnější vyhodnocení pokrytí

Dřívější osmivteřinové highwater maximum mohlo znamenat stav ok i tehdy, když fáze již několik sekund neposílala aktuální report. Nyní jsou nezávislé informace: 8s maximum každé fáze a stáří jejího nejnovějšího skutečného source last_reported.

- Stáří v čase kontrolního snapshotu = fyzický věk v HA při sběru + monotonic čas od sběru. Opakovaná stejná časová značka nikdy neobnovuje čerstvost.
- Při starším než 3,0 s nebo chybějícím validním reportu fáze je quality stale/missing, okno unverified a 5s virtuální regulátor fail closed.
- Kratší výpadek při stále čerstvém reportu může být held_fresh_prior; takto je transparentně označen.
- Max report gap a inferred missed reports vycházejí z HA časových značek a 1s noc / 2,5s den očekávané sběrné periody. Není to potvrzený počet ztracených Modbus paketů.
- Maxima nad 25 A jsou pouze virtuálně blokována; nejde o hard-real-time ochranu jističe. Nezměněné původní souhrny, SOC, prioritizace, fyzické nastavení a retence.

## MODBUS-02 – měření skutečných dob cyklů

Custom SolaX Modbus verze 2026.11.04 plánuje dotazování podle číselných intervalů. FAST 1 s a společná MEDIUM+DEFAULT 5 s jsou tedy dvě skutečné skupiny. Není poctivé je vykazovat jako tři samostatné skupiny, protože 5s dotaz se uskuteční společně.

Read-only observabilita měří čas celé operace od startu do dokončení podle původního upstream monotonic časovače. Na každou periodu drží v RAM maximálně 64 dokončených cyklů, průměr, P95, P99, max, úspěšnost, počet cyklů a počet překročení periody. Diagnostika se přepočítává každých 30 sekund a zveřejní ve stávajícím atributu poll_interval_diagnostics zdravotního senzoru SolaX. Nepřidávají se nové entity ani databázové tabulky, ale atribut tohoto senzoru se mírně zvětší.

Stínový HEC sbírá read-only health stav z HA a sleduje rozdíl overrun čítače, rychlost překročení za minutu a group_latency_stats. Neměním skutečnou periodu ani Modbus register block. Pokud se plugin v budoucnu aktualizuje, vlastní lokální instrumentation patch musí být znovu zhodnocen a případně aplikován. Původní upstream soubor a záloha 0.6.37 na RPi jsou zachovány pro rollback.

## Přijetí

Syntetické testy PEAK-02: 3s freshness / 8s highwater, duplicate, stale, missing phase, recovery, daytime 2,5 s, RAM virtual stop, žádné fyzické akce. Syntetické testy Modbus: 70 FAST + 20 pomalých cyklů, P95/P99 a výpočet overrun.

Po restartu: vyžadovat stav HEC 0.6.38 observe_only, zdravý SolaX a obě intervalové skupiny, čerstvé a správně označené fáze, evidence pipeline OK. Následující celé noční období je samostatný akceptační test, nikoli dnes potvrzená fyzická bezpečnost.

Všechny soukromé logy, binární DB a 1s raw časové řady zůstávají pouze na RPi; neukládat je do GitHubu.

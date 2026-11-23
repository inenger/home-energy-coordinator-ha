# PEAK-03 – fail-closed při chybějícím fázovém okně (0.6.39)

Datum: 23.11.2026. Autoritativní zdroj: `priority_shadow/energy/ram_control.py`.
Pouze změna zdroje na GitHubu; na RPi nadále běží 0.6.38 `observe_only`.

## Kontrapříklad na 0.6.38

Produkční SnapshotCollector v běžném stavu předává `collection_phase_peaks`.
Samotný RAM regulátor 0.6.38 ale vyhodnocoval nové ochranné okno pouze
při `peak_window is not None`. Pokud pole nebylo předáno, samostatné
15s HA reporty vyhověly a model simuloval 0 / 500 / 1000 / 1500 W
bez chyby. To **není** potvrzení skutečné události v provozu, jde
o izolovaný E2E protipříklad. Žádný akční adaptér neexistuje.

## Oprava

`peak_window_errors()` považuje chybějící, ne-dict, ne-`ok`,
neúplné, falsifikované či nesprávně čerstvé fázové informace za
`fast_phase_peak_window_unverified`. Platná data musí potvrdit
všechny L1/L2/L3: `phase_quality`, `last_report_age_s`,
`maxima`, `last_reported`, interval 8 s a limit stáří 3 s.
Hodnoty `maxima` musí být konečné a nezáporné.
Kromě indikátoru `over_limit_phases` se **nezávisle**
porovnává každá maxima s 25 A, takže falešné prázdné pole
neobchází virtuální blokaci.

Pro návrat z neplatných dat platí stávající dvě nové koherentní
reportovací sady. Záměrně se neimplementuje náhradní domyšlené
měření ani ztráta naměřených raw vzorků. Syntetické unit/E2E
test fixtures vytvářejí explicitní důkazní metadata; produkční
`MemoryControl.step` žádná chybějící nedoplňuje.

## Regrese a hranice

[Test PEAK-02/03](../priority_shadow/tests/test_phase_freshness_0638.py)
ověřuje úplně chybějící okno, `None`, prázdné a pouze
`status=ok` okno, chybějící jednotlivé fáze, překročení 25 A
i při falešné flag sadě, recovery a nulové fyzické povely.
Původní [PEAK-01](../priority_shadow/tests/test_phase_peaks_0637.py)
ověřuje 1s špičky mezi 5s kroky.

Tento kód **není nezávislé hardwarové omezení** proudů.
`observe_only` bez fyzických povelů. LIVE-01/LIVE-02
zůstávají otevřené a musí být otestovány při souběhu EV/baterie
včetně nezávislé 3×25A ochrany. Žádný proud, výkon měniče,
Modbus perioda, Recorder ani addon DB nebyly touto změnou přepnuty.

## Historie

- Baseline `c9a2024`: 0.6.38 guard s volitelnými metadaty.
- Neúspěšný předpoklad: `status=ok` bude vždy znamenat kompletní
  fázové okno – explicitně testován protipříklad `{'status':'ok'}`.
- Zamítnuto: tiché nahrazení chybějícího okna nulovými proudy.
- Oprava: fail-closed v jediném vstupním bodě RAM regulátoru.
- GitHub CI a nasazení zůstávají samostatným akceptačním krokem.

## Zpětný replay historických nocí

Přímá kontrola zabaleného Docker testu zjistila, že offline
`replay_archived_night.py` původně nepředával již archivovaná
`ram_control_samples.phase_peak_window`. 0.6.39 jej nyní předává
**pouze přesně ve zdokumentovaném čase původního 5s kroku**.
Pokud historická relace žádné 1s highwater neuchovala, moderní
replay neodvozuje bezpečnost z řidších HA stavů, neimputuje nulu
proudu a kladný výkon je **výslovně zablokovaný**.
Pouze syntetická fixtures mají kontrolovaně generovanou evidenci.
Regrese: [archivovaný replay](../priority_shadow/tests/test_archived_replay.py).

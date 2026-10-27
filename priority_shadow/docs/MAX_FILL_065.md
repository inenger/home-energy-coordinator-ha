# 0.6.5 — okamžitá stínová alokace

Runtime používá instant-max-fill-v1 mezi 03:00–05:00 Europe/Prague.
Ekonomický návrh SOC je poradní; jeho odmítnutí neblokuje okamžité využití
přípojky. Strop modelu je 100 %, výsledné SOC je výsledek, ne pevný cíl.

Přípojka: 25 A jednotlivě pro každou fázi. Základ domu bez EV = výkon
měniče minus podepsaný síťový výkon minus právě nahrazované EV. Aktuální
U/P/I poskytují označený proxy účiníku, nikoli nezávislou kalibraci čidla.
Historická rezerva ani pevný účiník 0,9 nevstupují do okamžité alokace.
Nízké proudy používají konzervativní trojúhelníkovou mez. Měnič/baterie
mají předpoklad vyváženého AC výkonu; nejslabší fáze omezuje nabíjení.

EV priorita zachová naměřené požadavky fází auta pod nastavením 16 A
(s uvedenou tolerancí měření). BAT priorita přidělí baterii výkon první;
minimum proudu EV se kontroluje po kvantování baterie. DC limit je I*U;
převod AC/DC zůstává explicitní předpoklad. Neověřený AC limit se nevymýšlí;
případný doložený limit lze předat session. Stav není live_ready.

Proudové vstupy jsou explicitní inverter Solax Grid Current. API proud
wallboxu je jen diagnostika, nikdy náhrada chybějícího měření. Neplatné,
rozporné a zastaralé vstupy vyřadí interval. Archivovaný energetický model
se zachytí bez budoucích dat a během relace zůstává neměnný i po restartu.
Bez něj se nevyrábí falešný odhad SOC. Výkon ani prognóza nejsou povely.

Denní audit v4 rozlišuje kalendářní den od opožděného resetu při podzimní
změně času. Přičte zaznamenaný přírůstek před resetem k čítači po resetu;
uchová časy hranic a příznak kvantování. Chybějící počáteční stav,
neplatné hodnoty či další reset zůstanou nevyhodnotitelné. Obecné pozdní
resety se nepovolují. Starší revize se nepřepisují.

Historický empirický rozpočet je pouze poradní. Kalibrace PF a kroky
základní zátěže mají oddělené masky; pozorovaná nepřípustná rezerva
rozpočet zablokuje místo návratu k legacy fallbacku.

Regrese: test_instant_fill.py, starší sady a test_partial_card.mjs.
Přehrání skutečných dat probíhá výhradně na RPi a mimo veřejný checkout;
porovnání používá stejné platné intervaly a netvrdí naměřenou úsporu.
Pouze observe_only, bez fyzického adaptéru. Nulová reakční rezerva je
stínový předpoklad, nikoli schválení fyzického řízení na hranici jističe.

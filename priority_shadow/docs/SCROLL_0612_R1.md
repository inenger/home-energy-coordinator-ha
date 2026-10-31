## Frontend0.6.12-r1 · stabilní čtení a stránkování deníku

Karta při každém HA hlášení nahrazovala celý shadow DOM, obnovovala scroll
podle indexu tabulky a otevření details podle společné CSS třídy. Doplnění
jiné tabulky tak přeneslo offset jinam a rozbalení jedné capacity otevřelo
i ostatní. Zobrazení celé relace současně vytvářelo stovky řádků; dekódovaný
monitor navíc dostával novou objektovou identitu i při nesouvisejícím HA
hlášení. Časovač i výškový ResizeObserver vyvolávaly další zbytečnou práci.

Nově se mění obsah stávajících DOM prvků podle stabilních klíčů. Zaniklé
prvky se odstraňují před vložením nových, aby nová výstraha nepřesouvala
všechny další panely. Zachovávají se jednotlivá details, focus, horizontální
offset, čtený řádek i vnější HA scroll. Při doplnění obsahu nad čteným místem
se kompenzuje pouze skutečná změna jeho polohy. Scroll tabulky se nesmí
kompenzovat o pohyb celé tabulky na stránce.

Deník uchovává všechny načtené události/vzorky, ale současně vykreslí nejvýše
50 událostí. Celý deník je dostupný po stránkách. Nové živé události neposunou
rozečtené okno; zobrazí se po výslovném kliknutí na tlačítko nových událostí.
Uzavřený kompletní stream se znovu nestahuje bez změny očekávaných počtů
nebo výslovného reloadu. Neúplné a aktivní streamy mají původní obnovu dat.

Dekódované State wrappery mají při stejném zdrojovém State stabilní identitu.
Externí změny se slučují do animation frame, stejné fragmenty se nepřekreslují
a formáty Intl se používají opakovaně. ResizeObserver reaguje jen na změnu
šířky; grafy mají vyhrazenou výšku.

Regrese: scripts/test_card_updates.mjs (identita, cache, explicitní reload,
úplnost všech stránek a stabilní živé okno) a test_card_scroll_browser.mjs
(skutečný Chromium, dvě šířky, načtení obsahu, geometrie, wheel, focus,
details a všechny události). Browser test přijímá PUPPETEER_MODULE_PATH,
CHROMIUM_PATH, CARD_SOURCE, CARD_FIXTURE a CARD_BROWSER_RESULT. Skutečná
data se předávají pouze na RPi; výchozí data jsou syntetická. Browser běží
na testovací stránce s vnořeným shadow scroll kontejnerem; není to přihlášený
HA shell. Načítání skutečného HA recorderu se ověřuje samostatně.

Jde pouze o frontendovou revizi. Backend0.6.12 ani observer0.5.4 se nemění
a nerestartují. Archivní manifesty a původní data se nepřepisují. Fyzický
adaptér zůstává vypnutý. Soukromá evidence v recovery adresáři na RPi.

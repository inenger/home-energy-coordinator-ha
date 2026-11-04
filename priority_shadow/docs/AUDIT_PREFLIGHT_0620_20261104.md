# Audit preflight kontraktu 0.6.20

Stav sběru, kontinuita řídicí smyčky a skutečné převzetí relace jsou různé důkazy. Žádný počet bezchybných sběrů nebo nulových stopů sám neprokazuje, že regulátor začal nabíjet alespoň ve stínovém modelu.

Syntetická reprodukce test_preflight_audit_0620.py prochází produkční MemoryControl a původní stavový algoritmus. Při čerstvých platných měřeních, známém modelu, Disabled remote vlastnících, pracovní strategii Back Up Mode a uložené volbě ručního podrežimu Force Charge je okamžitá alokace kladná, ale převzetí zůstává blokované důvodem unowned_manual_charge_or_discharge.

Příčinou v kódu je nepodmíněné vyhodnocení volby manual_mode_select: gate nerozlišuje, zda je aktivní pracovní režim Manual Mode. Reprodukce dokládá softwarové chování; samotná uložená volba ještě neprokazuje aktivní fyzické řízení cizím vlastníkem. Před změnou gate je nutné ověřit tuto vazbu a zachovat ochranu proti skutečnému souběhu. Tento audit gate ani provozní nastavení nemění. Test zachycuje současný protipříklad, nikoli schválení tohoto chování jako budoucího požadavku.

Dílčí WriterTimeout analytiky musí být posuzován odděleně od úspěšného commitu evidence a od stavu regulátoru. Noc bez převzetí není pozitivní celonoční validací běžící výkonové regulace, i když má úplnou evidenci.

Auditní nástroje zpracovávají velkou HA historii po řádcích s paměťovým limitem. Původní přepočet vyžadující started_at a účtovanou energii není použitelný pro relaci not_started; výsledek musí rozlišit nulovou realizovanou regulační energii a neprovedený SOC model.

Veřejně jsou pouze obecné závěry a syntetická reprodukce. Žádná provozní časová řada, export logů, soukromá MEMORY ani soukromý hash manifest nejsou součástí změny. Runtime zůstává 0.6.20, bez nového nasazení.

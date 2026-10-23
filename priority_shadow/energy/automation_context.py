"""Audited descriptions and live HA status only. No automation/service writes."""
CONFIG_CHECKED_ON='2026-10-23'
CONFIG_SHA256='1f39eac7dd4662f91bb9c414db438f52e325a22258f0b2d6bade4c17e06a1dbc'

GROUPS=[
 {'title':'EV priorita · zapnutí (dvě varianty)',
  'ids':['automation.ev_priorita_nabijeni_zapnuti_2','automation.ev_priorita_nabijeni_zapnuti'],
  'current':'Nad 300 W po dobu 1 minuty zapne EV prioritu; vypne 3 fáze patrony a čerpadlo bojleru, nastaví TČ na MEDIUM a posun topné křivky na 0. Platí i mimo 03–05.',
  'planned':'Pro ostré 03–05 sjednotit obě varianty a přenechat jejich zásahy koordinátoru; předejít souběžnému řízení a uvolnění spotřebičů po dobití auta.'},
 {'title':'EV priorita · vypnutí', 'ids':['automation.ev_priorita_nabijeni_vypnuti'],
  'current':'Pod 50 W po dobu 5 minut pouze vypne příznak EV priority. Neobnovuje původní stav patrony, čerpadla ani topné křivky.',
  'planned':'V nočním okně neuvolňovat koordinovanou rezervu jen proto, že auto dokončilo nabíjení; baterie může dál potřebovat výkon.'},
 {'title':'Baterie · levný proud · zapnutí', 'ids':['automation.baterie_nabijeni_levny_proud_zapnuti_2'],
  'current':'Vyžaduje povolení levného proudu, SOC pod 50 %, zbývající FVE pod 15 kWh a vypnutou EV prioritu. Okna 03–05, 11–12 a 13–14; přepíná na Manual Mode / Force Charge.',
  'planned':'Pro 03–05 nahradit staré hranice cíli 90 / 80 / 70 / 30 % a společným fázovým rozpočtem auta a baterie. Denní okna posoudit zvlášť.'},
 {'title':'Baterie · levný proud · vypnutí', 'ids':['automation.baterie_nabijeni_levny_proud_vypnuti_2'],
  'current':'Při aktivní relaci zastaví nabíjení mimo okna, při EV prioritě, odvolání povolení, FVE alespoň 20 kWh nebo SOC alespoň 97 %. Přepíná Back Up Mode / Stop Charge and Discharge.',
  'planned':'V 03–05 nesmí přepisovat nový cíl a prioritu; ukončení a dosažení cíle musí vlastnit stejný koordinátor jako zahájení.'},
 {'title':'Zvýšení spotřeby · patrona a TČ',
  'ids':['automation.zapnuti_ohrevu_bojleru','automation.tc_tepla_voda_zapnuti','automation.tc_posun_krivky'],
  'current':'Všechny mají podmínku vypnuté EV priority. Patrona smí startovat až po 09:00, zvýšení křivky 07–20, ohřev TČ na LARGE po východu slunce + 1 h.',
  'planned':'Nejde o důvod plošně vypínat automatizace. Při ostrém nočním řízení zamezit novému zvýšení zátěže i po dobití auta a započítat již běžící spotřebu.'},
 {'title':'Čerpadlo bojleru',
  'ids':['automation.cerpadlo_bojleru_automaticke_spusteni','automation.bojler_cerpadlo_zapnuti_tp','automation.automaticke_vypnuti_cerpadla_bojleru'],
  'current':'Zapnutí podle režimu TČ LARGE nebo příkonu patrony nad 100 W; vypnutí má vlastní časové a teplotní podmínky. Zapínací pravidla nemají podmínku EV priority.',
  'planned':'Zohlednit opětovné zapnutí čerpadla. Nevypínat ho plošně bez posouzení vazby na ohřev a odvodu tepla.'},
 {'title':'Návrat ohřevu do základního režimu',
  'ids':['automation.vypnuti_ohrevu_bojleru','automation.nova_automatizace_3','automation.tc_posun_krivky_na_nulu'],
  'current':'Podle výroby a SOC vypínají patronu, vracejí TČ na MEDIUM nebo topnou křivku na 0.',
  'planned':'Ponechat základní a omezující funkce; neblokovat vše bez rozlišení jen kvůli nočnímu algoritmu.'},
 {'title':'Starší řízení baterie · původně vypnuté',
  'ids':['automation.baterie_nabijeni_zapnuti','automation.baterie_nabijeni_vypnuti','automation.vybijeni_baterie_zapnuti','automation.baterie_vybijeni_do_site_vypnuti','automation.vecer','automation.nabijeni_baterie_na_cas','automation.baterie_nabijeni_zapnuti_blok_2h','automation.baterie_nabijeni_vypnuti_2h_blok'],
  'current':'Při auditu byly vypnuté. Obsahují další přepínání režimů měniče podle času, spotu a bloků levného proudu.',
  'planned':'Bez důvodu je nezapínat. Před ostrým režimem ověřit, že nevznikl další souběžný vlastník řízení měniče.'},
 {'title':'FVE · povolení a zákaz přetoků',
  'ids':['automation.mensi_vykupni_cena_nez_03_kc','automation.povoleni_pretoku_vyssi_nez_05_kc'],
  'current':'Mění limit exportu podle výkupní ceny; neřídí cílové SOC nočního nabíjení.',
  'planned':'Ponechat oddělené. Případný exportní limit zahrnout při vyhodnocování výroby a přetoků.'},
]
FLAGS={
 'EV priorita':'input_boolean.ev_nabijeni_priorita',
 'Levný proud · povoleno':'input_boolean.baterie_nabijeni_levny_proud_povoleno',
 'Levný proud · aktivní':'input_boolean.baterie_nabijeni_levny_proud_aktivni',
 'Nabíjení baterie · příznak':'input_boolean.battery_charge',
}
ENTITY_IDS=tuple(sorted({eid for g in GROUPS for eid in g['ids']} | set(FLAGS.values())))


def snapshot(states,at):
    by={s['entity_id']:s for s in states}
    def status(eid):
        s=by.get(eid,{})
        return {'entity_id':eid,'state':s.get('state','missing'),
                'name':s.get('attributes',{}).get('friendly_name',eid),
                'last_triggered':s.get('attributes',{}).get('last_triggered')}
    return {'observed_at':at,'config_checked_on':CONFIG_CHECKED_ON,'config_sha256':CONFIG_SHA256,
            'mode':'observe_only','applied_to_control':False,'device_actions':0,
            'groups':[{**g,'automations':[status(eid) for eid in g['ids']]} for g in GROUPS],
            'flags':[{'label':label,**status(eid)} for label,eid in FLAGS.items()],
            'note':'Descriptions reflect the reviewed configuration; current on/off states are read live. The shadow algorithm disables no automations.',
            'after_window':'Budoucí ostré řízení má v 05:00 ukončit vlastní zásahy a bezpečně vrátit pouze převzaté stavy. Nezapínat hromadně všechny automatizace ani neobnovovat ohřev bez kontroly aktuálních podmínek.'}

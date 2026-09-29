"""Publish only explicit monitoring sensors. No service calls and no actuator IDs."""
import json
import urllib.request
from .collector import DATA, NoRedirect, settings, read_token
from .core import VERSION

IDS=(
'sensor.energie_v3_sber_stav','sensor.energie_v3_posledni_sber','sensor.energie_v3_pocet_vzorku',
'sensor.energie_v3_profil','sensor.energie_v3_pripravenost_porovnani','sensor.energie_v3_samokalibrace',
'sensor.energie_v3_kalibrace_pocet_dni','sensor.energie_v3_kalibrace_zlepseni',
'sensor.energie_v3_fve_predikce_zitra','sensor.energie_v3_fve_korekce',
'sensor.energie_v3_baterie_efektivni_kapacita','sensor.energie_v3_baterie_soh',
'sensor.energie_v3_ev_mesic_kwh','sensor.energie_v3_ev_mesic_naklad',
'sensor.energie_v3_ev_prumerna_cena','sensor.energie_v3_spotrebice_pocet',
'sensor.energie_v3_spotrebice_cykly_30d','sensor.energie_v3_anomalie_pocet',
'sensor.energie_v4_telemetrie_pocet','sensor.energie_v4_teploty_pocet',
'sensor.energie_v4_pocasi_stav','sensor.energie_v4_pocasi_pocet_paru','sensor.energie_v4_data_kvalita'
)

def request(entity_id,payload,base,token):
    if entity_id not in IDS:raise ValueError('Only exact monitoring IDs are allowed')
    if set(payload)-{'state','attributes'}:raise ValueError('Invalid payload')
    return urllib.request.Request(base.rstrip('/')+'/api/states/'+entity_id,
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode(),method='POST',
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})

def _load(name):
    p=DATA/name
    return json.loads(p.read_text()) if p.exists() else {}

def _safe_state(value):
    if value is None:
        return 'unknown'
    if isinstance(value, float) and not __import__('math').isfinite(value):
        return 'unknown'
    return value

def main():
    cfg,_=settings();status=_load('status.json');cal=_load('calibration.json');a=_load('analytics.json')
    stamp=status.get('last_observed_at');validation=cal.get('validation') or {}
    pv=a.get('pv') or {};up=(pv.get('upcoming') or {}).get('tomorrow') or {}
    bat=a.get('battery') or {};ev=(a.get('ev') or {}).get('month') or {};apps=a.get('appliances') or {}
    cycles=sum(x.get('cycles_30d') or 0 for x in apps.values())
    translate={'collecting':'sbírá podklady','disabled':'vypnuto','insufficient_validation':'málo testovacích dat',
               'candidate_improves_holdout':'kandidát k posouzení','candidate_not_better':'beze zlepšení'}
    imp=validation.get('relative_improvement')
    rows=[
      (IDS[0],'Sběr dat V3','běží' if stamp else 'chyba',{}),
      (IDS[1],'Poslední sběr V3',stamp or 'unknown',{'device_class':'timestamp'}),
      (IDS[2],'Vzorků V3',status.get('samples',0),{}),
      (IDS[3],'Kalendářní profil V3',{'winter':'zima','spring':'jaro','summer':'léto','autumn':'podzim'}.get((status.get('decision') or {}).get('season'),'unknown'),{}),
      (IDS[4],'Porovnání V3','čeká na kalibraci',{'real_comparison_running':False,'savings_czk':None,'missing_approvals':(status.get('decision') or {}).get('missing_approvals',[])}),
      (IDS[5],'Samokalibrace V3',translate.get(cal.get('status'),'čeká na výpočet'),{'minimum_complete_days':cal.get('minimum_complete_days',14),'calculated_at':cal.get('calculated_at'),'applied_to_control':False}),
      (IDS[6],'Kalibrace — úplné dny',cal.get('complete_days',0),{}),
      (IDS[7],'Kalibrace — zlepšení chyby modelu',round(imp*100,2) if imp is not None else 'unknown',{'unit_of_measurement':'%','description':'Změna chyby modelu, nikoli úspora elektřiny.'}),
      (IDS[8],'FVE — korigovaná predikce zítra',up.get('corrected_kwh','unknown'),{'unit_of_measurement':'kWh','device_class':'energy','raw_kwh':up.get('raw_kwh')}),
      (IDS[9],'FVE — korekční faktor Solcast',pv.get('fallback_factor','unknown'),{'paired_forecasts':pv.get('paired_forecasts'),'status':pv.get('status')}),
      (IDS[10],'Baterie — odhad efektivní kapacity',bat.get('effective_capacity_kwh','unknown'),{'unit_of_measurement':'kWh','device_class':'energy','spec_usable_kwh':(bat.get('spec') or {}).get('usable_kwh')}),
      (IDS[11],'Baterie — odhad SoH',bat.get('soh_pct','unknown'),{'unit_of_measurement':'%','evidence_count':bat.get('capacity_evidence_count')}),
      (IDS[12],'EV — domácí nabíjení tento měsíc',ev.get('home_charge_kwh',0),{'unit_of_measurement':'kWh','device_class':'energy'}),
      (IDS[13],'EV — tarifní náklad tento měsíc',ev.get('tariff_equivalent_cost_czk','unknown'),{'unit_of_measurement':'Kč','definition':'wallbox kWh × cena ČEZ INDI v čase dodání'}),
      (IDS[14],'EV — vážená cena nabíjení',ev.get('weighted_price_czk_kwh','unknown'),{'unit_of_measurement':'Kč/kWh'}),
      (IDS[15],'Měřené spotřebiče',len(apps),{}),
      (IDS[16],'Cykly spotřebičů — 30 dní',cycles,{}),
      (IDS[17],'Energetické anomálie',len(a.get('anomalies') or []),{})
    ]
    environment=a.get('environment') or {};weather=a.get('weather') or {};quality=environment.get('quality') or {}
    temps=[{k:p.get(k) for k in ('entity_id','label','value','unit','quality','role','zone','area_name')} for p in environment.get('points',[]) if p.get('quantity')=='temperature']
    rows.extend([
        (IDS[18],'Telemetrie — počet čidel',quality.get('count','unknown'),{'counts_by_quantity':environment.get('counts_by_quantity',{}),'observed_at':environment.get('observed_at')}),
        (IDS[19],'Teploty — počet čidel',len(temps),{'sensors':temps}),
        (IDS[20],'Počasí — stav ověření',weather.get('status','unknown'),{'reference':weather.get('reference_entity'),'attempts':weather.get('attempts',[])}),
        (IDS[21],'Počasí — vyhodnocené páry',sum(m['n'] for m in weather.get('metrics',[])),{'metrics':weather.get('metrics',[])}),
        (IDS[22],'Telemetrie — dostupná čidla',quality.get('valid','unknown'),{'unclassified_temperatures':quality.get('unclassified_temperatures')})
    ])
    token=read_token();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    published=0;failed=[]
    for eid,name,value,extra in rows:
        value=_safe_state(value)
        attrs={'friendly_name':name,'mode':'observe_only','managed_by':'home-energy-coordinator-'+VERSION,
               'runtime':'Home Assistant app / Raspberry Pi 4','device_actions':0,**extra}
        if eid==IDS[0]:attrs.update(last_success=stamp,forecast_versions=status.get('forecast_versions'),
            signal_count=(status.get('quality') or {}).get('signal_count'),missing_required=(status.get('quality') or {}).get('missing_required'))
        try:
            with opener.open(request(eid,{'state':value,'attributes':attrs},cfg['ha_base_url'],token),timeout=5) as r:
                if r.status not in (200,201):raise RuntimeError('Publish failure')
            published+=1
        except Exception as e:
            failed.append({'entity_id':eid,'error_code':type(e).__name__})
    print(json.dumps({'published_status_entities':published,'failed_status_entities':failed,'device_actions':0}))
    if failed: raise RuntimeError('One or more monitoring states failed to publish')

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'publication':'failed','error_code':type(e).__name__}));raise SystemExit(1) from None

"""Compact derived observations and reproducible analytics."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json, math
from .core import instant, TZ
from .appliances import summarize as summarize_appliances
from .evmodel import analyze as analyze_ev
from .batterymodel import analyze as analyze_battery
from .pvmodel import calibrate as calibrate_pv, corrected_upcoming
from .pricing import TariffBook
from . import telemetry, weather


def ensure_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS appliance_obs(
      at TEXT NOT NULL, appliance_id TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL,
      power_w REAL, energy_kwh REAL, buy_price REAL,
      PRIMARY KEY(at,appliance_id));
    CREATE INDEX IF NOT EXISTS appliance_obs_id_at ON appliance_obs(appliance_id,at);
    CREATE TABLE IF NOT EXISTS ev_obs(
      at TEXT PRIMARY KEY, power_w REAL, energy_total_kwh REAL, soc REAL, buy_price REAL,
      odometer_km REAL, vehicle_energy_total_kwh REAL);
    CREATE TABLE IF NOT EXISTS battery_obs(
      at TEXT PRIMARY KEY, soc REAL, input_today_kwh REAL, output_today_kwh REAL, temp_c REAL);
    CREATE TABLE IF NOT EXISTS pv_obs(
      at TEXT PRIMARY KEY, energy_today_kwh REAL);
    """)


def _value(sample,key):
    s=sample.get("signals",{}).get(key,{})
    v=s.get("value")
    return v if s.get("quality")=="valid" and isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None


def record(store,sample):
    ensure_schema(store.db)
    telemetry.ensure_schema(store.db)
    at=sample["observed_at"];price=_value(sample,"buy_price")
    with store.db:
        for aid,a in sample.get("appliances",{}).items():
            store.db.execute("""INSERT OR REPLACE INTO appliance_obs
                (at,appliance_id,label,kind,power_w,energy_kwh,buy_price) VALUES(?,?,?,?,?,?,?)""",
                (at,aid,a.get("label",aid),a.get("kind","generic"),a.get("power_value"),a.get("energy_value"),price))
        store.db.execute("""INSERT OR REPLACE INTO ev_obs VALUES(?,?,?,?,?,?,?)""",
            (at,_value(sample,"ev_power"),_value(sample,"ev_energy_total"),_value(sample,"ev_soc"),price,
             _value(sample,"ev_odometer"),_value(sample,"ev_lifetime_energy")))
        store.db.execute("""INSERT OR REPLACE INTO battery_obs VALUES(?,?,?,?,?)""",
            (at,_value(sample,"battery_soc"),_value(sample,"battery_charge_energy_today"),
             _value(sample,"battery_discharge_energy_today"),_value(sample,"battery_temperature")))
        store.db.execute("""INSERT OR REPLACE INTO pv_obs VALUES(?,?)""",(at,_value(sample,"pv_energy_today")))
        for key,name in (("house_energy_today","house_kwh"),("pv_energy_today","pv_kwh"),
                         ("grid_import_energy_today","import_kwh"),("grid_export_energy_today","export_kwh")):
            v=_value(sample,key)
            if v is not None:
                store.db.execute("""INSERT INTO daily_observed VALUES(?,?,?,?,?)
                    ON CONFLICT(day,metric) DO UPDATE SET value=excluded.value,last_seen=excluded.last_seen
                    WHERE excluded.last_seen>=daily_observed.last_seen""",(sample['local_date'],name,v,at,at))


def _rows(db,sql,args=()):
    cur=db.execute(sql,args);names=[d[0] for d in cur.description]
    return [dict(zip(names,row)) for row in cur]


def _forecast_rows(db,cutoff):
    rows=db.execute("""SELECT v.entity,v.available_at,o.payload FROM versions v
      JOIN objects o ON o.hash=v.hash WHERE v.available_at>=?
      AND v.entity LIKE 'sensor.solcast_pv_forecast_forecast_%' ORDER BY v.available_at""",(cutoff,))
    from .store import unpack
    return [{"entity":a,"available_at":b,"payload":unpack(c)} for a,b,c in rows]


def _latest_forecasts(db):
    rows=db.execute("""SELECT v.entity,v.available_at,o.payload FROM versions v JOIN objects o ON o.hash=v.hash
      WHERE v.id IN (SELECT MAX(id) FROM versions WHERE entity LIKE 'sensor.solcast_pv_forecast_forecast_%' GROUP BY entity)""")
    from .store import unpack
    out={}
    for entity,available,payload in rows:
        if entity.endswith("_today"):name="today"
        elif entity.endswith("_tomorrow"):name="tomorrow"
        else:continue
        out[name]={**unpack(payload),"_available_at":available}
    return out


def _daily_overview(db,now):
    cutoff=(now.astimezone(TZ).date()-timedelta(days=30)).isoformat();daily=defaultdict(dict)
    for d,metric,value,first,last in db.execute('SELECT * FROM daily_observed WHERE day>=? ORDER BY day',(cutoff,)):
        daily[d].update({metric:value,'observed_from':first,'observed_until':last,
                         'coverage':'counter_readings_not_proof_of_full_day'})
    return [{'date':d,**v} for d,v in sorted(daily.items())]


def _tariffs(db,cutoff):
    from .store import unpack
    rows=db.execute("""SELECT v.available_at,o.payload FROM versions v JOIN objects o ON o.hash=v.hash
        WHERE v.entity='sensor.cez_indi_cenik' AND (v.available_at>=? OR v.id=(
          SELECT MAX(id) FROM versions WHERE entity='sensor.cez_indi_cenik' AND available_at<?))
        ORDER BY v.available_at""",(cutoff,cutoff))
    return TariffBook([{'available_at':a,'payload':unpack(p)} for a,p in rows])


def build(store,now=None,cfg=None):
    now=now or datetime.now(timezone.utc);ensure_schema(store.db)
    telemetry.ensure_schema(store.db);cfg=cfg or {}
    cutoff45=(now-timedelta(days=45)).isoformat();cutoff90=(now-timedelta(days=90)).isoformat()
    cutoff_year=(now-timedelta(days=366)).isoformat()
    tariff=_tariffs(store.db,cutoff_year)
    apps=_rows(store.db,"SELECT * FROM appliance_obs WHERE at>=? ORDER BY at",(cutoff45,))
    byapp=defaultdict(list)
    for r in apps:byapp[r["appliance_id"]].append(r)
    ev=analyze_ev(_rows(store.db,"SELECT * FROM ev_obs WHERE at>=? ORDER BY at",(cutoff_year,)),now,tariff)
    battery=analyze_battery(_rows(store.db,"SELECT * FROM battery_obs WHERE at>=? ORDER BY at",(cutoff90,)),now)
    pvrows=_rows(store.db,"SELECT * FROM pv_obs WHERE at>=? ORDER BY at",(cutoff45,))
    pvc=calibrate_pv(_forecast_rows(store.db,cutoff45),pvrows,now)
    pvc["upcoming"]=corrected_upcoming(_latest_forecasts(store.db),pvc,now)
    appliances=summarize_appliances(byapp,now,tariff,cfg.get("appliance_overrides",{}))
    anomalies=[]
    for aid,a in appliances.items():
        tr=a.get("trend_7d_vs_prev7_pct")
        if tr is not None and abs(tr)>=35 and a.get("energy_7d_kwh",0)>=0.5:
            anomalies.append({"type":"appliance_trend","appliance_id":aid,"label":a["label"],"change_pct":tr})
    return {"schema_version":1,"calculated_at":now.isoformat(),"mode":"observe_only",
        "daily":_daily_overview(store.db,now),"pv":pvc,"battery":battery,"ev":ev,
        "appliances":appliances,"anomalies":anomalies,
        "environment":telemetry.summary(store,now),
        "weather":weather.summary(store,now,cfg.get('weather_reference','sensor.current_outdoor_temperature_bt1_30002')),
        "versions":{"software":"0.4.0","pricing":"interval_split_v1","pv":"hourly_holdout_v1"},
        "quality":{"derived_from_minute_observations":True,"control_actions":0}}

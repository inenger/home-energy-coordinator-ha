"""Relace má předat jen vlastní stavy; veškeré změny jsou pouze virtuální."""
import copy,json,sqlite3,tempfile,unittest,random,ast
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch,MagicMock
from energy import control_journal as c,priority,instant_fill as f,publish_status,priority_observer
from energy.store import Store,unpack
from test_instant_fill import points,SESSION
from test_night import state

AT='2026-01-15T02:00:00+00:00'
END='2026-01-15T04:00:00+00:00'

def states(at=AT,disabled=()):
    ss=[state(e,'off' if e in disabled else 'on',at) for e in c.AUTOMATIONS]
    ss+=[state(c.FLAG,'off',at),state(c.CURRENT,30,at),state(c.MODE,'Back Up Mode',at),state(c.FORCE,'Stop Charge and Discharge',at),state('sensor.solax_api_charge_power_total',11040,at)]
    for s in ss:
        if s['entity_id']==c.CURRENT:s['attributes'].update(min=0,max=30,step=.1,unit_of_measurement='A')
        if s['entity_id']==c.MODE:s['attributes']['options']=['Back Up Mode','Self Use Mode','Manual Mode']
        if s['entity_id']==c.FORCE:s['attributes']['options']=['Stop Charge and Discharge','Force Charge','Force Discharge']
    return ss

def result(at=AT,base=(460,920,230)):
    s=f.allocate(points(base),at,SESSION,11,'ev')
    return {'at':at,'selected':s,'actual':{'battery_v':230,'battery_a':0,'ev_w':11040},'mode':'observe_only','device_actions':0}

def patch_value(ss,eid,value,at=None,manual=False):
    for s in ss:
        if s['entity_id']==eid:
            s['state']=str(value)
            if at:s['last_updated']=at;s['last_reported']=at
            if manual:s['context']={'user_id':'synthetic'}

class ControlJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'e.sqlite';self.store=Store(self.path)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def events(self):return [unpack(p) for p, in self.store.db.execute('select payload from control_events order by id')]
    def run_at(self,at=AT,ss=None,r=None):return c.observe(self.store,ss if ss is not None else states(at),r if r is not None else result(at))
    def test_outside_window_only_preview_and_no_fake_session(self):
        v=self.run_at(END)
        self.assertEqual(v['status'],'waiting_for_window');self.assertEqual(v['recent_events'],[])
        self.assertEqual(len(v['preview']),len(c.MANAGED))
    def test_snapshot_precedes_virtual_writes_and_inputs_not_mutated(self):
        ss=states();before=copy.deepcopy(ss);r=result();original=copy.deepcopy(r);v=self.run_at(ss=ss,r=r)
        self.assertEqual(ss,before);self.assertEqual(r,original)
        ev=self.events();self.assertEqual(ev[0]['kind'],'snapshot_saved')
        keys=[x['entity_id'] for x in ev]
        self.assertLess(keys.index(c.CURRENT),keys.index(c.MODE));self.assertLess(keys.index(c.MODE),keys.index(c.FORCE))
        self.assertEqual(v['session']['owned'][c.CURRENT]['before'],30)
        self.assertAlmostEqual(v['recent_samples'][0]['proposed_dc_a'],13.3)
        self.assertTrue(all(x['device_actions']==0 and not x['applied_to_control'] for x in ev))
    def test_repeated_sample_and_same_setting_deduplicated(self):
        self.run_at();n=len(self.events());self.run_at();self.assertEqual(len(self.events()),n)
        self.run_at('2026-01-15T02:00:15+00:00');self.assertEqual(len(self.events()),n)
        self.assertEqual(self.store.db.execute('select count(*) from control_samples').fetchone()[0],2)
    def test_dynamic_current_decrease_and_increase(self):
        self.run_at();at='2026-01-15T02:00:15+00:00';v=self.run_at(at,r=result(at,(460,1500,230)))
        self.assertLess(v['recent_samples'][0]['proposed_dc_a'],13.3)
        at='2026-01-15T02:00:30+00:00';v=self.run_at(at,r=result(at,(460,500,230)))
        self.assertGreater(v['recent_samples'][0]['proposed_dc_a'],13.3)
        self.assertGreater(v['session']['counts']['current_increases'],0)
        self.assertGreater(v['session']['counts']['current_decreases'],0)
    def test_missing_phase_waits_then_takes_fresh_snapshot(self):
        r=result();r['selected']['battery_ac_w']=None;r['selected']['reason']='invalid_phase_input'
        v=self.run_at(r=r);self.assertEqual(v['status'],'awaiting_inputs');self.assertFalse(v['session']['owned'])
        at='2026-01-15T02:00:15+00:00';ss=states(at);patch_value(ss,c.CURRENT,25)
        v=self.run_at(at,ss);self.assertEqual(v['status'],'active');self.assertEqual(v['session']['owned'][c.CURRENT]['before'],25)
    def test_missing_data_during_charge_proposes_stop_not_old_limit(self):
        self.run_at();at='2026-01-15T02:00:15+00:00';r=result(at);r['selected']['battery_ac_w']=None
        v=self.run_at(at,r=r);self.assertIsNone(v['recent_samples'][0]['proposed_dc_a'])
        self.assertEqual(v['recent_samples'][0]['virtual_limit_dc_a'],0)
        self.assertEqual(v['session']['owned'][c.FORCE]['virtual'],'Stop Charge and Discharge')
    def test_restart_restores_only_enabled_automations_and_order(self):
        ss=states(disabled=(c.AUTOMATIONS[0],));self.run_at(ss=ss)
        self.store.close();self.store=Store(self.path)
        endstates=states(END,disabled=(c.AUTOMATIONS[0],));patch_value(endstates,'sensor.solax_api_charge_power_total',0)
        v=self.run_at(END,endstates);r=v['session'];self.assertTrue(r['exact_restore'])
        self.assertEqual(r['owned'][c.AUTOMATIONS[0]]['virtual'],'off')
        events=self.events();stops=[i for i,x in enumerate(events) if x['kind']=='would_stop_charge'];restores=[i for i,x in enumerate(events) if x['kind']=='would_restore']
        self.assertLess(stops[-1],restores[0]);self.assertEqual(events[-1]['kind'],'window_closed')
        n=len(events);self.run_at('2026-01-15T04:01:00+00:00',endstates);self.assertEqual(len(self.events()),n)
    def test_ev_still_charging_handoff_not_blind_flag_restore(self):
        self.run_at();v=self.run_at(END);r=v['session']
        self.assertEqual(r['restoration_status'],'conditional_handoff');self.assertFalse(r['exact_restore'])
        row=next(x for x in r['restoration'] if x['entity_id']==c.FLAG);self.assertEqual(row['virtual_after'],'on')
    def test_missing_ev_at_end_is_not_successful_restore(self):
        self.run_at();ss=states(END);patch_value(ss,'sensor.solax_api_charge_power_total','unavailable');r=self.run_at(END,ss)['session']
        self.assertEqual(r['restoration_status'],'restore_pending');self.assertIsNone(r['closed_at']);self.assertGreater(r['unresolved_count'],0)
    def test_manual_change_conflicts_suspend_and_skip_restore(self):
        self.run_at();at='2026-01-15T02:10:00+00:00';ss=states(at);patch_value(ss,c.CURRENT,9,at,True)
        r=self.run_at(at,ss)['session'];self.assertTrue(r['suspended']);self.assertIn('conflict',r['owned'][c.CURRENT])
        end=states(END);patch_value(end,c.CURRENT,9,at,True);r=self.run_at(END,end)['session']
        row=next(x for x in r['restoration'] if x['entity_id']==c.CURRENT)
        self.assertEqual(row['status'],'unresolved_external_change');self.assertEqual(row['observed_actual'],9)
        self.assertFalse(r['exact_restore'])
    def test_missed_end_processed_late_without_backdating(self):
        self.run_at();at='2026-01-15T07:00:00+00:00';self.run_at(at)
        end=self.events()[-1];self.assertEqual(end['at'],at);self.assertEqual(end['scheduled_at'],END)
    def test_late_start_and_gap_are_explicit(self):
        at='2026-01-15T03:00:00+00:00';v=self.run_at(at);self.assertEqual(v['session']['late_start_seconds'],3600)
        self.run_at('2026-01-15T03:03:00+00:00');self.assertIn('sampling_gap',[x['kind'] for x in self.events()])
    def test_force_charge_owned_by_other_controller_blocks_takeover(self):
        ss=states();patch_value(ss,c.FORCE,'Force Charge');v=self.run_at(ss=ss)
        self.assertFalse(v['session']['owned']);self.assertIn('unowned_manual_charge',v['session']['blocked_reason'])
    def test_invalid_register_and_unexpressible_ev_request_block(self):
        ss=states();next(x for x in ss if x['entity_id']==c.CURRENT)['attributes']['min']=1
        self.assertFalse(self.run_at(ss=ss)['session']['owned'])
        r=result();r['selected']['ev_reallocated_w']=2000
        self.assertEqual(c.current_proposal(r,c.read(states())[c.CURRENT])[1],'requires_ev_control_not_implemented')
    def test_round_down_never_increases_phase_power(self):
        rng=random.Random(67);meta=c.read(states())[c.CURRENT]
        for _ in range(500):
            r=result(base=tuple(rng.uniform(100,2000) for i in range(3)));amps,reason=c.current_proposal(r,meta)
            if amps is None:continue
            self.assertGreaterEqual(amps,0);self.assertLessEqual(amps,30)
            self.assertAlmostEqual(amps*10,round(amps*10))
            self.assertLessEqual(amps*230/.9,r['selected']['battery_ac_w']+1e-6)
    def test_observed_automatic_convergence_not_manual_conflict(self):
        self.run_at();at='2026-01-15T02:01:00+00:00';ss=states(at);patch_value(ss,c.FLAG,'on',at)
        r=self.run_at(at,ss)['session'];self.assertNotIn('conflict',r['owned'][c.FLAG])
    def test_publisher_uses_only_new_allowlisted_monitor(self):
        v=self.run_at();r=result();r.update(active=True,priority='ev',control_journal=v)
        opener=MagicMock();opener.open.return_value.__enter__.return_value.status=201
        with patch.object(publish_status.urllib.request,'build_opener',return_value=opener),patch.object(publish_status,'read_token',return_value='synthetic'):
            publish_status.publish_priority(r,{'ha_base_url':'http://example.test'})
        reqs=[call.args[0] for call in opener.open.call_args_list]
        self.assertTrue(any(x.full_url.endswith('/'+c.SENSOR) for x in reqs))
        self.assertTrue(all(x.full_url.rsplit('/',1)[-1] in publish_status.IDS for x in reqs))
        self.assertFalse(any('/api/services/' in x.full_url for x in reqs))
    def test_no_device_adapter_import_or_service_call(self):
        tree=ast.parse(Path(c.__file__).read_text());imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertNotIn('collector',imports);self.assertNotIn('urllib.request',imports)
        self.assertNotIn('callService',Path(c.__file__).read_text())

    def test_missing_restore_state_retried_after_recovery(self):
        self.run_at();ss=states(END);patch_value(ss,c.MODE,'unavailable');patch_value(ss,'sensor.solax_api_charge_power_total',0)
        r=self.run_at(END,ss)['session'];self.assertEqual(r['status'],'restore_pending')
        at='2026-01-15T04:01:00+00:00';ss=states(at);patch_value(ss,'sensor.solax_api_charge_power_total',0)
        r=self.run_at(at,ss)['session'];self.assertEqual(r['restoration_status'],'would_restore_all');self.assertTrue(r['exact_restore'])
    def test_failure_stops_virtual_charge_then_recovers(self):
        self.run_at();v=c.record_failure(self.store,'2026-01-15T02:00:30+00:00','TimeoutError')
        self.assertEqual(v['status'],'waiting_for_recovery');self.assertEqual(v['session']['owned'][c.FORCE]['virtual'],'Stop Charge and Discharge')
        at='2026-01-15T02:01:00+00:00';r=self.run_at(at)['session'];self.assertEqual(r['status'],'active')
        self.assertEqual(r['owned'][c.FORCE]['virtual'],'Force Charge')
        self.assertEqual(r['statistics']['covered_s'],0)
    def test_failure_at_end_does_not_claim_restored(self):
        self.run_at();v=c.record_failure(self.store,END,'TimeoutError')
        self.assertEqual(v['session']['status'],'restore_pending');self.assertIsNone(v['session']['closed_at'])
    def test_pending_prior_night_prevents_second_virtual_owner(self):
        self.run_at();c.record_failure(self.store,END,'TimeoutError')
        at='2026-01-16T02:00:00+00:00';ss=states(at);patch_value(ss,c.MODE,'unavailable')
        self.run_at(at,ss)
        self.assertEqual(self.store.db.execute('select count(*) from control_sessions').fetchone()[0],1)

    def test_repeated_missing_restore_does_not_churn_current(self):
        self.run_at();ss=states(END);patch_value(ss,c.MODE,'unavailable');patch_value(ss,'sensor.solax_api_charge_power_total',0)
        self.run_at(END,ss);n=len(self.events())
        self.run_at('2026-01-15T04:01:00+00:00',ss);self.assertEqual(len(self.events()),n)
    def test_full_night_series_and_exact_virtual_restoration(self):
        start=datetime.fromisoformat(AT)
        for i in range(480):
            at=(start+timedelta(seconds=i*15)).isoformat();self.run_at(at,r=result(at,(460,1500 if i%40<20 else 500,230)))
        ss=states(END);patch_value(ss,'sensor.solax_api_charge_power_total',0)
        v=self.run_at(END,ss);r=v['session']
        self.assertTrue(r['exact_restore']);self.assertEqual(r['statistics']['covered_s'],7200)
        self.assertEqual(r['statistics']['model_exceedance_samples'],0)
        self.assertEqual(self.store.db.execute('select count(*) from control_samples').fetchone()[0],480)
        self.assertTrue(all(x['before']==x['virtual_after'] for x in r['restoration']))
    def test_failure_monitor_contains_control_failure_without_actions(self):
        self.run_at();view=c.record_failure(self.store,'2026-01-15T02:00:30+00:00','TimeoutError')
        r=priority_observer.failure_result('2026-01-15T02:00:30+00:00',TimeoutError(),AT);r['control_journal']=view
        opener=MagicMock();opener.open.return_value.__enter__.return_value.status=201
        with patch.object(publish_status.urllib.request,'build_opener',return_value=opener),patch.object(publish_status,'read_token',return_value='synthetic'):
            publish_status.publish_priority_failure(r,{'ha_base_url':'http://example.test'})
        req=next(x.args[0] for x in opener.open.call_args_list if x.args[0].full_url.endswith('/'+c.SENSOR))
        d=json.loads(req.data);self.assertEqual(d['state'],'waiting_for_recovery');self.assertEqual(d['attributes']['device_actions'],0)

    def test_initial_zero_charge_keeps_virtual_battery_idle_until_restore(self):
        r=result();r['selected']['battery_ac_w']=0;r['selected']['reason']='target_reached'
        v=self.run_at(r=r);own=v['session']['owned']
        self.assertEqual(own[c.CURRENT]['virtual'],0)
        self.assertEqual(own[c.MODE]['virtual'],'Manual Mode')
        self.assertEqual(own[c.FORCE]['virtual'],'Stop Charge and Discharge')
        ss=states(END);patch_value(ss,'sensor.solax_api_charge_power_total',0)
        v=self.run_at(END,ss);self.assertTrue(v['session']['exact_restore'])
        self.assertEqual(v['session']['owned'][c.MODE]['virtual'],'Back Up Mode')

    def test_normal_operating_status_is_distinct_and_phase_conflict_stops_then_recovers(self):
        # Syntetický úplný průchod: provozní stav není nastavovaná strategie.
        ss=states();ss.append(state('sensor.solax_run_mode','Normal Mode',AT))
        view=self.run_at(ss=ss)
        self.assertEqual(view['session']['snapshot'][c.MODE]['value'],'Back Up Mode')
        self.assertEqual(view['session']['owned'][c.MODE]['virtual'],'Manual Mode')
        self.assertFalse(any(e['entity_id']=='sensor.solax_run_mode' for e in self.events()))
        at='2026-01-15T02:00:15+00:00';p=points();p['grid_l2_w']['value']=-4600;p['grid_l2_a']['value']=16
        selected=f.allocate(p,at,SESSION,11,'ev')
        self.assertEqual(selected['reason'],'invalid_phase_input');self.assertIn('grid_l2_a',selected['missing_inputs'])
        self.assertTrue(all(x['quality']=='valid' for x in p.values()))
        r=result(at);r['selected']=selected;view=self.run_at(at,r=r)
        self.assertEqual(view['session']['owned'][c.CURRENT]['virtual'],0)
        self.assertEqual(view['session']['owned'][c.FORCE]['virtual'],'Stop Charge and Discharge')
        at='2026-01-15T02:00:30+00:00';view=self.run_at(at)
        self.assertGreater(view['session']['owned'][c.CURRENT]['virtual'],0)
        self.assertEqual(view['session']['owned'][c.FORCE]['virtual'],'Force Charge')
        self.assertTrue(all(e['device_actions']==0 for e in self.events()))

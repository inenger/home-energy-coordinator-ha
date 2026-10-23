"""Regression of stale REST serialization; do not turn a read into a heartbeat."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from energy.collector import ReadOnlyHA
from energy import night,priority,priority_audit as audit,automation_context,soc_runtime
from energy.store import Store
from test_priority import inputs,points,AT
from test_priority_audit import result


class LiveReportsTests(unittest.TestCase):
    def snapshot(self,reported=AT):
        return [{'entity_id':night.IDS['ev_w'],'state':'0','attributes':{'unit_of_measurement':'W'},
                 'last_reported':reported,'last_updated':'2026-10-22T16:00:00+00:00',
                 'report_source':'ha_live_state_template'}]

    def test_query_reads_real_state_report_and_never_replaces_it_with_query_time(self):
        client=ReadOnlyHA()
        with patch.object(client,'get',return_value=self.snapshot()),patch.object(client,'_query',return_value=json.dumps(self.snapshot())) as query:
            states=client.priority_states()
        self.assertEqual(query.call_args.args[0],'/api/template')
        template=query.call_args.args[1]['template']
        self.assertIn('s.last_reported.isoformat()',template)
        self.assertNotIn('now()',template)
        self.assertNotIn('services',template)
        self.assertEqual(json.loads(template.split(' = ',1)[1].split(' %}',1)[0]),sorted(set(night.IDS.values())|set(priority.EXTRA.values())|set(automation_context.ENTITY_IDS)|set(soc_runtime.IDS.values())))
        p=night.point(states[0],AT)
        self.assertEqual(p['age_seconds'],0)
        self.assertTrue(night.valid({'ev_w':p},'ev_w'))

    def test_successful_query_with_stale_report_still_blocks_and_unknown_is_not_zero(self):
        client=ReadOnlyHA()
        with patch.object(client,'get',return_value=self.snapshot()),patch.object(client,'_query',return_value=json.dumps(self.snapshot('2026-10-22T16:00:00+00:00'))):
            p=night.point(client.priority_states()[0],AT)
        self.assertFalse(night.valid({'ev_w':p},'ev_w'))
        s=self.snapshot()[0];s['state']='unavailable'
        self.assertIsNone(night.point(s,AT)['value'])

    def test_missing_or_unexpected_entities_and_query_errors_fail_closed(self):
        client=ReadOnlyHA()
        for data in ({},self.snapshot()*2,[{**self.snapshot()[0],'entity_id':'switch.unknown'}]):
            with patch.object(client,'get',return_value=self.snapshot()),patch.object(client,'_query',return_value=json.dumps(data)):
                self.assertRaises(ValueError,client.priority_states)
        with patch.object(client,'get',return_value=self.snapshot()),patch.object(client,'_query',side_effect=TimeoutError):self.assertRaises(TimeoutError,client.priority_states)
        with patch.object(client,'get',return_value=self.snapshot()),patch.object(client,'_query',return_value='[]'):self.assertEqual(client.priority_states(),[])

    def test_racing_state_or_attribute_change_is_omitted_not_joined(self):
        client=ReadOnlyHA();rest=self.snapshot()
        for change in ({'state':'1000'},{'last_updated':AT}):
            live=[{**rest[0],**change}]
            with patch.object(client,'get',return_value=rest),patch.object(client,'_query',return_value=json.dumps(live)):
                self.assertEqual(client.priority_states(),[])

    def test_feasible_demand_has_no_artificial_rounding_deferral(self):
        pp=points(inputs());pp['ev_w']['value']=11379
        for i in (1,2,3):pp[f'ev_l{i}_w']['value']=3793
        r=priority.allocate(pp,AT,{'forecast_kwh':23.9,'target_soc_pct':0},11,'ev')
        self.assertEqual(r['ev_ac_w'],11379)
        self.assertEqual(r['ev_reallocated_w'],0)
        self.assertEqual(r['ev_allocation_mode'],'follow_measured_demand')

    def test_following_demand_deduplicates_noise_but_keeps_stop_limit_and_block(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'e.sqlite')
            for i,w in enumerate([11200,11300,11400,11300]):
                r=result(f'2026-10-23T01:00:{i*15:02}+00:00',w=w)
                r['selected'].update(ev_allocation_mode='follow_measured_demand',ev_setting_limit_a=16)
                audit.journal(st,r)
            self.assertEqual(audit.command_summary(st,AT)['total_records'],1)
            r['at']='2026-10-23T01:01:00+00:00';r['selected']['ev_setting_limit_a']=15;audit.journal(st,r)
            r['at']='2026-10-23T01:01:15+00:00';r['selected'].update(ev_allocation_mode='idle',ev_ac_w=0);audit.journal(st,r)
            r['at']='2026-10-23T01:01:30+00:00';r['selected'].update(ev_ac_w=None,reason='invalid_ev_input');audit.journal(st,r)
            self.assertEqual(audit.command_summary(st,AT)['total_records'],4)
            st.close()

    def test_battery_can_use_idle_ev_window_and_stale_soc_still_rejected(self):
        pp=points(inputs(soc=11));pp['ev_w']['value']=0
        for i in (1,2,3):pp[f'ev_l{i}_w']['value']=0
        r=priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},11,'battery')
        self.assertGreater(r['battery_ac_w'],0);self.assertEqual(r['ev_ac_w'],0)
        pp['ev_w']['age_seconds']=100
        self.assertIsNone(priority.allocate(pp,AT,{'forecast_kwh':8,'target_soc_pct':80},11,'battery')['battery_ac_w'])

    def test_no_battery_request_does_not_prove_a_priority_winner(self):
        self.assertEqual(priority.comparison_context({'target_soc_pct':0}),'battery_no_request')
        self.assertEqual(priority.comparison_context(None),'missing_forecast')
        self.assertEqual(priority.comparison_context({'target_soc_pct':80}),'battery_target_present')

import tempfile,unittest
from pathlib import Path
from energy import night,priority,priority_audit,automation_context
from energy.store import Store,pack
from test_priority import inputs,points,AT


class Reserve30Tests(unittest.TestCase):
    def test_new_boundaries_match_displayed_rules(self):
        for f,target in [(0,90),(4.999,90),(5,80),(9.999,80),(10,70),(14.999,70),(15,30),(23.903,30),(30,30),(99,30)]:
            self.assertEqual(night.target_for(f),target)
            rules=[r for r in priority_audit.RULES if f>=r['min_kwh'] and (r['max_kwh'] is None or f<r['max_kwh'])]
            self.assertEqual(rules[0]['target_soc_pct'],target)

    def test_30pct_target_charges_below_and_never_discharges_above(self):
        pp=points(inputs())
        for forecast in (15,23.903,30,50):
            session={'forecast_kwh':forecast,'target_soc_pct':night.target_for(forecast)}
            for choice in ('ev','battery'):
                below=priority.allocate(pp,AT,session,11,choice)
                self.assertGreater(below['battery_ac_w'],0)
                self.assertLessEqual(below['ev_ac_w'],pp['ev_w']['value'])
                above=priority.allocate(pp,AT,session,35,choice)
                self.assertEqual(above['battery_ac_w'],0)
                self.assertEqual(above['reason'],'target_reached')
                self.assertEqual(below['forbid_discharge'],forecast<30)

    def test_existing_frozen_session_keeps_its_original_target(self):
        with tempfile.TemporaryDirectory() as td:
            st=Store(Path(td)/'x.sqlite');night.ensure_schema(st.db);priority.schema(st.db)
            original={'day':'2026-10-23','status':'captured','forecast_kwh':23.903,'target_soc_pct':0,'policy_version':'0.5.7'}
            with st.db:st.db.execute('INSERT INTO night_sessions VALUES(?,?)',('2026-10-23',pack(original)))
            self.assertEqual(priority.effective_session(st,'2026-10-23',AT,points(inputs())),original)
            st.close()

    def test_automation_context_reports_missing_as_missing_and_never_applies_plan(self):
        eid=automation_context.GROUPS[0]['ids'][0]
        r=automation_context.snapshot([{'entity_id':eid,'state':'on','attributes':{'friendly_name':'EV priorita'}}],AT)
        self.assertFalse(r['applied_to_control']);self.assertEqual(r['device_actions'],0)
        self.assertEqual(r['groups'][0]['automations'][0]['state'],'on')
        self.assertEqual(r['groups'][0]['automations'][1]['state'],'missing')
        self.assertTrue(all(x['state']=='missing' for x in r['flags']))

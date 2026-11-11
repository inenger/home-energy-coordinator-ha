import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

let Card;
const context={HTMLElement:class{
  attachShadow(){this.shadowRoot={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>({})};}
},localStorage:{getItem:()=>null},window:{},requestAnimationFrame:()=>{},
customElements:{get:()=>Card,define:(_,value)=>{Card=value;}},console,Date,Intl};
vm.runInNewContext(fs.readFileSync(new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url),'utf8'),context);
const card=new Card();
card._hass={states:{'sensor.nocni_stinovy_soc_optimalizace':{attributes:{
  status:'partial_shadow_plan',target_soc_pct:30,day:'2026-01-15',issued_at:new Date().toISOString(),
  attainable_soc_05:{central:65,low_pv_high_load:60,high_pv_low_load:70},power_budget:{status:"empirical_shadow_candidate",reserve_a:[.3,.4,.5],power_factor:[.99,.99,.99]},horizon_complete:true,ev_deficit_ac_kwh:{central:22},assumptions:{},profile:[],candidates:[],
  priority_alternatives:{ev:{target_soc_pct:30,ev_deficit_ac_kwh:{central:22}},battery:{target_soc_pct:70,ev_deficit_ac_kwh:{central:28}}}
}}},callService(){throw Error('Rendering must not call services');}};
card.lastEntity={attributes:{at:new Date().toISOString(),actual:{inverter_run_mode:'Normal Mode',inverter_mode:'Back Up Mode'},
  comparison_status:'no_coverage',comparison_context:'invalid_soc_plan',active:true}};

// Acceptance: malformed optional date never aborts real card.render.
card.render();const previous=card.shadowRoot.innerHTML;assert(previous.length>0);
const optimizer=card._hass.states['sensor.nocni_stinovy_soc_optimalizace'].attributes;
for(const value of ['unknown','unavailable','invalid-date']){
 optimizer.sunrise=value;
 assert.doesNotThrow(()=>card.render());
 assert.match(card.shadowRoot.innerHTML,/Východ slunce/);
}
optimizer.sunrise='2026-11-11T07:00:00+01:00';
assert.doesNotThrow(()=>card.render());
assert.match(card.shadowRoot.innerHTML,/07:00/);
console.log('PASS UI-01: unknown/malformed and Prague offset render');

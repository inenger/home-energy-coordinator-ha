import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
let Card;
const context={HTMLElement:class{attachShadow(){this.shadowRoot={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>({})};}},
localStorage:{getItem:()=>null},window:{},requestAnimationFrame:()=>{},
customElements:{get:()=>Card,define:(_,value)=>{Card=value;}},console,Date,Intl};
vm.runInNewContext(fs.readFileSync(new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url),'utf8'),context);
const card=new Card();
card._hass={states:{'sensor.nocni_stinovy_soc_optimalizace':{attributes:{
  status:'partial_shadow_plan',target_soc_pct:30,day:'2026-11-12',issued_at:new Date().toISOString(),
  attainable_soc_05:{central:65},power_budget:{status:'empirical_shadow_candidate',reserve_a:[.5,.5,.5],power_factor:[1,1,1]},
  horizon_complete:true,ev_deficit_ac_kwh:{central:22},assumptions:{},profile:[],candidates:[],priority_alternatives:{}
}}},callService(){throw Error('Not permitted')}};
card.lastEntity={attributes:{at:new Date().toISOString(),actual:{},active:false,comparison_status:'no_coverage',comparison_context:'invalid_soc_plan'}};
assert.doesNotThrow(()=>card.render());
const before=card.shadowRoot.innerHTML;
assert.ok(before.length>100);
for(const bad of ['unknown','unavailable','bad-input']){
 card.lastEntity.attributes.at=bad;
 let error;
 try{card.render();}catch(e){error=e}
 console.log('MALFORMED_PLAN_TIME',bad,'thrown',error?.name||'none','old_dom_length',card.shadowRoot.innerHTML.length);
 assert.ok(error instanceof RangeError || error?.name==='RangeError',
   'Without a guard, real card.render should throw on malformed plan timestamp');
}
card.lastEntity.attributes.at=new Date().toISOString();
assert.doesNotThrow(()=>card.render());
console.log('CONFIRMED UI-02 COUNTEREXAMPLE: invalid plan timestamp aborts full render; normal date recovers');

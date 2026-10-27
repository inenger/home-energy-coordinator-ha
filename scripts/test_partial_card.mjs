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
const panel=card.optimizerPanel({});
assert.match(panel,/Částečný plán/);
assert.match(panel,/22 kWh/);
assert.match(panel,/Baterie první: cíl 70/);
assert.match(panel,/Dosažitelné SOC/);
assert.match(panel,/při vyšší spotřebě 60/);
assert.match(panel,/Přípojka 3×25 A/);
assert.match(panel,/0[,.]3 \/ 0[,.]4 \/ 0[,.]5/);
card.render();
assert.match(card.shadowRoot.innerHTML,/sensor.solax_run_mode\]: Normal Mode/);
assert.match(card.shadowRoot.innerHTML,/select.solax_charger_use_mode\]: Back Up Mode/);
assert.match(card.shadowRoot.innerHTML,/Nelze vyhodnotit/);
console.log('PASS: partial demand, distinct inverter states, unknown model coverage, no services');

card.lastEntity.attributes.allocation_policy='instant-max-fill-v1';
card.render();
assert.match(card.shadowRoot.innerHTML,/Strop stínového dobíjení/);
assert.match(card.shadowRoot.innerHTML,/ekonomický cíl je poradní/);
assert.match(card.shadowRoot.innerHTML,/Odstup.*25 A/);
console.log('PASS: instant max-fill is separate from economic target');

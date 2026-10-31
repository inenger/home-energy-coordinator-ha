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

card.lastEntity.attributes.collection_health={status:'degraded',last_successful_collection_at:new Date().toISOString(),summary_errors:[{day:'2026-01-15',error_code:'ValueError'}]};
card.render();
assert.match(card.shadowRoot.innerHTML,/Sběr pokračuje · chyba souhrnu noci/);
assert.match(card.shadowRoot.innerHTML,/Poslední úspěšný sběr/);
assert.match(card.shadowRoot.innerHTML,/2026-01-15/);
card.lastEntity.attributes.collection_health={status:'failed',error_code:'ValueError',last_successful_collection_at:'2026-01-15T03:00:00Z'};
card.lastEntity.attributes.at='2026-01-15T03:00:00Z';
card.lastEntity.attributes.selected={reason:'ev_first',ev_ac_w:123456,battery_ac_w:654321};
card.render();
assert.match(card.shadowRoot.innerHTML,/Sběr selhal · návrhy nejsou dostupné/);
assert.equal(card.lastEntity.attributes.selected.battery_ac_w,654321);
assert.doesNotMatch(card.shadowRoot.innerHTML,/654[,.]32 kW/);
console.log('PASS: summary error, last success, stale powers hidden without mutating HA');

const controlEntity='sensor.nocni_stinovy_ridici_denik';
const controlEvent={id:1,day:'2026-01-15',at:'2026-01-15T02:00:00Z',kind:'would_set',entity_id:'number.solax_battery_charge_max_current',label:'<script>unsafe</script>',before:30,after:13.3,reason:'ev_first',decision:{binding_phase:2,battery_ac_w:3400}};
const controlSession={day:'2026-01-15',status:'closed',event_count:1,counts:{current_increases:1,current_decreases:2,stops:1},restoration_status:'would_restore_all',snapshot:{x:{value:30,label:'Baterie'}},restoration:[{label:'Baterie',before:30,virtual_after:30,observed_actual:30,status:'would_restore'}]};
card._hass.states[controlEntity]={attributes:{observed_at:new Date().toISOString(),next_window_start:'2026-01-16T02:00:00Z',session:controlSession,sessions:[{day:'2026-01-15'}],recent_events:[controlEvent],recent_samples:[]}};
card.render();
assert.match(card.shadowRoot.innerHTML,/Řídicí deník/);
assert.match(card.shadowRoot.innerHTML,/VIRTUÁLNÍ ZÁSAHY/);
assert.match(card.shadowRoot.innerHTML,/Návrat a předání/);
assert.match(card.shadowRoot.innerHTML,/Skutečný HA údaj při předání/);
assert.match(card.shadowRoot.innerHTML,/&lt;script&gt;unsafe/);
assert.doesNotMatch(card.shadowRoot.innerHTML,/<script>unsafe/);
let historyRequests=0;
card._hass.callApi=async(method,url)=>{assert.equal(method,'GET');assert.match(url,/filter_entity_id=sensor.nocni_stinovy_ridici_denik/);assert.match(url,/significant_changes_only=0/);assert.doesNotMatch(url,/minimal_response/);historyRequests++;return [[{entity_id:controlEntity,attributes:{session:controlSession,recent_events:[controlEvent],recent_samples:[{day:'2026-01-15',at:'2026-01-15T02:00:00Z',virtual_limit_dc_a:13.3,actual_limit_dc_a:30,actual_charge_dc_a:0}]}},{attributes:{recent_events:[controlEvent],recent_samples:[{day:'2026-01-15',at:'2026-01-15T02:00:15Z',virtual_limit_dc_a:10,actual_limit_dc_a:30,actual_charge_dc_a:0}]}}]];};
await card.loadControlHistory(true);
assert.equal(card.controlCache['2026-01-15'].events.length,1);
assert.equal(card.controlCache['2026-01-15'].samples.length,2);
assert.match(card.shadowRoot.innerHTML,/Stínové nastavení, skutečné nastavení/);
const n=historyRequests;await card.loadControlHistory();assert.equal(historyRequests,n);
card.controlDay='bad/path';await card.loadControlHistory(true);assert.equal(historyRequests,n);
console.log('PASS: control takeover/restore UI, escaping, DC graph, GET-only history deduplication');

// Retrospective chunks have their own authenticated archive; live history remains separate.
const archive={day:'2026-01-14',archive_id:'a'.repeat(64),recorded_from:'2026-01-15T10:00:00Z',recorded_to:'2026-01-15T10:02:00Z',event_count:1,sample_count:2,chunk_count:2};
card.setConfig({control_archives:[archive,{day:'bad/path'}]});card.controlDay=archive.day;
const retrospective={...controlSession,day:archive.day,provenance:{kind:'retrospective_held_recorder_states',reconstructed_at:archive.recorded_from,limitations:['Heartbeat <unknown>']}};
const ae={...controlEvent,day:archive.day},as=[{day:archive.day,at:'2026-01-14T02:00:00Z',virtual_limit_dc_a:20.9},{day:archive.day,at:'2026-01-14T02:00:15Z',virtual_limit_dc_a:21.2}];
const chunks=[{archive_id:archive.archive_id,day:archive.day,kind:'retrospective_held_recorder_states',chunk_index:0,session:retrospective,events:[ae]},{archive_id:archive.archive_id,day:archive.day,kind:'retrospective_held_recorder_states',chunk_index:1,samples:as}];
let archiveRequests=0;
card._hass.callApi=async(method,url)=>{assert.equal(method,'GET');assert.match(url,/sensor.nocni_stinovy_denik_rekonstrukce/);assert.match(url,/significant_changes_only=0/);assert.doesNotMatch(url,/minimal_response/);archiveRequests++;return [[...chunks,chunks[0],{...chunks[0],archive_id:'b'.repeat(64)}].map(attributes=>({attributes}))];};
await card.loadControlHistory(true);
assert.equal(card.controlCache[archive.day].archive_complete,true);assert.equal(card.controlCache[archive.day].events.length,1);assert.equal(card.controlCache[archive.day].samples.length,2);
assert.match(card.shadowRoot.innerHTML,/ZPĚTNÁ REKONSTRUKCE/);assert.match(card.shadowRoot.innerHTML,/Heartbeat &lt;unknown&gt;/);assert.match(card.shadowRoot.innerHTML,/2026-01-14 · archiv dostupný/);
const ar=archiveRequests;await card.loadControlHistory();assert.equal(archiveRequests,ar);
card._hass.callApi=async()=>[[{attributes:chunks[0]}]];await card.loadControlHistory(true);assert.equal(card.controlCache[archive.day].archive_complete,false);assert.equal(card.controlError,true);assert.match(card.shadowRoot.innerHTML,/nepodařilo načíst úplně/);
// A live session always takes its original loading path, even if an archive exists for the day.
card._hass.states[controlEntity].attributes.session={...controlSession,day:archive.day};
card._hass.callApi=async(method,url)=>{assert.match(url,/filter_entity_id=sensor.nocni_stinovy_ridici_denik&/);return [];};
card.controlSources={[archive.day]:'live'};await card.loadControlHistory(true);assert.doesNotMatch(card.controlPanel(),/ZPĚTNÁ REKONSTRUKCE/);assert.equal(card.controlCache[archive.day].events.length,0);
console.log('PASS: retrospective provenance, chunk completeness, escaping, source isolation, no service calls');

// Odlišné registry a existující, ale rozporná data musí být čitelné i v deníku.
const auditedDay='2026-01-13';card.controlDay=auditedDay;card.controlShowAll=true;
card._hass.states[controlEntity].attributes.session=null;
const auditedRun={...controlSession,day:auditedDay,event_count:2,provenance:{kind:'retrospective_held_recorder_states',limitations:[]},operating_context:{run_status:{entity_id:'sensor.solax_run_mode',value:'Normal Mode',label:'Provozní stav měniče'},charge_strategy:{entity_id:'select.solax_charger_use_mode',value:'Back Up Mode',label:'Nastavená strategie nabíjení'}},input_diagnostics:[{at:'2026-01-13T03:00:00Z',phase:2,grid_power_w:-4600,grid_voltage_v:230,grid_current_a:16,apparent_power_va:3680,power_to_va_ratio:1.25,accepted_ratio_max:1.05,recorded_inconsistent_interval_s:5}]};
card.controlCache[auditedDay]={session:auditedRun,events:[{...controlEvent,day:auditedDay,id:1,entity_id:'select.solax_charger_use_mode',before:'Back Up Mode',after:'Manual Mode',reason:'enable_virtual_charge'},{...controlEvent,day:auditedDay,id:2,reason:'inconsistent_phase_measurement',diagnostic:auditedRun.input_diagnostics[0]}],samples:[]};
let auditedHTML=card.controlPanel();
assert.match(auditedHTML,/Provozní stav měniče/);assert.match(auditedHTML,/sensor.solax_run_mode/);assert.match(auditedHTML,/Normal Mode/);assert.match(auditedHTML,/Nastavená strategie nabíjení/);assert.match(auditedHTML,/Strategie nabíjení \(nastavení\)/);assert.match(auditedHTML,/Back Up Mode → Manual Mode/);assert.match(auditedHTML,/Rozporné měření proudu a výkonu fáze/);assert.match(auditedHTML,/Data přicházela/);assert.match(auditedHTML,/data jsou přítomná, ale rozporná/);assert.doesNotMatch(auditedHTML,/Chybí platné podklady nabíjení/);
console.log('PASS: operating status and charge strategy separated; inconsistency evidence is not called missing data');

// Nový výkonový model nesmí v grafu předstírat přepis trvalého A registru.
card.controlDay='2026-01-12';card.controlShowAll=true;
card._hass.states[controlEntity].attributes={policy:'volatile-power-shadow-v1',cadence_s:5,observed_at:new Date().toISOString(),interface:{readback_available:[],physical_control_ready:false}};
card.controlCache[card.controlDay]={session:{...controlSession,day:card.controlDay,policy:'volatile-power-shadow-v1',counts:{power_increases:2,power_decreases:1,stops:0}},events:[],samples:[{at:'2026-01-12T02:00:00Z',virtual_limit_dc_a:2,actual_limit_dc_a:30},{at:'2026-01-12T02:00:05Z',virtual_limit_dc_a:4,actual_limit_dc_a:30}]};
const ramHTML=card.controlPanel();assert.match(ramHTML,/EEPROM zápisy 0/);assert.match(ramHTML,/Zvýšení výkonu/);assert.match(ramHTML,/Odhad A DC z požadavku výkonu/);assert.match(ramHTML,/Trvalý limit A DC · pouze čtení/);assert.match(ramHTML,/fyzické řízení vypnuté/);assert.doesNotMatch(ramHTML,/Nastavení se zaokrouhluje dolů na krok registru/);
console.log('PASS: RAM shadow UI separates logical power, estimated DC current and read-only persistent ceiling');

// Archive labels follow their source version, with a fallback for older manifests.
card.controlCache[card.controlDay].session.provenance={software_version:'0.6.8',limitations:[]};
assert.match(card.controlPanel(),/logikou 0\.6\.8/);
card.controlCache[card.controlDay].session.provenance.software_version='<untrusted>';
assert.match(card.controlPanel(),/logikou &lt;untrusted&gt;/);
delete card.controlCache[card.controlDay].session.provenance.software_version;
assert.match(card.controlPanel(),/logikou 0\.6\.7/);
console.log('PASS: archive version comes from provenance and is escaped; legacy fallback retained');

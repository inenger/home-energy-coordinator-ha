import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import crypto from 'node:crypto';
let Card;const ctx={HTMLElement:class{attachShadow(){this.shadowRoot={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>({})};}},customElements:{get:()=>Card,define:(_,c)=>{Card=c;}},localStorage:{getItem:()=>null},window:{},requestAnimationFrame:()=>{},console,Date,Intl,Blob,DecompressionStream,TextDecoder,TextEncoder,Uint8Array,atob,btoa,crypto:{}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url),'utf8'),ctx);
const card=new Card();card.setConfig({});const state=v=>({state:String(v),attributes:{unit_of_measurement:'A'}});card._hass={states:{'sensor.solax_run_mode':{state:'Normal Mode',attributes:{}},'number.solax_api_max_charge_current_setting':state(16),'number.tesla_model_y_juniper_nabijeci_proud':state(13),'number.solax_battery_charge_max_current':state(30),'sensor.solax_battery_current_charge':state(2.5)}};card.lastEntity={attributes:{at:new Date().toISOString(),collection_health:{status:'ok'}}};card.render();
const values=Object.fromEntries([...card.shadowRoot.innerHTML.matchAll(/<label>([^<]+)<\/label><b>([^<]+)</g)].map(m=>[m[1],m[2].trim()]));
assert.equal(values['Wallbox · nastavený limit'],'16');assert.equal(values['Tesla · nastavený limit'],'13');assert.equal(values['Max. nabíjecí proud · nastavení'],'30');assert.equal(values['Naměřený proud baterie'],'2,5');
const day='2026-01-15',run={day,status:'closed',event_count:1,statistics:{sample_count:1},provenance:{kind:'retrospective_held_recorder_states',software_version:'0.6.12',limitations:[]}},event={id:1,day,at:day+'T02:00:00Z',kind:'would_set',before:0,after:100},sample={day,at:event.at,virtual_limit_dc_a:1};
const manifest={day,archive_id:'a'.repeat(64),recorded_from:day+'T10:00:00Z',recorded_to:day+'T10:01:00Z',event_count:1,sample_count:1,chunk_count:2};
const part=(index,extra)=>({attributes:{day,archive_id:manifest.archive_id,kind:'retrospective_held_recorder_states',chunk_index:index,chunk_count:2,...extra}});
const canonical=vm.runInContext('NIGHT_CANONICAL',ctx),content=canonical({session:run,events:[event],samples:[sample]}),hash=crypto.createHash('sha256').update(content).digest('hex');
async function load(rows,m={...manifest,content_sha256:hash}){
 const c=new Card();c.setConfig({control_archives:[m]});c.controlDay=day;c.render=()=>{};c._hass={states:{},callApi:async(method)=>{assert.equal(method,'GET');return [rows];},callService(){throw Error('No services');}};
 await c.loadControlHistory(true);return c;
}
const good=[part(0,{session:run,events:[event]}),part(1,{samples:[sample]})];
let c=await load(good);assert.equal(c.controlError,false);assert.equal(c.controlCache[day].verified_content_sha256,hash);assert.equal(c.controlSession().day,day);
c=await load([...good,structuredClone(good[0])]);assert.equal(c.controlError,false,'Exact duplicate should be harmless');
const reordered=JSON.parse(JSON.stringify(good),(k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).reverse()):v);c=await load(reordered);assert.equal(c.controlError,false,'Object key order must not change digest');
for(const [label,rows,m]of [
 ['index',[part(999,{session:run,events:[event],samples:[sample]})],{...manifest,chunk_count:1}],
 ['event conflict',[...good,part(1,{samples:[sample],events:[{...event,after:999}]})],manifest],
 ['sample conflict',[good[0],part(1,{samples:[sample,{...sample,virtual_limit_dc_a:99}]})],manifest],
 ['session conflict',[good[0],part(1,{samples:[sample],session:{...run,status:'active'}})],manifest],
 ['content corruption',[part(0,{session:run,events:[{...event,after:999}]}),good[1]],{...manifest,content_sha256:hash}],
 ['metadata',[good[0],{attributes:{...good[1].attributes,chunk_count:3}}],manifest],
 ['missing',[good[0]],manifest],
 ['manifest',good,{...manifest,chunk_count:0}],
 ]){
 c=await load(rows,m);assert.equal(c.controlError,true,label);assert.equal(c.controlSession(),null,label+' leaked an unverified controller');
}
const stamp=s=>new Date(Date.parse(day+'T02:00:00Z')+s*1000).toISOString(),rows=[{at:stamp(0),virtual_limit_dc_a:0,actual_limit_dc_a:30,actual_charge_dc_a:0},{at:stamp(5),virtual_limit_dc_a:10,actual_limit_dc_a:30,actual_charge_dc_a:0,intent_expires_at:stamp(15)},{at:stamp(10),virtual_limit_dc_a:20,actual_limit_dc_a:30,actual_charge_dc_a:0,intent_expires_at:stamp(20)},{at:stamp(20),virtual_limit_dc_a:0,actual_limit_dc_a:30,actual_charge_dc_a:0}];
let graph=card.controlCurrentChart(rows,true,[{at:stamp(12),kind:'would_stop_charge'}]),green=graph.match(/<path d="([^"]*)" fill="none" stroke="#5fdfbc"/)[1];assert(green.includes('H580.0V145.0'));assert(!green.includes('H940.0V145.0'));
const expired=structuredClone(rows);expired[2].intent_expires_at=stamp(15);graph=card.controlCurrentChart(expired,true,[]);green=graph.match(/<path d="([^"]*)" fill="none" stroke="#5fdfbc"/)[1];assert(green.includes('H715.0V145.0'));
assert(graph.includes('stroke="#94a9bb"'),'Persistent setting must stay separate from logical expiry');
console.log('PASS: four named current entities, archive index/duplicates/metadata/content SHA, no partial controller, exact stop and expiry plot boundaries');

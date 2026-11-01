// Syntetické protipříklady skutečného loaderu; žádné HA služby nebo síť.
import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';import crypto from 'node:crypto';import zlib from 'node:zlib';import path from 'node:path';
let Card;const RealDate=Date,now=Date.parse('2026-01-29T12:00:00Z');
class Clock extends RealDate{constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
const ctx={HTMLElement:class{attachShadow(){this.shadowRoot={querySelector:()=>null,querySelectorAll:()=>[],innerHTML:''};}},customElements:{get:()=>Card,define:(_,c)=>{Card=c;}},localStorage:{getItem:()=>null},window:{},console,Date:Clock,Intl,requestAnimationFrame:()=>{},Blob,DecompressionStream,TextDecoder,TextEncoder,Uint8Array,atob,btoa,crypto:{}};
vm.runInNewContext(fs.readFileSync(new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url),'utf8'),ctx);
const day='2026-01-15',at=day+'T02:00:05Z',last=day+'T04:00:02Z',eid='sensor.nocni_stinovy_ridici_denik',stream='audit-synthetic';
const run={day,status:'closed',closed_at:day+'T04:00:00Z',policy:'volatile-power-shadow-v2',event_count:1,statistics:{sample_count:1},counts:{}};
function batch(seq,power){const delta={session:run,events:[{id:1,day,at,kind:'would_set',after:power}],samples:[{day,at,ram_target_ac_w:power}]};const raw=Buffer.from(JSON.stringify(delta));return {format:'journal-chunks-v1',stream_id:stream,seq,batch_id:crypto.createHash('sha256').update(raw).digest('hex'),part_index:0,part_count:1,first_seq:seq,last_seq:seq,day,at,encoding:'zlib-json-v1',unpacked_bytes:raw.length,data:zlib.deflateSync(raw).toString('base64'),device_actions:0};}
function cardFor(parts){const c=new Card();c.setConfig({});c.render=()=>{};c.controlDay=day;let requested;
c._hass={states:{[eid]:{attributes:{observed_at:new Clock().toISOString(),session:run,sessions:[run],transport:{format:'journal-chunks-v1',stream_id:stream,status:'ok',pending_chunks:0,days:{[day]:{first_recorded_at:at,last_recorded_at:last,recorded_chunks:parts.length,queued_chunks:parts.length}}}}}},callApi:async(method,url)=>{if(method!=='GET')throw Error('Writes forbidden');requested=url;return [parts.map(attributes=>({attributes}))];},callService(){throw Error('Services forbidden');}};
return {c,url:()=>requested};}

const original=batch(1,500),conflict=batch(2,9000);
for(const parts of [[original,conflict],[conflict,original]]){
 const {c}=cardFor(parts);await c.loadControlHistory(true);
 assert.equal(c.controlError,true);assert.equal(c.controlSession(),null);
 assert.equal(c.controlEventView().all.length,0);
}
const good=cardFor([original,original]);await good.c.loadControlHistory(true);
assert.equal(good.c.controlError,false);assert.equal(good.c.controlCache[day].history_complete,true);
const endOf=x=>Date.parse(new URL('https://synthetic.invalid/'+x.url()).searchParams.get('end_time'));
assert.equal(endOf(good),Date.parse(last)+2000);
const attrs=c=>c._hass.states[eid].attributes;
let calls=0;const api=good.c._hass.callApi;
good.c._hass.callApi=(...args)=>{calls++;return api(...args);};
await good.c.loadControlHistory();assert.equal(calls,0,'Complete cache skips network');
attrs(good.c).recent_events=[{id:1,day,at,kind:'would_set',after:9000}];
assert.equal(good.c.controlSession(),null);assert.equal(good.c.controlEventView().all.length,0);
attrs(good.c).recent_events=[];
await good.c.loadControlHistory();assert.equal(calls,1,'Integrity failure permits recovery');
assert.equal(good.c.controlError,false);assert.ok(good.c.controlSession());
attrs(good.c).recent_samples=[{day,at,ram_target_ac_w:9000}];
assert.equal(good.c.controlSession(),null);
attrs(good.c).recent_samples=[{ram_target_ac_w:500,at,day}];
await good.c.loadControlHistory(true);assert.equal(good.c.controlError,false,'Key order is not conflict');
const delta=cardFor([conflict]);delta.c.controlCache=structuredClone(good.c.controlCache);
await delta.c.loadControlHistory(true);assert.equal(delta.c.controlError,true);assert.equal(delta.c.controlSession(),null);
for(const mode of ['pending','active','unknown-last','late']){
 const probe=cardFor([original]);const a=attrs(probe.c);
 if(mode==='pending')a.transport.days[day].queued_chunks=2;
 if(mode==='active'){a.session={...run,closed_at:null};a.sessions=[a.session];}
 if(mode==='unknown-last')delete a.transport.days[day].last_recorded_at;
 if(mode==='late')a.transport.days[day].last_recorded_at='2026-01-16T08:00:00Z';
 await probe.c.loadControlHistory(true);
 assert.equal(endOf(probe),mode==='late'?Date.parse('2026-01-16T08:00:02Z'):now,mode);
}
console.log('A15-02/03: conflicting batch orders, live events/samples, cache delta, exact duplicates, recovery and bounded/late/pending/active ranges PASS');

const archived=cardFor([]).c;archived.controlIntegrityErrors={[day]:true};archived.controlUseArchive=()=>true;archived.controlArchives=()=>[{day,archive_id:'a'.repeat(64)}];archived.controlCache={[day]:{archive_id:'a'.repeat(64),archive_complete:true,session:run,events:[],samples:[]}};assert.ok(archived.controlSession());assert(!archived.controlPanelBody().includes('Konflikt obsahu deníku'));

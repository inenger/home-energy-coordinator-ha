// Syntetické protipříklady skutečného loaderu; žádné HA služby nebo síť.
import fs from 'node:fs';import vm from 'node:vm';import crypto from 'node:crypto';import zlib from 'node:zlib';import path from 'node:path';
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
const original=batch(1,500),conflict=batch(2,9000),bad=cardFor([original,conflict]);await bad.c.loadControlHistory(true);
const reversed=cardFor([conflict,original]);await reversed.c.loadControlHistory(true);
const good=cardFor([original,original]);await good.c.loadControlHistory(true);
const url=new URL('https://synthetic.invalid/'+bad.url()),end=Date.parse(url.searchParams.get('end_time')),begin=Date.parse(url.pathname.split('/period/')[1]);
const results={
 'A15-02':{valid_batch_hashes:true,conflicting_event_id:1,conflicting_sample_at:at,original_power_w:500,replacement_power_w:bad.c.controlCache[day].events[0].after,reversed_response_power_w:reversed.c.controlCache[day].events[0].after,history_complete:bad.c.controlCache[day].history_complete,error:bad.c.controlError,contract_met:bad.c.controlError===true},
 'exact_duplicate_control':{history_complete:good.c.controlCache[day].history_complete,error:good.c.controlError,contract_met:good.c.controlError===false},
 'A15-03':{closed_day:day,last_recorded_at:last,requested_end:new RealDate(end).toISOString(),requested_hours:(end-begin)/3600000,known_recorded_hours:(Date.parse(last)-begin)/3600000,excess_days:(end-Date.parse(last))/86400000,contract_met:end<=Date.parse(last)+2000}
};
const out=process.env.ENERGY_AUDIT_OUTPUT||'/tmp/audit-0615';fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'frontend-probes.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));

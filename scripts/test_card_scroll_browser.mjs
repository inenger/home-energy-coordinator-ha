// Skutečný Chromium: geometrie, identita DOM, kolečko, focus a všechny stránky.
// Volitelná skutečná data smí být předána jen na autorizovaném RPi.
import fs from 'node:fs';import http from 'node:http';import {createRequire}from 'node:module';import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),puppeteer=require(process.env.PUPPETEER_MODULE_PATH||'puppeteer');
const source=process.env.CARD_SOURCE||new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url);
const day='2026-01-15',at=i=>new Date(Date.parse(day+'T02:00:00Z')+i*5000).toISOString();
const run={day,policy:'volatile-power-shadow-v2',status:'closed',event_count:1057,statistics:{sample_count:1440},closed_at:day+'T04:00:00Z',counts:{stops:2},software_version:'0.6.12',shadow_model:{covered_s:7190,battery_kwh_ac:10,soc_pct:90},provenance:{kind:'retrospective_held_recorder_states',software_version:'0.6.12',limitations:['Synthetic browser test']}};
const synthetic={archive:{session:run,events:Array.from({length:1057},(_,i)=>({id:i+1,day,at:at(i),kind:'would_set',entity_id:'virtual.test',label:'Syntetická událost '+i,before:100,after:200,reason:'ev_first'})),samples:Array.from({length:1440},(_,i)=>({day,at:at(i),virtual_limit_dc_a:10+i%10,actual_limit_dc_a:30,actual_charge_dc_a:0}))},manifest:{day,archive_id:'a'.repeat(64),software_version:'0.6.12',recorded_from:day+'T10:00:00Z',recorded_to:day+'T10:01:00Z',event_count:1057,sample_count:1440,chunk_count:1},states:{}};
const fixture=process.env.CARD_FIXTURE?JSON.parse(fs.readFileSync(process.env.CARD_FIXTURE)):synthetic;
const server=http.createServer((q,s)=>{s.setHeader('Content-Type','text/html');s.end('<!doctype html><html><body style="margin:0;background:#101a25;color:#eee"><main id="shell"></main></body></html>');});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await puppeteer.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));const results=[];
try{
 for(const width of [1280,390]){
  await page.setViewport({width,height:850});await page.goto('http://127.0.0.1:'+server.address().port);
  await page.addScriptTag({content:fs.readFileSync(source,'utf8')});
  await page.evaluate(fixture=>{
   const host=document.querySelector('#shell');host.attachShadow({mode:'open'});host.shadowRoot.innerHTML='<div id="view" style="height:820px;overflow:auto;overflow-anchor:none"><div style="height:180px"></div><night-priority-card></night-priority-card><div id="below" style="height:900px">Obsah pod kartou</div></div>';
   const card=host.shadowRoot.querySelector('night-priority-card');window.card=card;window.view=host.shadowRoot.querySelector('#view');window.fixture=fixture;
   const states={...fixture.states};states['sensor.nocni_stinovy_plan']={...(states['sensor.nocni_stinovy_plan']||{}),attributes:{...(states['sensor.nocni_stinovy_plan']?.attributes||{}),at:new Date().toISOString(),collection_health:{status:'ok'}}};
   states['sensor.nocni_stinovy_ridici_denik']={...(states['sensor.nocni_stinovy_ridici_denik']||{}),attributes:{...(states['sensor.nocni_stinovy_ridici_denik']?.attributes||{}),observed_at:new Date().toISOString(),session:fixture.archive.session,sessions:[fixture.archive.session]}};
   card.setConfig({control_archives:[fixture.manifest]});card.controlDay=fixture.manifest.day;
   card._hass={states,callApi:async()=>[],callService(){throw Error('Services forbidden');}};card.lastEntity=states['sensor.nocni_stinovy_plan'];card.lastSummary=states['sensor.nocni_stinovy_souhrn'];card.render();
  },fixture);
  const loading=await page.evaluate(()=>{
   const root=card.shadowRoot,heading=root.querySelector('.control-panel h2');view.scrollTop+=heading.getBoundingClientRect().top-100;const before=heading.getBoundingClientRect().top;
   card.controlCache={[fixture.manifest.day]:{...fixture.archive,archive_id:fixture.manifest.archive_id,archive_complete:true,verified_content_sha256:fixture.manifest.content_sha256||null,loadedAt:Date.now()}};
   card.render();return {sameHeading:heading===root.querySelector('.control-panel h2'),shift:root.querySelector('.control-panel h2').getBoundingClientRect().top-before};
  });
  assert(loading.sameHeading,'Loading replaced the reading anchor');assert(Math.abs(loading.shift)<=1,'Loading shifted the reading anchor by '+loading.shift);
  const stable=await page.evaluate(()=>{
   const root=card.shadowRoot,details=[...root.querySelectorAll('details.capacity')];if(details.length>1){details[0].open=true;details[1].open=false;}
   const scroll=root.querySelector('#control-events')||root.querySelector('.control-timeline').parentElement;scroll.scrollTop=650;scroll.scrollLeft=40;
   view.scrollTop+=scroll.getBoundingClientRect().top-100;const before={top:scroll.scrollTop,left:scroll.scrollLeft,y:scroll.getBoundingClientRect().top};
   const focus=root.querySelector('#control-day');focus.focus({preventScroll:true});
   card.lastEntity={...card.lastEntity,attributes:{...card.lastEntity.attributes,collection_health:{status:'degraded',summary_errors:[{day:'2026-01-01',error_code:'Synthetic warning increases the height above the journal'}]}}};
   const timings={};for(const name of ['controlPanel','controllerPanel','inputHealth','optimizerPanel','auditPanels','automationPanel','updateDOM','chart']){const original=card[name].bind(card);card[name]=(...args)=>{const t=performance.now();try{return original(...args);}finally{timings[name]=(timings[name]||0)+performance.now()-t;}};}
   const t=performance.now();card.render();const duration=performance.now()-t,after=root.querySelector('#control-events')||root.querySelector('.control-timeline').parentElement;
   return {sameScroll:scroll===after,sameDetails:details[0]===root.querySelector('details.capacity'),independentDetails:details.length<2||details[0].open&&!details[1].open,sameFocus:root.activeElement===focus,topShift:after.scrollTop-before.top,leftShift:after.scrollLeft-before.left,viewportShift:after.getBoundingClientRect().top-before.y,duration,timings};
  });
  console.log('geometry',width,JSON.stringify(stable));
  assert(stable.sameScroll,'Refresh replaced journal scroll container');assert(stable.sameDetails&&stable.independentDetails,'Details state changed across refresh');assert(stable.sameFocus,'Refresh lost selector focus');assert(Math.abs(stable.topShift)<=1&&Math.abs(stable.leftShift)<=1,'Refresh reset journal offset');assert(Math.abs(stable.viewportShift)<=1,'Refresh shifted journal viewport '+stable.viewportShift);
  const pages=await page.evaluate(async()=>{
   card.controlShowAll=true;card.controlPage=0;card.render();const root=card.shadowRoot,ids=[],durations=[],graph=root.querySelector('.control-chart')?.firstElementChild;let maxRows=0,fullRenders=0;const savedRender=card.render.bind(card);card.render=(...args)=>{fullRenders++;return savedRender(...args);};
   for(;;){await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));const rows=[...root.querySelectorAll('.control-timeline tbody tr[data-ui-key]')];maxRows=Math.max(maxRows,rows.length);ids.push(...rows.map(n=>Number(n.getAttribute('data-ui-key').split('-')[1])));const next=root.querySelector('#control-next');if(!next||next.disabled)break;const t=performance.now();next.click();root.querySelector('#control-events').getBoundingClientRect();durations.push(performance.now()-t);}
   card.render=savedRender;return {ids,maxRows,durations,fullRenders,sameGraph:graph===root.querySelector('.control-chart')?.firstElementChild,loadedSamples:card.controlCache[fixture.manifest.day].samples.length};
  });
  assert.equal(pages.fullRenders,0,'Paging invoked full card render');assert(pages.sameGraph,'Paging replaced graph');assert(Math.max(...pages.durations)<100,'Page rendering exceeds 100ms budget: '+Math.max(...pages.durations));assert(pages.maxRows<=20,'Journal DOM is unbounded');assert.deepEqual(pages.ids,fixture.archive.events.map(e=>e.id).sort((a,b)=>a-b));assert.equal(pages.loadedSamples,fixture.archive.samples.length);
  await page.evaluate(()=>{card.controlPage=0;card.render();const n=card.shadowRoot.querySelector('#control-events');n.scrollTop=0;view.scrollTop+=n.getBoundingClientRect().top-100;});
  const point=await page.evaluate(()=>{const n=card.shadowRoot.querySelector('#control-events'),r=n.getBoundingClientRect();return{x:r.left+Math.min(160,r.width/2),y:r.top+150,top:n.scrollTop};});
  await page.mouse.move(point.x,point.y);await page.mouse.wheel({deltaY:300});await new Promise(resolve=>setTimeout(resolve,120));
  const wheelTop=await page.evaluate(()=>card.shadowRoot.querySelector('#control-events').scrollTop);assert(wheelTop>point.top,'Wheel did not scroll journal');
  const counts=await page.evaluate(async()=>{
   card.hydratePacked=async()=>{};card.loadControlHistory=async()=>{};card.loadHistory=async()=>{};card.lastHistory=Date.now();
   const plan=card.lastEntity,raw={...plan,attributes:{packed_attributes:{sha256:'f'.repeat(64)}}};card.packedCache={'sensor.nocni_stinovy_plan':{hash:'f'.repeat(64),attributes:plan.attributes}};
   const hass={...card._hass,states:{...card._hass.states,'sensor.nocni_stinovy_plan':raw}};
   card.hass=hass;await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
   let renders=0;const render=card.render.bind(card);card.render=()=>{renders++;return render();};
   for(let i=0;i<100;i++)card.hass={...hass,states:{...hass.states,'sensor.unrelated':{state:String(i)}}};
   await new Promise(requestAnimationFrame);const unrelated=renders;renders=0;
   for(let i=0;i<20;i++)card.hass={...hass,states:{...hass.states,'sensor.nocni_stinovy_plan':{...raw,last_updated:String(i)}}};
   await new Promise(requestAnimationFrame);const burst=renders;
   return {unrelated,burst};
  });
  assert.equal(counts.unrelated,0,'Unchanged packed state caused redraws');assert.equal(counts.burst,1,'State burst was not coalesced');
  results.push({width,loading_anchor_shift_px:loading.shift,...stable,pages:Math.ceil(fixture.archive.events.length/20),max_rows:pages.maxRows,all_events_reachable:true,loaded_samples:pages.loadedSamples,wheel_scroll_px:wheelTop-point.top,unrelated_updates_rendered:counts.unrelated,burst_renders:counts.burst,page_render_max_ms:Math.max(...pages.durations),page_full_renders:pages.fullRenders,page_graph_preserved:pages.sameGraph});
 }
 assert.deepEqual(errors,[]);const output={browser:await browser.version(),real_browser:true,actual_HA_shell:false,private_fixture:!!process.env.CARD_FIXTURE,results,physical_services:0};if(process.env.CARD_BROWSER_RESULT)fs.writeFileSync(process.env.CARD_BROWSER_RESULT,JSON.stringify(output,null,2));console.log('PASS: real Chromium stable reading anchor, retained DOM/details/focus/offsets, wheel, bounded pages, all events, packed identity and coalesced renders');console.log(JSON.stringify(output));
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}

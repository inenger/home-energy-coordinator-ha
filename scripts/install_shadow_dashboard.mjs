// Install only a simulation helper, local Lovelace resource and one named view.
import fs from 'node:fs';import crypto from 'node:crypto';
const helper='input_select.nocni_stinova_priorita';
const dir='/share/hec-recovery/night-priority-'+new Date().toISOString().replace(/[:.]/g,'-');
fs.mkdirSync(dir,{recursive:true,mode:0o700});
const hash=x=>crypto.createHash('sha256').update(typeof x==='string'?x:JSON.stringify(x)).digest('hex');
const automation=fs.readFileSync('/config/automations.yaml','utf8');
if(automation.includes(helper))throw Error('Helper already referenced by operational automations; inspect before install');
const beforeHash=hash(automation);
const ws=new WebSocket('ws://supervisor/core/websocket');let counter=0;const pending=new Map();
const authenticated=new Promise((resolve,reject)=>{
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==='auth_required')ws.send(JSON.stringify({type:'auth',access_token:process.env.SUPERVISOR_TOKEN}));else if(m.type==='auth_ok')resolve();else if(m.type==='auth_invalid')reject(Error('Authentication rejected'));else if(m.id&&pending.has(m.id)){const {resolve,reject}=pending.get(m.id);pending.delete(m.id);m.success?resolve(m.result):reject(Error(m.error?.code+': '+m.error?.message));}};
 ws.onerror=()=>reject(Error('Websocket failed'));
});
const rpc=(type,args={})=>new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,type,...args}));});
const timer=setTimeout(()=>{console.error('Installer timed out');ws.close();process.exitCode=1;},45000);
try{
 await authenticated;
 const helpers=await rpc('input_select/list');
 fs.writeFileSync(dir+'/helpers-before.json',JSON.stringify(helpers,null,2),{mode:0o600});
 if(!helpers.some(x=>x.name==='Noční stínová priorita'))await rpc('input_select/create',{name:'Noční stínová priorita',options:['Elektromobil','Baterie SolaX'],icon:'mdi:swap-horizontal'});
 const dashboard=await rpc('lovelace/config',{url_path:'lovelace'});
 fs.writeFileSync(dir+'/lovelace-before.json',JSON.stringify(dashboard,null,2),{mode:0o600});
 const resources=await rpc('lovelace/resources');
 fs.writeFileSync(dir+'/resources-before.json',JSON.stringify(resources,null,2),{mode:0o600});
 const js=fs.readFileSync('/config/www/night-priority-card.js','utf8');
 const url='/local/night-priority-card.js?v=0.5.4-'+hash(js).slice(0,10);
 const existing=resources.find(x=>x.url?.startsWith('/local/night-priority-card.js'));
 if(existing)await rpc('lovelace/resources/update',{resource_id:existing.id,url,res_type:'module'});
 else await rpc('lovelace/resources/create',{url,res_type:'module'});
 const index=dashboard.views.findIndex(v=>v.path==='nabijeni');
 if(index<0)throw Error('Named charging view is missing');
 const others=dashboard.views.filter((_,i)=>i!==index);
 const latest=await rpc('lovelace/config',{url_path:'lovelace'});
 if(hash(latest)!==hash(dashboard))throw Error('Dashboard changed concurrently; retry after fresh review');
 const config=structuredClone(dashboard);
 config.views[index]={title:'Nabíjení',path:'nabijeni',icon:'mdi:ev-station',type:'panel',cards:[{type:'custom:night-priority-card'}]};
 await rpc('lovelace/config/save',{url_path:'lovelace',config});
 const saved=await rpc('lovelace/config',{url_path:'lovelace'});
 if(hash(saved.views.filter((_,i)=>i!==index))!==hash(others))throw Error('Other views differ after save');
 if(hash(fs.readFileSync('/config/automations.yaml','utf8'))!==beforeHash)throw Error('Operational automations changed during install');
 const result={backup:dir,updated_view:saved.views[index].path,view_count:saved.views.length,other_views_unchanged:true,automation_sha256:beforeHash,resource:url,helper,device_actions:0};
 fs.writeFileSync(dir+'/evidence.json',JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result));
}finally{clearTimeout(timer);ws.close();}

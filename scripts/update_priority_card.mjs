// Update only the existing priority card resource; preserve every Lovelace view.
import fs from 'node:fs';
import crypto from 'node:crypto';
const root=process.argv[2];
if(!root?.startsWith('/share/hec-recovery/'))throw Error('Expected a recovery directory');
const version=process.argv[3];
if(!/^0\.[0-9]+\.[0-9]+$/.test(version||''))throw Error('Expected a shadow version');
const hash=x=>crypto.createHash('sha256').update(typeof x==='string'?x:JSON.stringify(x)).digest('hex');
const automation=hash(fs.readFileSync('/config/automations.yaml','utf8'));
const ws=new WebSocket('ws://supervisor/core/websocket');
let id=0;const pending=new Map();
const ready=new Promise((resolve,reject)=>{
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==='auth_required')ws.send(JSON.stringify({type:'auth',access_token:process.env.SUPERVISOR_TOKEN}));else if(m.type==='auth_ok')resolve();else if(m.type==='auth_invalid')reject(Error('Auth failed'));else if(pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.success?p.resolve(m.result):p.reject(Error(m.error?.code));}};
 ws.onerror=()=>reject(Error('Websocket failed'));
});
const rpc=(type,args={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,type,...args}));});
const timer=setTimeout(()=>{ws.close();process.exitCode=1;},30000);
try{
 await ready;
 const dashboard=await rpc('lovelace/config',{url_path:'lovelace'}),resources=await rpc('lovelace/resources');
 fs.writeFileSync(root+'/lovelace-before.json',JSON.stringify(dashboard),{mode:0o600});
 fs.writeFileSync(root+'/resources-before.json',JSON.stringify(resources),{mode:0o600});
 const matches=resources.filter(r=>r.url?.startsWith('/local/night-priority-card.js'));
 if(matches.length!==1)throw Error('Expected one existing priority resource');
 const latest=await rpc('lovelace/config',{url_path:'lovelace'});
 if(hash(latest)!==hash(dashboard))throw Error('Concurrent dashboard change');
 const old=fs.readFileSync('/config/www/night-priority-card.js','utf8');
 if(hash(old)!==hash(fs.readFileSync(root+'/card-before.js','utf8')))throw Error('Card changed since backup');
 const js=fs.readFileSync(root+'/new/dashboard/night-priority-card.js','utf8');
 fs.writeFileSync('/config/www/night-priority-card.js.next',js);
 fs.renameSync('/config/www/night-priority-card.js.next','/config/www/night-priority-card.js');
 const url='/local/night-priority-card.js?v='+version+'-'+hash(js).slice(0,10);
 await rpc('lovelace/resources/update',{resource_id:matches[0].id,url,res_type:'module'});
 const saved=await rpc('lovelace/config',{url_path:'lovelace'});
 const after=await rpc('lovelace/resources');
 if(hash(saved)!==hash(dashboard))throw Error('Dashboard views changed');
 if(hash(after.filter(r=>r.id!==matches[0].id))!==hash(resources.filter(r=>r.id!==matches[0].id)))throw Error('Other resources changed');
 if(!after.some(r=>r.id===matches[0].id&&r.url===url))throw Error('Resource not updated');
 if(hash(fs.readFileSync('/config/automations.yaml','utf8'))!==automation)throw Error('Automations changed');
 const result={resource:url,card_sha256:hash(js),all_dashboard_views_unchanged:true,other_resources_unchanged:true,automation_sha256:automation};
 fs.writeFileSync(root+'/ui-result.json',JSON.stringify(result,null,2),{mode:0o600});
 console.log(JSON.stringify(result));
}finally{clearTimeout(timer);ws.close();}

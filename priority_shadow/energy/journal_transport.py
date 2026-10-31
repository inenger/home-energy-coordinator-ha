"""Trvalé přírůstky deníku. Potvrzení znamená načtení z recorderu, ne HTTP200.

Smyčka regulátoru jen přidává do SQLite. Samostatný worker provádí monitorovací
POST/GET a opakuje nepotvrzené části; nedotýká se fyzických HA služeb.
"""
import base64,hashlib,json,threading,time,uuid,zlib
from datetime import datetime,timedelta,timezone
from .store import Store,pack,unpack
from .monitor_payload import encoded,MAX_ATTRIBUTES_BYTES
from .core import instant
SENSOR='sensor.nocni_stinovy_denik_prirustky'
FORMAT='journal-chunks-v1'
PART_BYTES=7000

def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS journal_transport_meta(key TEXT PRIMARY KEY,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS journal_transport_outbox(seq INTEGER PRIMARY KEY,day TEXT NOT NULL,at TEXT NOT NULL,payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS journal_transport_receipts(seq INTEGER PRIMARY KEY,recorded_at TEXT NOT NULL,sha256 TEXT NOT NULL);''')

def get(db,key,default=None):
    row=db.execute('SELECT payload FROM journal_transport_meta WHERE key=?',(key,)).fetchone()
    return unpack(row[0])if row else default

def put(db,key,value):db.execute('INSERT OR REPLACE INTO journal_transport_meta VALUES(?,?)',(key,pack(value)))

def enqueue(store,journal):
    """Atomicky připraví chybějící řádky každé relace; pozdní návrat patří původnímu dni."""
    db=store.db;schema(db)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='ram_control_sessions'").fetchone():return status(store)
    with db:
        stream=get(db,'stream')
        if not stream:stream=uuid.uuid4().hex;put(db,'stream',stream)
        runs=[unpack(p)for p, in db.execute('SELECT payload FROM ram_control_sessions ORDER BY day')]
        for run in runs:
            day=run['day'];key='queued:'+day;cursor=get(db,key,{'event':0,'sample':0,'session_hash':None})
            events=[{'id':i,**unpack(p)}for i,p in db.execute('SELECT id,payload FROM ram_control_events WHERE day=? AND id>? ORDER BY id LIMIT 128',(day,cursor['event']))]
            samples=[(i,unpack(p))for i,p in db.execute('SELECT rowid,payload FROM ram_control_samples WHERE day=? AND rowid>? ORDER BY rowid LIMIT 128',(day,cursor['sample']))]
            session_hash=hashlib.sha256(encoded(run)).hexdigest()
            if not events and not samples and cursor.get('session_hash')==session_hash:continue
            delta={'session':run,'events':events,'samples':[p for _,p in samples]};raw=encoded(delta)
            if len(raw)>2*1024*1024:raise ValueError('JOURNAL_DELTA_TOO_LARGE_RETAINED_IN_SQLITE')
            batch=hashlib.sha256(raw).hexdigest();blob=zlib.compress(raw,6);parts=[blob[i:i+PART_BYTES]for i in range(0,len(blob),PART_BYTES)]
            seq=db.execute('SELECT coalesce(max(seq),0)FROM journal_transport_outbox').fetchone()[0];first=seq+1
            for i,part in enumerate(parts):
                seq+=1;attrs={'friendly_name':'Noční řídicí deník · přírůstky','format':FORMAT,'stream_id':stream,'seq':seq,'batch_id':batch,'part_index':i,'part_count':len(parts),'first_seq':first,'last_seq':first+len(parts)-1,'day':day,'at':journal.get('observed_at')or run.get('last_processed_at')or run['first_seen_at'],'encoding':'zlib-json-v1','unpacked_bytes':len(raw),'data':base64.b64encode(part).decode(),'device_actions':0}
                assert len(encoded(attrs))<MAX_ATTRIBUTES_BYTES
                db.execute('INSERT INTO journal_transport_outbox VALUES(?,?,?,?)',(seq,day,attrs['at'],pack(attrs)))
            put(db,key,{'event':events[-1]['id']if events else cursor['event'],'sample':samples[-1][0]if samples else cursor['sample'],'session_hash':session_hash})
    return status(store)

def status(store):
    schema(store.db);db=store.db
    head=db.execute('SELECT coalesce(max(seq),0)FROM journal_transport_outbox').fetchone()[0]
    ack=get(db,'ack',0);health=get(db,'health',{})
    days={day:{'first_recorded_at':first,'last_recorded_at':last,'queued_chunks':queued,'recorded_chunks':recorded}for day,first,last,queued,recorded in db.execute('SELECT o.day,min(r.recorded_at),max(r.recorded_at),count(o.seq),count(r.seq)FROM journal_transport_outbox o LEFT JOIN journal_transport_receipts r ON r.seq=o.seq GROUP BY o.day ORDER BY o.day DESC LIMIT 14')}
    return {'days':days,'format':FORMAT,'entity_id':SENSOR,'stream_id':get(db,'stream'),'queued_seq':head,'recorded_seq':ack,'pending_chunks':head-ack,**health}

def request_parts(entity,payload):
    if entity!=SENSOR:raise ValueError('Only journal monitoring stream is permitted')
    if len(encoded(payload['attributes']))>MAX_ATTRIBUTES_BYTES:raise ValueError('Journal chunk exceeds budget')
    return '/api/states/'+SENSOR,payload

class RecorderClient:
    def __init__(self):
        import urllib.request
        from .collector import NoRedirect,read_token
        self.urllib=urllib.request;self.token=read_token();self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def publish(self,attrs):
        path,payload=request_parts(SENSOR,{'state':str(attrs['seq'])+':'+uuid.uuid4().hex[:12],'attributes':attrs})
        req=self.urllib.Request('http://supervisor/core'+path,data=encoded(payload),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        with self.opener.open(req,timeout=5)as response:
            if response.status not in(200,201):raise RuntimeError('Journal stream publication failed')
    def history(self,begin,end):
        from urllib.parse import urlencode
        path='/api/history/period/'+begin+'?'+urlencode({'end_time':end,'filter_entity_id':SENSOR,'significant_changes_only':'0'})
        req=self.urllib.Request('http://supervisor/core'+path,headers={'Authorization':'Bearer '+self.token},method='GET')
        with self.opener.open(req,timeout=8)as response:raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Journal receipt response too large')
        return json.loads(raw)

class Publisher:
    def __init__(self,path,client=None):self.path=path;self.client=client;self.stop=threading.Event();self.thread=None
    def tick(self,now=None):
        """Jedna dávka s omezeným počtem in-flight zpráv a trvalým potvrzením."""
        now=now or datetime.now(timezone.utc);at=now.isoformat();store=Store(self.path);db=store.db;schema(db)
        try:
            if self.client is None:self.client=RecorderClient()
            ack=get(db,'ack',0);stream=get(db,'stream');rows=[(seq,unpack(p))for seq,p in db.execute('SELECT seq,payload FROM journal_transport_outbox WHERE seq>? ORDER BY seq LIMIT 32',(ack,))]
            if not rows:return
            sent=get(db,'sent',{})
            if sent:
                # Po návratu hodin se nové pokusy nesmějí zablokovat budoucím last_at.
                for receipt in sent.values():
                    if instant(receipt['first_at'])>now:receipt['first_at']=at
                lower=min(instant(x['first_at'])for x in sent.values())-timedelta(seconds=2)
                upper=now+timedelta(seconds=1)
                cursor=get(db,'receipt_cursor')
                begin=instant(cursor) if cursor else lower
                if not lower<=begin<upper:begin=lower
                end=min(upper,begin+timedelta(minutes=2))
                history=self.client.history(begin.isoformat(),end.isoformat());valid={seq:a for seq,a in rows}
                # Omezené cyklické dohledávání se vrací i ke starým časům.
                # Resend nemění první možný čas přijetí a neposune jej mimo dosah.
                with db:put(db,'receipt_cursor',(lower if end>=upper else end-timedelta(seconds=2)).isoformat())
                with db:
                    for series in history:
                        for state in series:
                            attrs=state.get('attributes',{});seq=attrs.get('seq');expected=valid.get(seq)
                            if expected and attrs==expected and attrs.get('stream_id')==stream:
                                stamp=state.get('last_updated')or state.get('last_changed')or sent.get(str(seq),{}).get('first_at')or at
                                recorded_at=instant(stamp).astimezone(timezone.utc).isoformat()
                                db.execute('INSERT OR IGNORE INTO journal_transport_receipts VALUES(?,?,?)',(seq,recorded_at,attrs['batch_id']))
                    while db.execute('SELECT 1 FROM journal_transport_receipts WHERE seq=?',(ack+1,)).fetchone():ack+=1
                    put(db,'ack',ack)
                sent={k:v for k,v in sent.items()if int(k)>ack and not db.execute('SELECT 1 FROM journal_transport_receipts WHERE seq=?',(int(k),)).fetchone()}
            for seq,attrs in rows:
                if seq<=ack or db.execute('SELECT 1 FROM journal_transport_receipts WHERE seq=?',(seq,)).fetchone():continue
                receipt=sent.get(str(seq))
                if receipt and 0<=(now-instant(receipt['last_at'])).total_seconds()<20:continue
                self.client.publish(attrs);sent[str(seq)]={'first_at':min(instant(receipt['first_at']),now).isoformat()if receipt else at,'last_at':at}
                with db:put(db,'sent',sent)
            waiting=max([(now-instant(v['first_at'])).total_seconds()for v in sent.values()]or[0])
            with db:put(db,'sent',sent);put(db,'health',{'status':'degraded'if waiting>30 else 'ok','checked_at':at,'error_code':'RECORDER_CONFIRMATION_TIMEOUT'if waiting>30 else None,'recording_wait_s':waiting})
        except Exception as error:
            with db:put(db,'health',{'status':'degraded','checked_at':at,'error_code':type(error).__name__})
        finally:store.close()
    def run(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception as error:print(json.dumps({'journal_transport_error':type(error).__name__,'device_actions':0}),flush=True)
            self.stop.wait(1)
    def start(self):
        self.thread=threading.Thread(target=self.run,name='journal-recorder',daemon=True);self.thread.start();return self
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=15)
        return not self.thread or not self.thread.is_alive()

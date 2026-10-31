"""Bezztrátové zmenšení atributů před recorderem; žádný tichý ořez podkladů."""
import base64,hashlib,json,zlib
MAX_ATTRIBUTES_BYTES=14000
MAX_UNPACKED_BYTES=2*1024*1024
ENCODING='zlib-json-v1'

class PayloadOverflow(ValueError):
    def __init__(self,message,attributes):super().__init__(message);self.attributes=attributes;self.entity_id=None

def record_overflow(store,error,at):
    from .store import pack
    store.db.execute('CREATE TABLE IF NOT EXISTS monitor_overflow_evidence(hash TEXT PRIMARY KEY,entity_id TEXT,at TEXT NOT NULL,payload BLOB NOT NULL)')
    raw=encoded(error.attributes);key=hashlib.sha256(raw).hexdigest()
    with store.db:store.db.execute('INSERT OR IGNORE INTO monitor_overflow_evidence VALUES(?,?,?,?)',(key,error.entity_id,at,pack(error.attributes)))

def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def bounded(attributes):
    raw=encoded(attributes)
    if len(raw)<=MAX_ATTRIBUTES_BYTES:return attributes
    if len(raw)>MAX_UNPACKED_BYTES:raise PayloadOverflow('MONITOR_PAYLOAD_TOO_LARGE_FULL_EVIDENCE_RETAINED',attributes)
    # Malý synchronní náhled zachová stav/platnost. Úplné atributy se neodstraňují.
    keep=('friendly_name','mode','device_actions','observed_at','software_version','collection_health','policy','status','day','issued_at','target_soc_pct','decision_reason','live_ready')
    out={k:attributes[k]for k in keep if k in attributes}
    out['packed_attributes']={'encoding':ENCODING,'sha256':hashlib.sha256(raw).hexdigest(),'unpacked_bytes':len(raw),'data':base64.b64encode(zlib.compress(raw,6)).decode()}
    if len(encoded(out))>MAX_ATTRIBUTES_BYTES:
        raise PayloadOverflow('MONITOR_PACKED_PAYLOAD_EXCEEDS_BUDGET_FULL_EVIDENCE_RETAINED',attributes)
    return out

def unpacked(attributes):
    p=attributes.get('packed_attributes')
    if not p:return attributes
    if p.get('encoding')!=ENCODING or not 0<p.get('unpacked_bytes',0)<=MAX_UNPACKED_BYTES:raise ValueError('Invalid packed monitor')
    compressed=base64.b64decode(p['data'],validate=True);dec=zlib.decompressobj();raw=dec.decompress(compressed,MAX_UNPACKED_BYTES+1)
    if len(raw)!=p['unpacked_bytes'] or not dec.eof or dec.unused_data or hashlib.sha256(raw).hexdigest()!=p['sha256']:raise ValueError('Packed monitor integrity failed')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('Packed monitor is not an object')
    return value

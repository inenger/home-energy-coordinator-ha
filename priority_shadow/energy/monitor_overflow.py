"""Lossless overflow evidence in the monitor process, with a truthful small receipt.

The archive is content-addressed, never purged, and bounded at 64 MiB. An I/O or
budget failure is explicitly reported as NOT retained; other entities still publish.
It is private diagnostic evidence, not an HA downloadable recorder payload.
"""
import hashlib,os,tempfile,zlib
from pathlib import Path
from .collector import DATA
from .monitor_payload import encoded
from .sqlite_writes import details

class OverflowArchive:
    def __init__(self,cfg):
        self.path=Path(cfg.get('monitor_evidence_dir',DATA/'monitor-overflow'))
        self.limit=64*1024*1024;self.errors={};self.total=0;self.last=None
    def begin(self):self.errors={}
    def capture(self,error,at):
        raw=encoded(error.attributes);key=hashlib.sha256(raw).hexdigest();packed=zlib.compress(raw,6)
        receipt={'entity_id':error.entity_id,'observed_at':at,'sha256':key,
                 'unpacked_bytes':len(raw),'compressed_bytes':len(packed),
                 'error_code':str(error),'retained':False,'archive_format':'zlib-json-v1'}
        temporary=None
        try:
            self.path.mkdir(parents=True,exist_ok=True,mode=0o700)
            target=self.path/(key+'.json.zlib')
            if target.exists():
                decoder=zlib.decompressobj();existing=decoder.decompress(target.read_bytes(),len(raw)+1)
                if len(existing)!=len(raw) or not decoder.eof or decoder.unused_data or hashlib.sha256(existing).hexdigest()!=key:
                    raise ValueError('MONITOR_OVERFLOW_ARCHIVE_INTEGRITY_FAILED')
            else:
                used=sum(p.stat().st_size for p in self.path.iterdir()if p.is_file())
                if used+len(packed)>self.limit:raise RuntimeError('MONITOR_OVERFLOW_ARCHIVE_BUDGET_EXCEEDED_NO_DELETE')
                fd,temporary=tempfile.mkstemp(prefix='pending-',dir=self.path)
                with os.fdopen(fd,'wb')as stream:
                    stream.write(packed);stream.flush();os.fsync(stream.fileno())
                os.chmod(temporary,0o600);os.replace(temporary,target);temporary=None
                directory=os.open(self.path,os.O_RDONLY)
                try:os.fsync(directory)
                finally:os.close(directory)
            receipt.update(retained=True,archive_key=target.name)
        except Exception as failure:
            receipt.update(archive_error=type(failure).__name__,archive_message=str(failure)[:256],storage_error=details(failure))
        finally:
            if temporary:
                try:os.unlink(temporary)
                except FileNotFoundError:pass
        self.total+=1;self.last=receipt;self.errors[error.entity_id]=receipt
        return {'mode':'observe_only','device_actions':0,'observed_at':at,
                'payload_status':'overflow_evidence_retained'if receipt['retained']else'overflow_evidence_not_retained',
                'overflow_evidence':receipt,'full_payload_in_recorder':False}
    def health(self):
        value={'overflow_count':self.total,'last_overflow':self.last,'overflow_entities':dict(self.errors)}
        if self.errors:value.update(status='degraded',error_code='MONITOR_PAYLOAD_OVERFLOW',stage='monitor_preparation')
        return value

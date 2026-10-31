"""Migrace původní evidence nesmí vytvořit prázdnou historii ani přenést kód."""
import tempfile,unittest,json,sqlite3,hashlib
from pathlib import Path
from unittest.mock import patch
from energy import portable
class AuxiliaryMigrationTests(unittest.TestCase):
 def seed(self,root,files):
  root.mkdir();db=root/'evidence.sqlite';con=sqlite3.connect(db);con.execute('CREATE TABLE evidence(value)');con.execute('INSERT INTO evidence VALUES(123)');con.commit();con.close();aux=root/'migration-aux';aux.mkdir();hashes={}
  for name,body in files.items():
   raw=json.dumps(body).encode();(aux/name).write_bytes(raw);hashes[name]=hashlib.sha256(raw).hexdigest()
  (root/'migration-aux.json').write_text(json.dumps({'format':'evidence-aux-v1','files':hashes}));return db
 def test_database_and_auxiliary_settings_preserved_then_existing_database_kept(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);source=root/'source';db=self.seed(source,{'telemetry-overrides.json':{'include':['sensor.synthetic']},'analytics.json':{'state':'synthetic'}});target=root/'destination/evidence.sqlite'
   with patch.object(portable,'PORTABLE_DIR',source),patch.object(portable,'PORTABLE_DB',db):
    result=portable.restore_if_empty(target);self.assertEqual(result['status'],'restored');self.assertEqual(json.loads((target.parent/'telemetry-overrides.json').read_text()),{'include':['sensor.synthetic']});con=sqlite3.connect(target);self.assertEqual(con.execute('SELECT value FROM evidence').fetchone()[0],123);con.close();self.assertEqual(portable.restore_if_empty(target)['status'],'existing_database_kept')
 def test_tampered_auxiliary_fails_before_target_database_exists(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);source=root/'source';db=self.seed(source,{'analytics.json':{}});(source/'migration-aux/analytics.json').write_text('tampered');target=root/'destination/evidence.sqlite'
   with patch.object(portable,'PORTABLE_DIR',source),patch.object(portable,'PORTABLE_DB',db):self.assertRaises(ValueError,portable.restore_if_empty,target)
   self.assertFalse(target.exists())
 def test_unknown_path_or_code_file_is_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);source=root/'source';db=self.seed(source,{});target=root/'destination/evidence.sqlite';(source/'migration-aux.json').write_text(json.dumps({'format':'evidence-aux-v1','files':{'../runtime.py':'0'*64}}))
   with patch.object(portable,'PORTABLE_DIR',source),patch.object(portable,'PORTABLE_DB',db):self.assertRaises(ValueError,portable.restore_if_empty,target)
   self.assertFalse(target.exists())

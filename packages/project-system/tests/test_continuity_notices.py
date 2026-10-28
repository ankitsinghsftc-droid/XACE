import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from tools.continuity_notices import verify_notices
class NoticeIntegrityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  (self.root/'LICENSE.txt').write_text('Synthetic test attribution, not a real license grant.')
  h=hashlib.sha256((self.root/'LICENSE.txt').read_bytes()).hexdigest()
  self.value=dict(schema='xace.continuity_notices.v1',notice_inventory_complete=True,missing=[],public_redistribution_approved=False,files={'LICENSE.txt':h},packages=[dict(source='registry:test',files=[dict(path='LICENSE.txt',sha256=h)])]);self.save()
 def save(self):(self.root/'notices.manifest.json').write_text(json.dumps(self.value))
 def test_valid_inventory_is_not_public_release_approval(self):self.assertFalse(verify_notices(self.root)['public_redistribution_approved'])
 def test_modified_notice_refused(self):
  (self.root/'LICENSE.txt').write_text('changed')
  with self.assertRaises(ValueError):verify_notices(self.root)
 def test_missing_dependency_notice_cannot_be_hidden(self):
  self.value['packages'][0]['files']=[];self.save()
  with self.assertRaises(ValueError):verify_notices(self.root)
 def test_unlisted_nested_manifest_refused(self):
  (self.root/'nested').mkdir();(self.root/'nested/notices.manifest.json').write_text('{}')
  with self.assertRaises(ValueError):verify_notices(self.root)
 def test_inventory_cannot_self_certify_public_rights(self):
  self.value['public_redistribution_approved']=True;self.save()
  with self.assertRaises(ValueError):verify_notices(self.root)

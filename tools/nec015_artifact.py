"""Validate retained proof packages or checked creator-build receipts before reuse."""
import json
from tools.nec015_package_proof import sha

def verified(source):
 root=source.parent.parent
 if (root/'receipt.json').is_file():
  receipt=json.loads((root/'receipt.json').read_text(encoding='utf-8'))
  assert receipt['schema']=='xace.unreal.native_build.v1' and receipt['status']=='built-not-certified'
  files=[p for p in sorted(source.rglob('*')) if p.is_file()]
  assert all(p.resolve().is_relative_to(source) for p in files),'Artifact link escapes root'
  assert receipt['files'] and {p.relative_to(source).as_posix():sha(p) for p in files}==receipt['files'],'Checked artifact changed'
 else:assert json.loads((root/'proof.json').read_text(encoding='utf-8'))['ok']

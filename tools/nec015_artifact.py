"""Validate retained proof packages or checked creator-build receipts before reuse."""
import json
from tools.nec015_package_proof import sha

def verified(source):
 root=source.parent.parent
 if (root/'receipt.json').is_file():
  receipt=json.loads((root/'receipt.json').read_text(encoding='utf-8'))
  assert receipt['schema']=='xace.unreal.native_build.v1' and receipt['status']=='built-not-certified'
  assert receipt['files'] and all((source/name).resolve().is_relative_to(source) and (source/name).is_file() and sha(source/name)==value for name,value in receipt['files'].items()),'Checked artifact changed'
 else:assert json.loads((root/'proof.json').read_text(encoding='utf-8'))['ok']

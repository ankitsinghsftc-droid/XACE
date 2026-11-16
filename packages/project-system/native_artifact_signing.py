"""Create-only signed native delivery copies with retained unsigned inventories.

Original editor build receipts remain immutable. Derived receipts are not a
native Play, clean-machine, store, publisher-rights or human certification.
"""
import base64,copy,json,shutil
from pathlib import Path
from authoring_identity import require,canonical
from continuity_contract import portable_path
from release_handoff import tree,sha
from native_executor_contract import digest
from signed_executor import derive_launcher,publisher_policy
from signed_release import persistent_output
from pe_derivation import verify as verify_pe
from windows_authenticode import verify as verify_signature

MANIFEST='XACE-SIGNED-DELIVERY.json'

def finalize_native(source,output,*,engine,expected_unsigned_inventory_sha256,policy,expected_policy_sha256,replacements):
 source=Path(source).resolve(strict=True);output=persistent_output(output,source);require(engine in {'godot','unity','unreal'},'Declared engine required');before=tree(source)
 require(MANIFEST not in before and digest(before)==expected_unsigned_inventory_sha256,'Unsigned inventory differs from independently reviewed build')
 policy=publisher_policy(policy);require(digest(policy)==expected_policy_sha256,'Publisher policy differs from independent approval')
 require(type(replacements) is dict and replacements,'Explicit signed executable replacements required')
 derivations={}
 for name,path in sorted(replacements.items()):
  portable_path(name);require(name in before and name.lower().endswith('.exe'),'Only existing explicitly selected native executables may be signed')
  derivations[name]=derive_launcher(source/name,path,expected_unsigned_sha256=before[name]['sha256'],policy=policy)
 cooked=[name for name in before if name.endswith('/XACEBuild.json') or name=='XACEBuild.json'];original_cooked=None
 if engine=='unreal':
  require(len(cooked)==1,'Unique checked Unreal cooked inventory required');original_cooked=dict(path=cooked[0],bytes_base64=base64.b64encode((source/cooked[0]).read_bytes()).decode('ascii'));record=json.loads((source/cooked[0]).read_bytes());require(record.get('schema')=='xace.unreal.cooked_files.v1','Checked Unreal cooked inventory required')
  parent=(source/cooked[0]).parent;actual=tree(parent);del actual['XACEBuild.json'];require({n:r['sha256'] for n,r in actual.items()}==record['files'],'Original Unreal cooked files differ')
 require(tree(source)==before,'Original native build changed during preflight');shutil.copytree(source,output)
 for name,path in replacements.items():
  raw=Path(path).read_bytes();require(__import__('hashlib').sha256(raw).hexdigest()==derivations[name]['executable_sha256'],'Signed file changed after verification')
  (output/name).write_bytes(raw)
 if original_cooked:
  path=output/original_cooked['path'];record=json.loads(base64.b64decode(original_cooked['bytes_base64']));files=tree(path.parent);del files['XACEBuild.json'];
  if path.parent==output:files.pop(MANIFEST,None)
  record['files']={n:r['sha256'] for n,r in files.items()};path.write_bytes(canonical(record))
 receipt=dict(schema='xace.signed_native_delivery.v1',engine=engine,unsigned_inventory=before,unsigned_inventory_sha256=expected_unsigned_inventory_sha256,publisher_policy=policy,publisher_policy_sha256=expected_policy_sha256,signed_executables=derivations,original_cooked_receipt=original_cooked,files=tree(output),status='derived_not_certified',native_gameplay_verified=False,clean_machine_certified=False,release_certified=False)
 with (output/MANIFEST).open('xb') as stream:stream.write(canonical(receipt))
 verify_native(output,sha(output/MANIFEST));require(tree(source)==before,'Original native build changed');return receipt

def verify_native(root,expected_receipt_sha256):
 root=Path(root);actual=tree(root);require(MANIFEST in actual and actual.pop(MANIFEST)['sha256']==expected_receipt_sha256,'Delivery receipt differs from independent pin')
 receipt=json.loads((root/MANIFEST).read_bytes());fields={'schema','engine','unsigned_inventory','unsigned_inventory_sha256','publisher_policy','publisher_policy_sha256','signed_executables','original_cooked_receipt','files','status','native_gameplay_verified','clean_machine_certified','release_certified'}
 require(type(receipt) is dict and set(receipt)==fields and receipt['schema']=='xace.signed_native_delivery.v1' and receipt['engine'] in {'godot','unity','unreal'},'Exact native delivery contract required')
 require(receipt['status']=='derived_not_certified' and all(receipt[k] is False for k in ['native_gameplay_verified','clean_machine_certified','release_certified']),'Derivation is not native/release certification')
 require(actual==receipt['files'] and digest(receipt['unsigned_inventory'])==receipt['unsigned_inventory_sha256'],'Native delivery inventory changed')
 policy=publisher_policy(receipt['publisher_policy']);require(digest(policy)==receipt['publisher_policy_sha256'],'Publisher policy identity changed');original=receipt['unsigned_inventory'];allowed=set()
 require(type(receipt['signed_executables']) is dict and receipt['signed_executables'],'Explicit signed native executables required')
 for name,d in receipt['signed_executables'].items():
  portable_path(name);require(name in original and name.lower().endswith('.exe') and type(d) is dict and set(d)=={'schema','unsigned_sha256','executable_sha256','unsigned_length','unsigned_pe_checksum','signer_certificate_sha256'} and d['schema']=='xace.signed_launcher.v1','Exact PE derivation required')
  require(d['unsigned_sha256']==original[name]['sha256'] and d['executable_sha256']==actual[name]['sha256'] and d['signer_certificate_sha256'] in policy['allowed_signer_certificate_sha256'],'Unapproved native PE identity')
  raw=(root/name).read_bytes();verify_pe(raw,unsigned_sha256=d['unsigned_sha256'],unsigned_length=d['unsigned_length'],unsigned_pe_checksum=d['unsigned_pe_checksum']);report=verify_signature(root/name,d['signer_certificate_sha256']);require(report['executable_sha256']==actual[name]['sha256'],'Native file changed during signature verification');allowed.add(name)
 cooked=receipt['original_cooked_receipt']
 if receipt['engine']=='unreal':
  require(type(cooked) is dict and set(cooked)=={'path','bytes_base64'},'Retained Unreal cooked receipt required');name=portable_path(cooked['path']);require(name in original,'Unknown cooked inventory')
  raw=base64.b64decode(cooked['bytes_base64'],validate=True);require(__import__('hashlib').sha256(raw).hexdigest()==original[name]['sha256'],'Original cooked receipt identity changed')
  expected=json.loads(raw);require(expected.get('schema')=='xace.unreal.cooked_files.v1','Unknown cooked receipt');parent=(root/name).parent;files=tree(parent);del files['XACEBuild.json'];
  if parent==root:files.pop(MANIFEST,None)
  expected['files']={n:r['sha256'] for n,r in files.items()};require((root/name).read_bytes()==canonical(expected),'Reissued cooked inventory differs');allowed.add(name)
 else:require(cooked is None,'Unexpected cooked inventory')
 require(set(actual)==set(original) and all(actual[n]==r for n,r in original.items() if n not in allowed),'Signing changed unrelated native files')
 return receipt

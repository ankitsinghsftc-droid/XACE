"""Create-only creator finalization after externally authorized signing.

Never invokes a signing service, modifies keys/stores or edits an old receipt.
A completed common release still needs explicitly approved native rebuild/cook
and final engine signing/inventories; this is not an automatic release gate.
"""
import json,subprocess
from pathlib import Path
from authoring_identity import require,canonical
import native_executor_contract as executor
import playable_package as pp
from signed_executor import derive,derive_launcher,publisher_policy
from release_handoff import tree,sha
from continuity_contract import plain

def persistent_output(path,source):
    path=Path(path).absolute();source=Path(source).resolve(strict=True)
    require(not path.exists() and not path.is_relative_to(source) and not source.is_relative_to(path),'Fresh output outside original source required')
    require(not any(p.casefold() in {'target','build','dist','tmp','temp','.cache'} for p in path.parts),'Persistent creator output required')
    for parent in path.parents:
        if parent.exists():plain(parent)
    return path

def native_verify(verifier,expected_sha,source,pin):
    require(sha(verifier)==expected_sha,'Native verifier differs from trusted host binary')
    result=subprocess.run([str(verifier),'--native-verify','--source',str(source),'--expected',pin],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:record=json.loads(result.stdout)
    except (ValueError,UnicodeDecodeError):record={}
    require(result.returncode==0 and record.get('ok') is True and record.get('state')=='verified','Native preflight refused: '+result.stdout.decode(errors='replace')[:1000])
    require(sha(verifier)==expected_sha,'Native verifier changed during preflight')
    return record

def finalize(source,output,*,expected_release_sha256,policy,expected_policy_sha256,unsigned_launcher,expected_unsigned_launcher_sha256,signed_launcher,signed_executor,verifier,expected_verifier_sha256,version):
    source=Path(source).resolve(strict=True);output=persistent_output(output,source)
    verifier=Path(verifier).resolve(strict=True);before=tree(source)
    require(sha(source/'native-release.json')==expected_release_sha256,'Unsigned release differs from trusted identity')
    policy=publisher_policy(policy);require(executor.digest(policy)==expected_policy_sha256,'Publisher policy differs from independent approval')
    native_verify(verifier,expected_verifier_sha256,source,expected_release_sha256)
    native=json.loads((source/'native-release.json').read_bytes());require(native['schema']=='xace.native_release.v1','Unsigned v1 release required')
    original=json.loads((source/'executor-receipt.json').read_bytes());compiled,_=pp.compiled_artifacts(json.loads((source/'package/game.cgs.json').read_bytes()))
    original_support=executor.admit(original,expected_receipt_digest=native['executor_receipt_sha256'],executable=source/'package/runtime/xace_runtime.exe',required_capabilities=native['required_capabilities'],expected_compatibility=native['compatibility'],package=compiled)
    original_files={name:(source/'package'/name).read_bytes() for name in tree(source/'package')};old_manifest=pp.verify_files(original_files,original_support)
    receipt=derive(original,expected_unsigned_digest=native['executor_receipt_sha256'],unsigned_executable=source/'package/runtime/xace_runtime.exe',signed_executable=signed_executor,policy=policy)
    launcher=derive_launcher(unsigned_launcher,signed_launcher,expected_unsigned_sha256=expected_unsigned_launcher_sha256,policy=policy)
    support=executor.admit(receipt,expected_receipt_digest=executor.digest(receipt),executable=signed_executor,required_capabilities=native['required_capabilities'],expected_compatibility=native['compatibility'],package=compiled,publisher_policy=policy)
    archive=pp.build_package(json.loads(original_files['game.cgs.json']),original_files['execution_plan.json'],Path(signed_executor).read_bytes(),support,package_id=old_manifest['package_id'],version=version,presentation_files={n:b for n,b in original_files.items() if n.startswith('presentation/')})
    files=pp.read_archive(archive);pp.verify_files(files,support)
    payload={**{'package/'+n:b for n,b in files.items()},'executor-receipt.json':canonical(receipt),'xace-player-launcher.exe':Path(signed_launcher).read_bytes()}
    require(executor.sha(payload['xace-player-launcher.exe'])==launcher['executable_sha256'],'Signed launcher changed after verification')
    resources=[]
    # Preserve every non-package sidecar, including notices, and bind it into
    # the new closure. Never silently discard an unlisted original sidecar.
    for path in before:
        if path.startswith('package/') or path in {'executor-receipt.json','native-release.json','xace-player-launcher.exe'}:continue
        require(path not in payload,'Ambiguous native resource closure');payload[path]=(source/path).read_bytes();resources.append(dict(path=path,size=len(payload[path]),sha256=executor.sha(payload[path])))
    resources.append(dict(path='xace-player-launcher.exe',size=len(payload['xace-player-launcher.exe']),sha256=launcher['executable_sha256']))
    native.update(schema='xace.native_release.v2',executor_receipt_sha256=executor.digest(receipt),package_manifest_sha256=executor.sha(files['playable.manifest.json']),publisher_policy=policy,launcher_derivation=launcher,resources=sorted(resources,key=lambda r:r['path']))
    payload['native-release.json']=canonical(native)
    require(tree(source)==before,'Source changed before signed finalization')
    output.mkdir(parents=True,exist_ok=False)
    for name,data in payload.items():
        pp.safe_path(name);dest=output/name;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as stream:stream.write(data)
    report=native_verify(verifier,expected_verifier_sha256,output,executor.sha(payload['native-release.json']))
    require(tree(source)==before,'Original source changed during finalization')
    return dict(schema='xace.signed_common_release_finalization.v1',common_release_verified=True,source_release_sha256=expected_release_sha256,release_sha256=report['release'],publisher_policy_sha256=expected_policy_sha256,executor_receipt_sha256=native['executor_receipt_sha256'],launcher_sha256=launcher['executable_sha256'],source_unchanged=True,native_engine_rebuild_required=True,final_native_engine_signing_required=True,clean_machine_certified=False,release_certified=False)

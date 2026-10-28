"""Reviewed create-only detach. Never mutates the original native project.

retain-runtime keeps all runtime/adapter code in an independent native workspace.
remove-adapter removes only hash-owned integration in the independent copy;
XACE gameplay is not promised in that mode. Archives and failed copies survive.
"""
from pathlib import Path
import hashlib
from continuity_contract import canonical,require,portable_path
from continuity_archive import verify_archive,restore_archive,parents_plain
from adapter_installation import uninstall_adapter

def review_detach(archive,expected_sha256,destination,*,mode='retain-runtime',native_root=None,engine=None):
    manifest=verify_archive(Path(archive),expected_sha256)
    require(manifest['declared_closure_complete'],'detach requires reviewed complete declared closure')
    destination=Path(destination).absolute();parents_plain(destination.parent)
    require(not destination.exists(),'detach destination must be new')
    require(mode in {'retain-runtime','remove-adapter'},'unsupported detach mode')
    if mode=='remove-adapter':
        require(engine in {'godot','unity','unreal'},'engine required')
        require(any(r['key']==native_root and r['role']=='native-project' for r in manifest['roots']),'native root required')
    review=dict(schema='xace.continuity_detach_review.v1',archive_sha256=expected_sha256,manifest_sha256=manifest['content_sha256'],destination=str(destination),mode=mode,native_root=native_root,engine=engine,original_untouched=True,runtime_required=mode=='retain-runtime',runtime_free_gameplay_export=False)
    review['review_sha256']=hashlib.sha256(canonical(review)).hexdigest();return review

def apply_detach(archive,review,approved_review_sha256):
    current=review_detach(archive,review['archive_sha256'],review['destination'],mode=review['mode'],native_root=review['native_root'],engine=review['engine'])
    require(current==review and approved_review_sha256==current['review_sha256'],'explicit current review approval required')
    destination=Path(review['destination']);restored=restore_archive(Path(archive),review['archive_sha256'],destination)
    report=None
    if review['mode']=='remove-adapter':
        report=uninstall_adapter(engine_project_root=destination/'payload'/review['native_root'],engine_type=review['engine'])
    result=dict(schema='xace.continuity_detach_receipt.v1',review=review,restore=restored,adapter_report=report,ok=report is None or report['ok'],original_untouched=True,archive_retained=True,rebuild_verified=False)
    with (destination/'detach.receipt.json').open('xb') as output:output.write(canonical(result))
    return result

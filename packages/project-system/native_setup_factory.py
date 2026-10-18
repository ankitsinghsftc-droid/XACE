"""Explicit native factory execution in a new, durable host-selected stage.

Template bytes and executable pins are supplied by trusted host configuration,
never a browser request. No existing directory is reused or cleaned.
"""
import os,subprocess
from pathlib import Path
from authoring_identity import require,canonical
from authoring_transaction_files import confined,durable,sha,load_json
from native_setup_bundle import NativeSetupBundle
from native_editor_gateway import NativeEditorGateway
from native_setup_stage import VerifiedNativeSetupStage
from native_setup_plan import NativeSetupPlan,plan_setup


def create_native_setup_stage(plan,cgs,stage_root,*,template_files,gateway_config):
    require(type(plan) is NativeSetupPlan,'typed setup plan required')
    data=plan.to_dict();expected=plan_setup(cgs,**{k:data[k] for k in ['engine','namespace_id','project_id','branch_id','mode_id']})
    require(expected.payload==plan.payload,'setup plan/source changed')
    root=Path(stage_root).absolute();engine=data['engine']
    require(not root.exists(),'fresh stage directory required')
    forbidden={'target','build','dist','tmp','temp','.cache','library','intermediate','.godot'}
    require(not {p.casefold() for p in root.parts}&forbidden,'persistent stage location required')
    require(gateway_config['engine']==engine,'factory engine mismatch')
    exe=Path(gateway_config['executable'])
    require(sha(exe.read_bytes())==gateway_config['executable_sha256'],'pinned editor mismatch')
    require(type(template_files) is dict and template_files and all(type(b) is bytes for b in template_files.values()),'host template bytes required')
    for p,h in gateway_config['plugin_hashes'].items():require(p in template_files and sha(template_files[p])==h,'template authoring implementation differs')
    if engine=='godot':require('addons/xace_authoring/native_setup_entry.gd' in template_files,'Godot factory entry missing')
    require(not any('xacegenerated' in p.casefold() for p in template_files),'template contains generated world')
    # Validate path policy before the first write, using the existing parent.
    require(root.parent.is_dir(),'persistent stage parent must exist')
    NativeSetupBundle(root.parent,engine=engine,allowed_paths=list(template_files))
    root.mkdir(exist_ok=False)
    for p,b in sorted(template_files.items()):durable(confined(root,p),b)
    spec=canonical(plan.to_dict()['native_request']);journal=root/'.xace'
    durable(journal/'spec.json',spec)
    durable(journal/'native-setup-approved.json',canonical(dict(digest=sha(spec),stage_root=root.as_posix())))
    restore=None
    if engine=='godot':
        cfg=confined(root,'addons/xace_authoring/plugin.cfg');original=cfg.read_bytes()
        require(original.count(b'authoring_plugin.gd')==1,'registered Godot plugin configuration required')
        restore=(cfg,original);durable(cfg,original.replace(b'authoring_plugin.gd',b'native_setup_entry.gd'))
        argv=[str(exe),'--headless','--editor','--path',str(root)]
    elif engine=='unity':argv=[str(exe),'-batchmode','-nographics','-projectPath',str(root),'-executeMethod','Xace.Authoring.Editor.UnityNativeSetup.Run','-logFile',str(journal/'setup-editor.log')]
    else:argv=[str(exe),str(confined(root,gateway_config['project_file'])),'-run=XaceNativeSetup','-unattended','-nop4','-nosplash','-NullRHI','-NoSound','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={journal/"setup-editor.log"}']
    durable(journal/'setup-command.json',canonical(argv))
    try:
        with (journal/'setup-process.log').open('wb') as log:
            process=subprocess.run(argv,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=900 if engine=='unity' else 240,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        result=load_json(journal/'result-create.json')
        require(process.returncode==0 and result.get('result',{}).get('inventory'),'native factory failed; inspect retained stage logs')
    finally:
        if restore:durable(*restore)
    return VerifiedNativeSetupStage(plan,cgs,NativeEditorGateway(root,**gateway_config))

"""Relocated cooked gameplay and physical native-resource tamper refusal."""
from pathlib import Path
import json,shutil,subprocess,os,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_unreal_existing_play import files
from tools.nec013_unity_player_proof import gone
from tools.nec015_package_proof import sha

def main(source,out):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec017') and out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert json.loads((source/'editor-proof.json').read_bytes())['ok'] and 'BUILD SUCCESSFUL' in (source/'package.log').read_text(encoding='utf-8');assert shutil.disk_usage(ROOT).free>3*1024**3
 original=source/'archive/Windows';before=files(original);out.mkdir(parents=True);cases={}
 reuse=Path(sys.argv[3]).resolve() if len(sys.argv)>3 else None
 if reuse is not None:assert reuse.is_relative_to(ROOT/'evidence/nec017') and reuse.is_dir()
 relative='release/package/presentation/unreal/Content/CrateMesh.uasset'
 for mode in ['relocated','tampered']:
  game=(reuse if reuse is not None else out)/mode
  if reuse is None:shutil.copytree(original,game)
  installation=files(game)
  if reuse is not None:
   expected=dict(before)
   if mode=='tampered':expected['NEC015/'+relative]=sha(game/'NEC015'/relative)
   assert installation==expected,'Retained artifact differs outside declared tamper'
   (out/(mode+'-reuse.json')).write_text(json.dumps(dict(source=str(game),files=installation),indent=2))
  if mode=='tampered' and reuse is None:
   target=(game/'NEC015'/relative).resolve();assert target.is_relative_to(game.resolve()) and target.is_file();data=target.read_bytes();assert data;(out/'original-resource.uasset').write_bytes(data);target.write_bytes(data[:-1]+bytes([data[-1]^1]));installation=files(game)
   (out/'tamper.json').write_text(json.dumps(dict(path=relative,original_sha256=sha(out/'original-resource.uasset'),tampered_sha256=sha(target),manifest_not_rewritten=True),indent=2))
  env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/(mode+'-user-data'));report=out/(mode+'.json');command=[str(game/'NEC015/Binaries/Win64/NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-NEC017ExistingReport={report}','-abslog='+str(out/(mode+'-engine.log'))]
  (out/(mode+'-command.json')).write_text(json.dumps(command,indent=2))
  with (out/(mode+'.log')).open('wb') as log:r=subprocess.run(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
  value=json.loads(report.read_text(encoding='utf-8-sig'));assert files(game)==installation
  if mode=='relocated':assert r.returncode==0 and value['ok'] and value['packaged'] and value['objects']==50 and gone(value['runtime_pid']) and gone(value['owner_pid'])
  # Unreal graceful main-loop exit may return0 even after RequestExitWithStatus(false,1).
  # Require the exact application refusal, zero authority processes, stable bytes,
  # and an orderly process exit; a crash/other status is never a refusal pass.
  else:assert r.returncode in [0,1] and not value['ok'] and value['error']=='Cooked file mismatch: '+relative and value['runtime_pid']==0 and value['owner_pid']==0
  cases[mode]=dict(report=value,exit_code=r.returncode,installation_unchanged=True)
 assert files(original)==before
 (out/'proof.json').write_text(json.dumps(dict(ok=True,cases=cases,original_source_unchanged=True,clean_machine=False,physical_resource_integrity_verified=True,refusal_verdict_requires_structured_report=True,nonzero_exit_alone_not_required=True,full_nec017_complete=False),indent=2));print('Relocated Unreal gameplay and tampered loose uasset refusal passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

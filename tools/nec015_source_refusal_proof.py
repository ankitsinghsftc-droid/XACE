"""Native Unreal uncooked game preflight against approved source and tampered copies."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main(source,out):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec015') and out.is_relative_to(ROOT/'evidence/nec015') and not out.exists()
 assert (source/'XACEApproval.json').is_file();out.mkdir(parents=True);results={}
 for case in ['approved','changed','added','missing']:
  caseout=out/case;caseout.mkdir();project=caseout/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('Intermediate','Saved','DerivedDataCache'))
  if case=='changed':
   p=project/'NEC015.uproject';p.write_bytes(p.read_bytes()+b'\n')
  elif case=='added':(project/'unapproved-source.txt').write_text('unapproved',encoding='utf-8')
  elif case=='missing':
   p=project/'release/package/world.json';assert p.is_relative_to(caseout);p.rename(caseout/'preserved-world.json')
  cmd=['C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe',str(project/'NEC015.uproject'),'/Game/NativeProof','-game','-unattended','-d3d11','-RenderOffscreen',f'-XaceNativePreflight={caseout/"preflight.json"}',f'-abslog={caseout/"engine.log"}']
  env=dict(os.environ);env['LOCALAPPDATA']=str(caseout/'user-data');(caseout/'command.json').write_text(json.dumps(cmd),encoding='utf-8')
  with (caseout/'run.log').open('xb') as f:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  result=json.loads((caseout/'preflight.json').read_text(encoding='utf-8-sig'));assert not result['authority_started'] and not result['cooked'],result
  if case=='approved':assert result['ok'] and r.returncode==0,result
  else:assert not result['ok'] and r.returncode!=0 and 'Native source' in result['error'],result
  results[case]=result
 (out/'proof.json').write_text(json.dumps(dict(ok=True,actual_native_uncooked_preflight=True,cases=results,dirty_editor_case=False),indent=2),encoding='utf-8');print(json.dumps(results))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

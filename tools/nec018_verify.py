"""Fresh NEC018 focused/regression/syntax receipts; no Windows policy changes."""
from pathlib import Path
import hashlib,json,subprocess,sys,os
ROOT=Path(__file__).resolve().parents[1]
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 for script in sorted((ROOT/'tools').glob('nec018*.py')):compile(script.read_bytes(),str(script),'exec')
 files=sorted({*list((ROOT/'packages/project-system').rglob('*.py')),*list((ROOT/'packages/schema-factory/src').rglob('*.py')),*list((ROOT/'packages/gde/src').rglob('*.py')),*list((ROOT/'tools').glob('nec018*')),*list((ROOT/'packages/player-launcher/src').glob('*.rs')),ROOT/'Cargo.toml',ROOT/'Cargo.lock'});pins={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};(out/'source-pins.json').write_text(json.dumps(pins,indent=2));results=[]
 env=dict(os.environ);env['CARGO_TARGET_DIR']='C:/Users/ankit/XACE-Recovery/build-output/cargo'
 commands=[('project-system',[sys.executable,'-B','-m','unittest','discover','-s','packages/project-system/tests','-v']),('schema-factory',[sys.executable,'-B','-m','pytest','packages/schema-factory/src/tests','-q','-p','no:cacheprovider']),('native-launcher',['cargo','test','-p','xace-player-launcher','--locked','--offline']),('session-relay',['cargo','test','-p','xace-session-relay','--locked','--offline'])]
 for label,command in commands:
  with (out/(label+'.log')).open('wb') as log:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
  results.append(dict(name=label,command=command,returncode=result.returncode));assert result.returncode==0,label+' failed; evidence retained';print(label+' passed',flush=True)
 script="$ErrorActionPreference='Stop';foreach($name in @('nec018_collect_environment.ps1','nec018_run_native_checks.ps1')){$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) ('tools/'+$name)),[ref]$t,[ref]$e)|Out-Null;if($e.Count){throw ($e|Out-String)}};Write-Output 'PowerShell parse passed; policy unchanged'"
 command=['powershell.exe','-NoProfile','-NonInteractive','-Command',script]
 with (out/'powershell-syntax.log').open('wb') as log:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
 assert result.returncode==0,'PowerShell syntax failed';assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==v for name,v in pins.items()),'Sources changed during verification';(out/'result.json').write_text(json.dumps(dict(ok=True,source_stable=True,tests=results,powershell_syntax_passed=True,external_certification=False),indent=2));print('Stable source and PowerShell syntax checks passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))

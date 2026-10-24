"""Relocate and execute an actual Unity build with no development tools on PATH.
Same-machine proof only: neither an ACL-enforced read-only nor a clean-machine claim.
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def inventory(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
def main(source,out):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec013') and out.is_relative_to(ROOT/'evidence/nec013') and not out.exists()
 out.mkdir(parents=True);game=out/'relocated game';shutil.copytree(source,game);before=inventory(game)
 env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'user-data')
 command=[str(game/'NativeGame.exe'),'-batchmode','-nographics','-xacePlayerReport',str(out/'player.json'),'-logFile',str(out/'player.log')]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
 with (out/'run.txt').open('wb') as log:run=subprocess.run(command,env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 report=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));report.update(exit_code=run.returncode,install_unchanged=before==inventory(game),clean_machine=False,acl_readonly=False)
 report['ok']=report['ok'] and run.returncode==0 and report['install_unchanged']
 (out/'inventory.json').write_text(json.dumps(before,indent=2),encoding='utf-8');(out/'proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));assert report['ok']
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))

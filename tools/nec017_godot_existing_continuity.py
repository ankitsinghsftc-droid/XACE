"""Create-only archive/restore/rebuild of the imported supported Godot fixture."""
from pathlib import Path
import json,shutil,subprocess,os,sys,tomllib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from continuity_contract import ArchiveRequest,SourceRoot,Dependency,Checkpoint,Prerequisite,Omission,canonical,require
from continuity_archive import create_archive,restore_archive,verify_archive,file_hash
from tools.continuity_notices import verify_notices
from tools.nec014_export import export,inventory
from tools.nec014_export_proof import GODOT
from tools.nec013_unity_player_proof import gone

def longpath(path):return Path('\\\\?\\'+str(Path(path).resolve()))

def main(out):
 out=out.resolve();require(out.is_relative_to(ROOT/'evidence/nec017') and not out.exists(),'fresh persistent output required');require(shutil.disk_usage(ROOT).free>4*1024**3,'4GiB reserve')
 out.mkdir(parents=True);source=ROOT/'evidence/nec017/20261106/godot-existing-play-b';before=inventory(source/'project');inputs=out/'inputs';inputs.mkdir()
 native=inputs/'native';shutil.copytree(source/'project',native,ignore=shutil.ignore_patterns('.godot','XACEApproval.json'))
 template=ROOT/'evidence/nec014/20261025/export-preflight-f/windows_release_x86_64.exe';shutil.copyfile(template,native/'continuity-template.exe')
 preset=(native/'export_presets.cfg').read_text(encoding='utf-8');require(template.as_posix() in preset,'Expected pinned template absent');(native/'export_presets.cfg').write_text(preset.replace(template.as_posix(),'res://continuity-template.exe'),encoding='utf-8')
 executor=longpath(inputs/'executor');executor.mkdir();receipt=json.loads((native/'release/executor-receipt.json').read_bytes());members=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['members']
 for name in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'):
  if name in ['Cargo.toml','Cargo.lock'] or any(name.startswith(member+'/') for member in members):
   p=executor/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
 recovered=[]
 for name,expected in receipt['source_files'].items():
  p=executor/name
  if not p.exists() or file_hash(p)!=expected:
   raw=subprocess.check_output(['git','show','9d16fb6^:'+name],cwd=ROOT)
   variants=[('git-blob',raw),('CRLF',raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))]
   match=next(((kind,data) for kind,data in variants if __import__('hashlib').sha256(data).hexdigest()==expected),None);require(match is not None,'Exact pinned source missing: '+name)
   p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(match[1]);recovered.append(dict(path=name,git_ref='9d16fb6^',encoding=match[0],sha256=expected))
  require(file_hash(p)==expected,'Pinned source differs: '+name)
 (executor/'original-executor-receipt.json').write_bytes(canonical(receipt));(out/'source-provenance.json').write_bytes(canonical(dict(all_receipt_sources_exact=True,count=len(receipt['source_files']),historical_blobs=recovered,current_source_not_substituted=True)))
 project=inputs/'project';project.mkdir();shutil.copyfile(native/'release/package/game.cgs.json',project/'game.cgs.json')
 history=longpath(inputs/'history');history.mkdir();shutil.copytree(longpath(ROOT/'evidence/nec017/20261105/godot-material-publish-a/project/.xace'),history/'authoring')
 shutil.copytree(source/'user-data',history/'native-user-data')
 checkpoint=history/'protected-checkpoint.json';checkpoint.write_bytes(canonical(dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),native_play_proof_sha256=file_hash(source/'proof.json'),source_provenance_sha256=file_hash(out/'source-provenance.json'),executor_sha256=receipt['executable_sha256'])))
 notices=ROOT/'evidence/nec016/20261028/notices-a';verify_notices(notices)
 omissions=tuple(Omission('history',p.relative_to(history).as_posix(),'Ephemeral authentication credential; fresh admission issues a new one',False) for p in history.rglob('*') if p.is_file() and p.name in ['ticket.json','native-ticket.json','session-ticket.json'])
 req=ArchiveRequest('nec017.imported.godot',(SourceRoot('project','project-source',project),SourceRoot('native','native-project',native),SourceRoot('executor','executor-source',executor),SourceRoot('runtime','runtime',native/'release'),SourceRoot('history','history',history),SourceRoot('notices','notices',notices)),(Dependency('private engineering notice inventory','payload/notices/notices.manifest.json'),),(Checkpoint('payload/history/protected-checkpoint.json',file_hash(checkpoint)),),(Prerequisite('Godot','4.6.3 stable Windows x64','Official installed editor; exact export template archived.'),Prerequisite('Rust/MSVC','pinned receipt toolchain and Cargo.lock','Exact executor sources and original two-build reproducibility receipt archived. Install/provision locked dependencies to rebuild; not bundled or downloaded here.')),omissions,True)
 archive=out/'continuity.zip';created=create_archive(req,archive);(out/'archive-receipt.json').write_bytes(canonical(created));verified=verify_archive(archive,created['archive_sha256']);restored=out/'independent';result=restore_archive(archive,created['archive_sha256'],restored)
 require(all(file_hash(longpath(restored/'payload/executor'/name))==expected for name,expected in receipt['source_files'].items()),'Restored exact executor source mismatch');verify_notices(restored/'payload/notices')
 restored_native=restored/'payload/native';env=dict(os.environ);env['LOCALAPPDATA']=str(out/'creator-user-data')
 def run(command,name,timeout=150):
  (out/(name+'-command.json')).write_bytes(canonical(command))
  with (out/(name+'.log')).open('wb') as log:r=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
  require(r.returncode==0,name+' failed; log retained')
 run([str(GODOT),'--headless','--path',str(restored_native),'--editor','--import'],'restored-import')
 (restored_native/'XACEApproval.json').write_bytes(canonical(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(restored_native))))
 build=export(restored_native,out/'restored-native-build',GODOT);game=out/'restored-native-build/shipping';installation=inventory(game);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'player-user-data')
 run([str(game/'NativeGame.exe'),'--headless','--',str(out/'restored-player.json')],'restored-player')
 player=json.loads((out/'restored-player.json').read_bytes());require(player['ok'] and player['objects']==50 and player['exported'] and gone(player['runtime_pid']) and gone(player['owner_pid']),'Restored native gameplay/process cleanup failed')
 require(inventory(game)==installation and inventory(source/'project')==before,'Original/installed bytes changed')
 (out/'proof.json').write_bytes(canonical(dict(ok=True,archive=created,restoration=result,declared_private_engineering_closure_complete=True,public_redistribution_approved=False,original_unchanged=True,restored_native_rebuilt=True,restored_executor_sources_exact=len(receipt['source_files']),executor_compiler_rerun=False,executor_reproducibility_receipt_carried_forward=True,player=player,installation_unchanged=True,history_preserved=True,clean_machine=False,runtime_dependency_retained=True,runtime_free_export=False,full_nec017_complete=False)));print('Imported Godot archive/restore/rebuild/player passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))

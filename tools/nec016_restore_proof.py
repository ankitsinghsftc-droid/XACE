"""Fresh continuity archive and independent Godot/executor rebuild proof.
Private engineering fixture; redistribution licensing remains explicitly unverified.
"""
from pathlib import Path
import dataclasses,hashlib,json,os,shutil,subprocess,sys,tomllib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from continuity_contract import *
from continuity_archive import create_archive,restore_archive,file_hash
from tools.nec014_export import export,inventory as native_inventory
from tools.nec014_export_proof import GODOT
from tools.nec013_unity_player_proof import gone

def write(p,v):p.write_bytes(canonical(v))
def main(out):
 out=out.resolve();require(out.is_relative_to(ROOT/'evidence/nec016') and not out.exists(),'fresh durable evidence required');out.mkdir(parents=True)
 source=ROOT/'evidence/nec014/20261025/export-final-g';roots=out/'inputs';roots.mkdir()
 executor=roots/'executor';executor.mkdir()
 receipt=json.loads((source/'project/release/executor-receipt.json').read_bytes())
 for name,digest in receipt['source_files'].items():require(file_hash(ROOT/name)==digest,'pinned executor source mismatch: '+name)
 members=tomllib.loads((ROOT/'Cargo.toml').read_text())['workspace']['members']
 tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
 for name in tracked:
  if name in {'Cargo.toml','Cargo.lock'} or any(name.startswith(m+'/') for m in members):
   p=executor/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,p)
 write(executor/'original-executor-receipt.json',receipt)
 native=roots/'native';shutil.copytree(source/'project',native,ignore=shutil.ignore_patterns('.godot'))
 shutil.copyfile(source/'windows_release_x86_64.exe',native/'continuity-template.exe')
 # Relocation is a recorded reviewed edit of a NEW fixture, never historical source.
 old=(native/'export_presets.cfg').read_text();new=old.replace((source/'windows_release_x86_64.exe').as_posix(),'res://continuity-template.exe')
 require(old!=new,'expected template relocation absent');(native/'export_presets.cfg').write_text(new)
 write(native/'XACEApproval.json',dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=native_inventory(native)))
 project=roots/'project';project.mkdir();shutil.copyfile(source/'project/release/package/game.cgs.json',project/'game.cgs.json')
 history=roots/'history';shutil.copytree(source/'user-data/XACE',history)
 write(history/'protected-checkpoint.json',dict(schema='xace.continuity_proof_checkpoint.v1',source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),native_approval_sha256=file_hash(source/'project/XACEApproval.json'),executor_receipt_sha256=file_hash(source/'project/release/executor-receipt.json'),original_history=True))
 notices=roots/'notices';notices.mkdir();(notices/'PRIVATE-ENGINEERING.txt').write_text('Private engineering continuity proof only. Original executor receipt requires creator redistribution review. Godot and Rust dependency notices/licensing closure are NOT certified by this receipt. Installed Godot, Rust/MSVC and the exact Cargo.lock dependencies are external creator prerequisites. No public redistribution approval. No Builder needed to run the native artifact. Gameplay still requires the bundled XACE runtime.')
 omissions=tuple(Omission('history',p.relative_to(history).as_posix(),'Ephemeral authentication ticket; a new native session issues fresh credentials',False) for p in history.rglob('*') if p.name in {'ticket.json','native-ticket.json'})
 req=ArchiveRequest('nec016.private-engineering',(SourceRoot('project','project-source',project),SourceRoot('native','native-project',native),SourceRoot('executor','executor-source',executor),SourceRoot('runtime','runtime',source/'project/release'),SourceRoot('history','history',history),SourceRoot('notices','notices',notices)),(Dependency('public redistribution notices',None,True,'Creator redistribution review and complete third-party notices remain unavailable; private diagnostic restore only'),),(Checkpoint('payload/history/protected-checkpoint.json',file_hash(history/'protected-checkpoint.json')),),(Prerequisite('Godot','4.6.3 stable Windows x64','Install official console editor; bundled template is pinned in archive.'),Prerequisite('Rust/MSVC','installed creator toolchain; Cargo.lock pinned','Install Rust, VS2022 MSVC14.44 and Windows SDK; provision locked crates before offline build.')),omissions,True)
 archive=out/'continuity.zip';created=create_archive(req,archive,allow_incomplete=True);write(out/'archive-receipt.json',created)
 restored=out/'independent';restore_archive(archive,created['archive_sha256'],restored,allow_incomplete=True)
 ex=restored/'payload/executor';env=dict(os.environ);env.update(receipt['build']['environment']);env['RUSTFLAGS']=env['RUSTFLAGS'].replace(str(ROOT),str(ex))
 target=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo')/('nec016-'+out.name);require(not target.exists(),'fresh build output required')
 command=['cargo','build','--manifest-path',str(ex/'examples/reference-mechanic/Cargo.toml'),'--bin','xace_reference_host','--offline','--locked','--target-dir',str(target)]
 write(out/'build-command.json',dict(command=command,environment={k:env[k] for k in receipt['build']['environment']}))
 with (out/'executor-build.log').open('wb') as log:r=subprocess.run(command,cwd=ex,env=env,stdout=log,stderr=subprocess.STDOUT)
 require(r.returncode==0,'restored executor build failed; log retained')
 rebuilt=out/'rebuilt-executor.exe';shutil.copyfile(target/'debug/xace_reference_host.exe',rebuilt)
 require(file_hash(rebuilt)==receipt['executable_sha256'],'restored executor binary differs from pinned identity')
 native=restored/'payload/native';env['LOCALAPPDATA']=str(out/'creator-user-data')
 with (out/'godot-import.log').open('wb') as log:r=subprocess.run([str(GODOT),'--headless','--path',str(native),'--editor','--import'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
 require(r.returncode==0,'restored native import failed')
 built=export(native,out/'native-build',GODOT);game=out/'native-build/shipping';before=native_inventory(game)
 env['LOCALAPPDATA']=str(out/'player-user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 with (out/'player.log').open('wb') as log:r=subprocess.run([str(game/'NativeGame.exe'),'--headless','--',str(out/'player.json')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 require(r.returncode==0,'restored native player failed');player=json.loads((out/'player.json').read_bytes());require(player['ok'],'native gameplay proof failed')
 result=dict(ok=True,archive=created,declared_closure_complete=False,restored_executor_exact=True,executor_sha256=file_hash(rebuilt),native_rebuilt=True,history_preserved=True,player=player,install_unchanged=before==native_inventory(game),process_cleanup=gone(player['runtime_pid']) and gone(player['owner_pid']),clean_machine=False,network_denial=False,builder_absent_from_artifact=True,public_redistribution=False)
 require(result['install_unchanged'] and result['process_cleanup'],'native cleanup/integrity failed');write(out/'proof.json',result);print(json.dumps(result))
if __name__=='__main__':main(Path(sys.argv[1]))

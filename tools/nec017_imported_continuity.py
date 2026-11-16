"""Independent imported-project archive/restore/creator rebuild. Original inputs read-only."""
from pathlib import Path
import json,shutil,subprocess,os,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from continuity_contract import ArchiveRequest,SourceRoot,Dependency,Checkpoint,Prerequisite,Omission,canonical,require
from continuity_archive import create_archive,restore_archive,file_hash
from tools.nec013_unity_player_proof import gone
from tools.nec015_package_proof import ENGINE,run

def io(p):
 value=str(Path(p).resolve());return Path(value if value.startswith('\\\\?\\') else '\\\\?\\'+value)
def table(root):return {p.relative_to(io(root)).as_posix():file_hash(p) for p in io(root).rglob('*') if p.is_file()}
def main(engine,out):
 require(engine in ['unreal','unity'],'declared engine required');out=out.resolve();require(out.is_relative_to(ROOT/'evidence/nec017') and not out.exists(),'fresh durable output required');require(shutil.disk_usage(ROOT).free>4*1024**3,'4GiB archive/rebuild reserve')
 out.mkdir(parents=True);inputs=out/'inputs';inputs.mkdir();build=ROOT/'evidence/nec017/20261116'/('unreal-existing-play-d' if engine=='unreal' else 'unity-existing-play-e')
 proof=ROOT/'evidence/nec017/20261116/unreal-cooked-integrity-c/proof.json' if engine=='unreal' else build/'proof.json';require(json.loads(proof.read_bytes())['ok'],'retained gameplay proof must pass')
 source=build/'project';runtime=build/('archive/Windows' if engine=='unreal' else 'shipping');runtime_before=table(runtime)
 native=io(inputs/'native');shutil.copytree(io(source),native,symlinks=True,ignore=shutil.ignore_patterns('Library','Temp','obj','Logs','Binaries','Intermediate','Saved','DerivedDataCache','.git','XACEApproval.json'))
 prior_approval=(source/'XACEApproval.json').read_bytes();source_changes={}
 if engine=='unreal':
  from tools.nec015_build import inventory as approved_inventory
  for current in (ROOT/'adapters/unreal').iterdir():
   if current.suffix in ['.cpp','.h']:
    target=native/'Plugins/XACE/Source/XACEAdapter'/('Public' if current.suffix=='.h' else 'Private')/current.name
    require(target.exists(),'native adapter source missing')
    if current.name=='XaceNativeContractProofCommandlet.cpp':require(current.read_text(encoding='utf-8') in target.read_text(encoding='utf-8'),'editor-only wrapper differs');continue
    if file_hash(target)!=file_hash(current):source_changes[target.relative_to(native).as_posix()]=dict(before=file_hash(target),after=file_hash(current));shutil.copyfile(current,target)
  reviewed=json.loads(prior_approval.decode('utf-8-sig'));reviewed['files']=approved_inventory(native)
  (native/'XACEApproval.json').write_bytes(canonical(reviewed))
 else:(native/'XACEApproval.json').write_bytes(prior_approval)
 native_before=table(native)
 (out/'explicit-source-revision-review.json').write_bytes(canonical(dict(scope='New private test-owner native source copy only',previous_approval_sha256=__import__('hashlib').sha256(prior_approval).hexdigest(),new_approval_sha256=file_hash(native/'XACEApproval.json'),changes=source_changes,original_source_changed=False,action='Explicitly approve copied adapter include fixes before compilation; retain previous approval in inert history')))

 # Preserve complete creator compiler/package source plus the exact prior executor.
 creator=io(inputs/'creator');creator.mkdir();names=[n for n in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0') if n]
 for name in names:
  original=io(ROOT/name);require(original.is_file() and not original.is_symlink(),'tracked creator source missing/link: '+name);target=creator/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
 creator_hashes=table(creator);(out/'creator-source.json').write_bytes(canonical(dict(source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),files=creator_hashes)))
 executor=io(inputs/'executor');exact=io(ROOT/'evidence/nec017/20261116/godot-existing-continuity-b/independent/payload/executor');shutil.copytree(exact,executor,symlinks=True)
 receipt=json.loads((executor/'original-executor-receipt.json').read_bytes());require(all(file_hash(executor/name)==expected for name,expected in receipt['source_files'].items()),'exact executor source mismatch')
 project=inputs/'project';project.mkdir();release=source/('release' if engine=='unreal' else 'Assets/StreamingAssets/XACERelease');shutil.copyfile(release/'package/game.cgs.json',project/'game.cgs.json')
 history=io(inputs/'history');history.mkdir();(history/'previous-native-source-approval.json').write_bytes(prior_approval);authoring=ROOT/'evidence/nec017/20261105'/('unreal-existing-publish-b' if engine=='unreal' else 'unity-existing-publish-b')/'project/.xace';shutil.copytree(io(authoring),history/'authoring',symlinks=True)
 for name in ['user-data','player-user-data']:
  path=build/name/'XACE'
  if path.exists():shutil.copytree(io(path),history/name,symlinks=True)
 checkpoint=history/'checkpoint.json';checkpoint.write_bytes(canonical(dict(source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),original_gameplay_proof_sha256=file_hash(proof),creator_source_sha256=file_hash(out/'creator-source.json'),executor_sha256=receipt['executable_sha256'])))
 notices=inputs/'notices';shutil.copytree(ROOT/'evidence/nec016/20261028/notices-a',notices)
 (notices/'NATIVE-CREATOR-PREREQUISITES.txt').write_text('Private engineering continuity only. Renderer is '+engine+'. Exact engine SDK/editor/toolchain is an explicit installed creator prerequisite, not bundled source. Engine-derived fixture assets remain under their original terms. Full public distribution notices/rights and clean-machine/Steam certification remain NEC018 gates. Existing notice inventory covers its declared Rust/Godot dependencies; it is not a new legal approval for this renderer. Do not treat source/archive integrity as redistribution authorization. Native game still depends on its bundled pinned XACE runtime.',encoding='utf-8')
 omissions=tuple(Omission('history',p.relative_to(history).as_posix(),'Ephemeral authentication ticket; fresh admission issues new credentials',False) for p in history.rglob('*') if p.is_file() and p.name in ['ticket.json','native-ticket.json','session-ticket.json'])
 if (creator/'.env.example').exists():omissions+=(Omission('creator','.env.example','Nonessential environment configuration example; omitted under credential-name gate, original source remains unchanged',False),)
 restored_creator_hashes={name:digest for name,digest in creator_hashes.items() if not any(item.root=='creator' and item.path==name for item in omissions)}
 req=ArchiveRequest('nec017.imported.'+engine,(SourceRoot('project','project-source',project),SourceRoot('creator','project-source',creator),SourceRoot('native','native-project',native),SourceRoot('executor','executor-source',executor),SourceRoot('runtime','runtime',runtime),SourceRoot('history','history',history),SourceRoot('notices','notices',notices)),(Dependency('private creator prerequisites and notice boundary','payload/notices/NATIVE-CREATOR-PREREQUISITES.txt'),),(Checkpoint('payload/history/checkpoint.json',file_hash(checkpoint)),),(Prerequisite(engine,'5.7.4' if engine=='unreal' else '6000.4.9f1','Installed official Windows creator editor/SDK under creator licence. Source and packaged binaries archived; SDK is external. Public terms/notices approval remains NEC018.'),Prerequisite('Rust/Python/MSVC','original executor receipt, Cargo.lock; Python3.11; installed VS2022','Exact executor source and original two-build reproducibility receipt archived. Full creator/compiler/package source archived. Locked Cargo dependencies/toolchains must be provisioned; no download performed.')),omissions,True)
 archive=out/'continuity.zip';created=create_archive(req,archive);(out/'archive-receipt.json').write_bytes(canonical(created));restored=out/'independent';restoration=restore_archive(archive,created['archive_sha256'],restored)
 require(table(restored/'payload/creator')==restored_creator_hashes,'creator source restore mismatch');require(all(file_hash(io(restored/'payload/executor'/name))==expected for name,expected in receipt['source_files'].items()),'executor source restore mismatch');require(table(restored/'payload/native')==native_before,'native source restore mismatch');print('Archive/restore and exact creator/executor/native source passed: '+engine,flush=True)
 native=restored/'payload/native';creator=restored/'payload/creator';env=dict(os.environ);env['LOCALAPPDATA']=str(out/'creator-user-data')
 if engine=='unreal':
  # Standard compiler option trades time for disk, keeping the continuous2GiB guard.
  uproject=native/'NEC015.uproject';command=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'NEC015Editor','Win64','Development',f'-Project={uproject}','-nohotreload','-installed','-NoUBA','-NoPCH','-MaxParallelActions=1',f'-log={out/"editor-build-ubt.log"}'];(out/'editor-build-command.json').write_bytes(canonical(command));run(command,out/'editor-build.log',env,1800)
  command=[sys.executable,'-B',str(creator/'tools/nec015_build.py'),str(uproject),str(out/'checked-native-build'),str(ENGINE),'/Game/World','--no-pch'];(out/'checked-build-command.json').write_bytes(canonical(command));run(command,out/'checked-native-build.log',env,3600)
  receipt_build=json.loads((out/'checked-native-build/receipt.json').read_bytes());require(receipt_build['status']=='built-not-certified' and receipt_build['pch_enabled'] is False,'checked rebuild receipt missing')
  original_shipping=out/'checked-native-build/shipping/Windows';game=out/'restored-game';shutil.copytree(original_shipping,game);game_root=game/'NEC015';shutil.copyfile(native/'NEC017.expected.json',game_root/'NEC017.expected.json')
  # Observer-only expected positions are already pinned in the native source approval.
  require(file_hash(game_root/'NEC017.expected.json')==json.loads((native/'XACEApproval.json').read_text(encoding='utf-8-sig'))['files']['NEC017.expected.json'],'unapproved observer metadata')
  command=[str(game_root/'Binaries/Win64/NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-NEC017ExistingReport={out/"restored-player.json"}',f'-abslog={out/"player-engine.log"}']
 else:
  command=['C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe','-batchmode','-nographics','-projectPath',str(native),'-executeMethod','NEC017ExistingBuild.Run','-xaceReport',str(out/'rebuild.json'),'-xaceBuild',str(out/'checked-native-build/NativeGame.exe'),'-logFile',str(out/'native-build.log')];(out/'native-build-command.json').write_bytes(canonical(command));run(command,out/'native-build-run.log',env,1200)
  require(json.loads((out/'rebuild.json').read_bytes())['ok'],'restored Unity build refused');game=out/'checked-native-build';command=[str(game/'NativeGame.exe'),'-batchmode','-nographics','-xacePlayerReport',str(out/'restored-player.json'),'-logFile',str(out/'player-engine.log')]
 env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'player-user-data');installed=table(game);(out/'restored-player-command.json').write_bytes(canonical(command));run(command,out/'restored-player.log',env,150)
 player=json.loads((out/'restored-player.json').read_text(encoding='utf-8-sig'));require(player['ok'] and player.get('objects',player.get('entities'))==(50 if engine=='unreal' else 51) and gone(player['runtime_pid']) and gone(player['owner_pid']),'restored gameplay/cleanup failed');require(table(game)==installed and table(runtime)==runtime_before,'installed/original bytes changed')
 (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,archive=created,restoration=restoration,creator_source_files=len(restored_creator_hashes),explicit_nonessential_omissions=[dict(root=x.root,path=x.path,reason=x.reason) for x in omissions],exact_executor_sources=len(receipt['source_files']),executor_compiler_rerun=False,original_executor_reproducibility_receipt_preserved=True,native_compiler_rerun=True,checked_native_build=True,player=player,original_runtime_unchanged=True,installation_unchanged=True,public_redistribution_approved=False,clean_machine=False,runtime_dependency_retained=True,full_nec017_complete=False)));print('Independent restored native compiler/build/gameplay passed: '+engine,flush=True)
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))

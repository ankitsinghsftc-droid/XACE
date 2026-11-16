"""Collect exact-version notice texts for owner review; never grant distribution rights."""
from pathlib import Path
import json,shutil,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from release_handoff import tree,sha
from native_executor_contract import canonical
from tools.continuity_notices import verify_notices

URLS={
 'Unity-Player-Windows-Mono-6000.4.9f1.pdf':'https://storage.googleapis.com/live-platform-resources-prd/templates/assets/Player_Windows_Mono_6000_4_9f1_5adaf86ab4/Player_Windows_Mono_6000_4_9f1_5adaf86ab4.pdf',
 'Unity-Build-Support-Windows-Mono-6000.4.9f1.pdf':'https://storage.googleapis.com/live-platform-resources-prd/templates/assets/Build_Support_Windows_Mono_6000_4_9f1_021cd10a9a/Build_Support_Windows_Mono_6000_4_9f1_021cd10a9a.pdf'}

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True)
 old=ROOT/'evidence/nec016/20261028/notices-a';existing=verify_notices(old);assert existing['cargo_lock_sha256']==sha(ROOT/'Cargo.lock');shutil.copytree(old,out/'godot-rust-existing-notices')
 provenance=[]
 for name,url in URLS.items():
  with urllib.request.urlopen(url,timeout=60) as response:raw=response.read(8*1024*1024+1)
  assert raw.startswith(b'%PDF-') and len(raw)<=8*1024*1024;(out/name).write_bytes(raw);provenance.append(dict(path=name,url=url,sha256=sha(out/name),scope='Official exact 6000.4.9f1 Windows Mono '+('Player' if 'Player' in name else 'creator build support')+' notices; linked from https://unity.com/releases/editor/whats-new/6000.4.9f1'))
 editor=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Data');unity=out/'unity-installed-context';unity.mkdir();shutil.copyfile(editor/'Resources/legal.txt',unity/'installed-editor-legal.txt')
 project=ROOT/'evidence/nec017/20261116/unity-existing-workflow-b/play-again/project';shutil.copyfile(project/'Packages/manifest.json',unity/'project-packages.json');packages=json.loads((project/'Packages/manifest.json').read_bytes())['dependencies'];collected=[]
 for package in sorted(packages):
  folder=editor/'Resources/PackageManager/BuiltInPackages'/package
  if not folder.exists():continue
  for file in folder.iterdir():
   if file.is_file() and file.name.lower() in ['license.md','license.txt','third party notices.md','third-party notices.md']:
    dest=unity/package/file.name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(file,dest);collected.append(dest.relative_to(out).as_posix())
 ue=Path('C:/Program Files/Epic Games/UE_5.7/Engine');shutil.copytree(ue/'Source/ThirdParty/Licenses',out/'unreal-installed-third-party-licenses');shutil.copyfile(ue/'Build/Build.version',out/'unreal-Build.version');version=json.loads((out/'unreal-Build.version').read_bytes());assert (version['MajorVersion'],version['MinorVersion'],version['PatchVersion'])==(5,7,4)
 r=dict(schema='xace.nec018.notice_review.v1',exact_native_candidate_sha256='42a50cff1bf9c0a3e19cf8437ecbfb5a598025a36bd45cbb7a89a8fd1f7a0cc0',cargo_lock_sha256=sha(ROOT/'Cargo.lock'),godot_and_rust_preexisting_inventory_verified=True,unity_exact_player_mono_notices=True,unity_declared_builtin_dependencies=packages,unity_module_notice_files=collected,unreal_version=version,unreal_notice_scope='Conservative installed-engine notice superset; not a claimed per-binary dependency or legal-rights determination',web_sources=provenance,files=tree(out),rights_approval=False,first_party_continuing_use_terms_approved=False,final_signed_distribution_notice_closure=False,release_certified=False)
 (out/'review-manifest.json').write_bytes(canonical(r));print(json.dumps(dict(ok=True,files=len(r['files']),bytes=sum(x['bytes'] for x in r['files'].values()),unity_exact_version_player_notices=True,rights_approval=False),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))

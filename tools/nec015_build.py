"""Create-only approved Unreal Windows native build. A successful receipt is mandatory."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def require(condition,message):
 if not condition:raise ValueError(message)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def run(command,log,env,timeout):
 with log.open('xb') as stream:
  process=subprocess.Popen(command,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);end=time.monotonic()+timeout
  while process.poll() is None:
   if shutil.disk_usage(log.parent).free<2*1024**3 or time.monotonic()>end:
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    raise RuntimeError('Owned build stopped at disk/time reserve; staging retained')
   time.sleep(.25)
  require(process.returncode==0,'Native process failed; retained '+str(log))


SKIP={'Binaries','Intermediate','Saved','DerivedDataCache','XACEEvidence','.git'}
def inventory(project):
 result={}
 for p in sorted(project.rglob('*')):
  rel=p.relative_to(project)
  if not p.is_file() or any(x in SKIP for x in rel.parts) or rel.as_posix() in {'XACEApproval.json','XACEBuild.json','Build/Windows/FileOpenOrder/CookerOpenOrder.log','Build/Windows/FileOpenOrder/EditorOpenOrder.log'}:continue
  require(p.resolve().is_relative_to(project),'Source link escapes project')
  result[rel.as_posix()]=sha(p)
 return result

def validate(project):
 record=json.loads((project/'XACEApproval.json').read_text(encoding='utf-8-sig'))
 require(record['schema']=='xace.unreal.source_approval.v1' and record['files']==inventory(project),'Native source/resource approval stale')
 return record

def preflight(command,out,env,name,cooked):
 report=out/(name+'.json');require(not report.exists(),'Preflight report already exists')
 command=command+['-unattended','-nocef','-d3d11','-RenderOffscreen',f'-XaceNativePreflight={report}',f'-abslog={out/(name+"-engine.log")}']
 (out/(name+'-command.json')).write_text(json.dumps(command),encoding='utf-8')
 run(command,out/(name+'.log'),env,120)
 proof=json.loads(report.read_text(encoding='utf-8-sig'))
 require(proof.get('schema')=='xace.unreal.native_preflight.v1' and proof.get('ok') is True and proof.get('package_admitted') is True and proof.get('authority_started') is False and proof.get('cooked') is cooked,'Native preflight receipt refused')
 return proof

def build(uproject,out,engine,map_name,release_relative='release'):
 uproject=uproject.resolve();project=uproject.parent;out=out.resolve();engine=engine.resolve()
 require(uproject.is_file() and not out.exists() and not out.is_relative_to(project),'Fresh persistent output outside project required')
 require(map_name.startswith('/Game/') and '..' not in map_name,'Native map path required')
 approval=validate(project);relative=Path(release_relative)
 require(not relative.is_absolute() and '..' not in relative.parts,'Release must be project-relative')
 source=(project/relative).resolve();require(source.is_relative_to(project),'Release escapes project')
 require(shutil.disk_usage(project).free>6*1024**3,'Need 6 GiB for Game-only build with precompiled Editor; no cleanup')
 out.mkdir(parents=True);receipt=dict(schema='xace.unreal.native_build.v1',status='staging',source=str(uproject),approval_sha256=sha(project/'XACEApproval.json'),unreal=approval['unreal'],clean_machine=False)
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 def verify_approval():
  require(sha(project/'XACEApproval.json')==receipt['approval_sha256'] and validate(project)==approval,'Approval/source changed during build')
 try:
  preflight([str(engine/'Binaries/Win64/UnrealEditor-Cmd.exe'),str(uproject),map_name,'-game'],out,env,'source-preflight',False)
  verify_approval()
  command=[str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/AutomationTool/AutomationTool.dll'),'BuildCookRun',f'-project={uproject}','-nop4','-unattended','-utf8output','-platform=Win64','-clientconfig=Development','-build','-cook','-stage','-pak','-archive',f'-archivedirectory={out/"shipping"}',f'-map={map_name}','-nocompileeditor','-skipbuildeditor','-nodebuginfo','-UbtArgs=-NoUBA -MaxParallelActions=1']
  (out/'build-command.json').write_text(json.dumps(command),encoding='utf-8');run(command,out/'build.log',env,3600)
  verify_approval()
  windows=out/'shipping/Windows';game=windows/uproject.stem;require(game.is_dir(),'Cooked native game missing')
  shutil.copytree(source,game/relative)
  marker=windows/'Engine/Build/InstalledProjectBuild.txt';marker.parent.mkdir(parents=True,exist_ok=True)
  if not marker.exists():marker.write_text('XACE approved installed native game\n',encoding='utf-8')
  cooked=game/'XACEBuild.json';require(not cooked.exists(),'Cooked receipt already exists')
  cooked.write_text(json.dumps(dict(schema='xace.unreal.cooked_files.v1',unreal=approval['unreal'],files={p.relative_to(game).as_posix():sha(p) for p in sorted(game.rglob('*')) if p.is_file()}),indent=2),encoding='utf-8')
  preflight([str(game/'Binaries/Win64'/(uproject.stem+'.exe'))],out,env,'cooked-preflight',True)
  verify_approval();receipt.update(status='built-not-certified',files={p.relative_to(windows).as_posix():sha(p) for p in sorted(windows.rglob('*')) if p.is_file()})
 except Exception as error:receipt.update(status='failed',error=str(error));raise
 finally:(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
 return receipt
if __name__=='__main__':print(json.dumps(build(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4],sys.argv[5] if len(sys.argv)>5 else 'release')))

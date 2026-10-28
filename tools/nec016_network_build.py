from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import export,inventory
from tools.nec014_export_proof import GODOT

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec016')
 project=out/'project';shutil.copytree(ROOT/'evidence/nec016/20261028/restore-c/independent/payload/native',project,ignore=shutil.ignore_patterns('.godot'))
 p=project/'probe.gd';s=p.read_text();s=s.replace('var deadline := 0','var continuity_network := false\nvar continuity_tcp := StreamPeerTCP.new()\nvar deadline := 0')
 s=s.replace('func _ready() -> void: deadline=Time.get_ticks_msec()+30000','''func _ready() -> void:
    deadline=Time.get_ticks_msec()+30000
    continuity_network="--network-probe" in OS.get_cmdline_user_args()
    if continuity_network:
        deadline=Time.get_ticks_msec()+8000
        continuity_tcp.connect_to_host("1.1.1.1",443)''')
 s=s.replace('func _process(_delta: float) -> void:','''func _process(_delta: float) -> void:
    if continuity_network:
        continuity_tcp.poll()
        var connected := continuity_tcp.get_status()==StreamPeerTCP.STATUS_CONNECTED
        if connected or Time.get_ticks_msec()>deadline:
            FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE).store_string(JSON.stringify({"schema":"xace.nec016.network_probe.v1","connected":connected,"endpoint":"1.1.1.1:443","pid":OS.get_process_id()}))
            continuity_tcp.disconnect_from_host()
            get_tree().quit(0)
        return''')
 p.write_text(s)
 # Match original tab indentation; GDScript forbids mixing indentation styles.
 p.write_text(p.read_text().replace('    ','\t'))
 (project/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project))))
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'creator-data')
 with (out/'import.log').open('wb') as log:r=subprocess.run([str(GODOT),'--headless','--path',str(project),'--editor','--import'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0
 export(project,out/'build',GODOT)
 env['LOCALAPPDATA']=str(out/'before-data')
 with (out/'baseline.log').open('wb') as log:r=subprocess.run([str(out/'build/shipping/NativeGame.exe'),'--headless','--',str(out/'baseline.json'),'--network-probe'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
 proof=json.loads((out/'baseline.json').read_bytes());assert r.returncode==0 and proof['connected'],proof;print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]))

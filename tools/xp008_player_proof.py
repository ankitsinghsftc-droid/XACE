"""XP-008 live Player proof setup; gameplay fixture remains package-owned."""
from pathlib import Path
import json,sys,importlib
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from tools.xp007_package_proof import compile_plan
from tools.world_extensibility_proof import rehash
from tools.xp008_player_build import prepare_player
from playable_package import RuntimeSupport,build_package,install_archive,digest

def stage(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    cgs=json.loads((ROOT/"examples/reference-mechanic/fixtures/game.cgs.json").read_text())
    cgs["global_systems"]=[{"id":"EngineInputSystem","phase":"Input","reads":[],"writes":[6],"depends_on":[],"deterministic":True}]
    cgs["modes"][0]["systems"][0]["depends_on"]=["EngineInputSystem"]
    cgs["modes"][0]["world"]["contract"]=importlib.import_module("schema-factory.src.world_contract_v3").migrate_v2_source(cgs["modes"][0]["world"]["contract"])
    rehash(cgs)
    plan,compiled=compile_plan(cgs)
    runtime=(ROOT/"target/debug/xace_reference_host.exe").read_bytes()
    support=RuntimeSupport(digest(runtime),"xace.runtime_executor.v1",tuple(compiled.to_sgc_input()))
    settings={"schema":"xace.player.controls.v1","controller_id":1,"instructions":"Move: W A S D    Jump: Space","bindings":[{"action":"move_x","positive":68,"negative":65,"kind":"axis_1d"},{"action":"move_z","positive":87,"negative":83,"kind":"axis_1d"},{"action":"Jump","positive":32,"kind":"button"}]}
    archive=build_package(cgs,plan,runtime,support,package_id="reference.player",version="1.0.0",presentation_files={"presentation/player/settings.json":json.dumps(settings).encode()})
    (out/"reference.xace").write_bytes(archive)
    installed,manifest=install_archive(archive,out/"installed",support)
    prepare_player(installed,support,out/"player")
    return out/"player"

PROOF_SCRIPT = r'''extends "res://player.gd"
var failure_state: Dictionary = {}
func _send_input(tick: int) -> void:
    var scenario: String = str(options.get("--scenario","normal"))
    if scenario == "runtime_loss" and tick == 6:
        OS.kill(runtime_pid)
        return
    if scenario == "close" and tick == 6:
        report["closed_at_tick"] = tick
        _write_report()
        _notification(NOTIFICATION_WM_CLOSE_REQUEST)
        return
    focused = not (scenario == "focus" and tick in [2,3])
    for code in [65,68,87,83,32]:
        var event := InputEventKey.new()
        event.physical_keycode = code
        event.pressed = (code in [65,87] and tick < 12) or (code == 32 and tick in [1,3,7,9])
        Input.parse_input_event(event)
    Input.flush_buffered_events()
    super._send_input(tick)

func _fail(message: String) -> void:
    if entities != null and controlled > 0:
        failure_state = entities.component_snapshot(controlled)
    super._fail(message)
    await get_tree().create_timer(0.15).timeout
    report["frozen_after_failure"] = entities == null or controlled == 0 or failure_state == entities.component_snapshot(controlled)
    _write_report()
    get_tree().quit()
'''


def process_alive(pid):
    import ctypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return False
    code=ctypes.c_ulong()
    kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))
    kernel.CloseHandle(ctypes.c_void_p(handle))
    return code.value==259


def run(out,godot,template):
    import os,subprocess,shutil,tempfile
    from tools.xp008_player_build import export_player
    out=Path(out).resolve();player=stage(out);dist=out/"exported"
    stale=player/"proof_player.gd"
    if stale.exists():stale.unlink()
    export_player(player,dist/"xace-player.exe",godot,template)
    (player/"proof_player.gd").write_text(PROOF_SCRIPT,encoding="utf8")
    scene=player/"player.tscn";original=scene.read_text();scene.write_text(original.replace("res://player.gd","res://proof_player.gd"))
    try:export_player(player,dist/"xace-proof.exe",godot,template)
    finally:scene.write_text(original)
    env=dict(os.environ);env["PATH"]=str(Path(env.get("SystemRoot","C:/Windows"))/"System32")
    for key in ["PYTHONPATH","CARGO_HOME","RUSTUP_HOME"]:env.pop(key,None)
    outcomes={}
    for scenario,fps in [("normal",30),("normal",144),("focus",60),("runtime_loss",60),("close",60)]:
        name=f"{scenario}-{fps}";report=out/(name+".json");schedule=out/(name+"-schedule.json")
        command=[str(dist/"xace-proof.exe"),"--log-file",str(out/(name+".log")),"--","--package="+str(dist/"package"),"--proof-ticks=30","--fps="+str(fps),"--scenario="+scenario,"--report="+str(report),"--schedule="+str(schedule)]
        if name=="normal-30":command.append("--screenshot="+str(out/"player.png"))
        else:command.insert(1,"--headless")
        sentinel=subprocess.Popen([sys.executable,"-c","import time;time.sleep(40)"],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            proc=subprocess.run(command,cwd=dist,env=env,timeout=30)
            assert proc.returncode==0
            data=json.loads(report.read_text());assert not process_alive(data["owned_runtime_pid"])
            assert sentinel.poll() is None,"Player touched an unowned process"
        finally:sentinel.terminate();sentinel.wait(timeout=5)
        if scenario=="runtime_loss":
            assert data["errors"] and data["frozen_after_failure"] and len(data["ticks"])==6
        else:assert data["errors"]==[]
        if scenario=="normal":
            assert len(data["ticks"])==30
            states=[row["components"]["10000"]["data"] for row in data["ticks"]]
            assert any(row["mode"]=="wall_running" for row in states)
            assert max(row["chain"] for row in states)==2
            assert all(row["components"]["6"]["data"]["controller_id"]==1 for row in data["ticks"])
        if scenario=="focus":
            assert all(action["value"]==0 for row in data["inputs"] if row["tick"] in [2,3] for action in row["actions"])
        outcomes[name]={"exit_code":proc.returncode,"ticks":len(data["ticks"]),"errors":data["errors"],"owned_process_stopped":True,"unowned_process_retained":True}
    a=json.loads((out/"normal-30-schedule.json").read_text());b=json.loads((out/"normal-144-schedule.json").read_text())
    assert a["hash_log"]==b["hash_log"]
    assert json.loads((out/"normal-30.json").read_text())["inputs"]==json.loads((out/"normal-144.json").read_text())["inputs"]
    with tempfile.TemporaryDirectory(prefix="tamper-",dir=out) as tmp:
        damaged=Path(tmp)/"package";shutil.copytree(dist/"package",damaged)
        (damaged/"world.json").write_bytes(b"{}")
        report=out/"tamper.json"
        command=[str(dist/"xace-player.exe"),"--headless","--quit-after","30","--","--package="+str(damaged),"--report="+str(report)]
        subprocess.run(command,cwd=dist,env=env,timeout=15,check=True)
        data=json.loads(report.read_text());assert data["errors"] and "owned_runtime_pid" not in data
    direct_report=out/"direct-launch.json"
    subprocess.run([str(dist/"xace-player.exe"),"--headless","--","--proof-ticks=4","--report="+str(direct_report)],cwd=out,env=env,timeout=15,check=True)
    direct=json.loads(direct_report.read_text());assert direct["errors"]==[] and len(direct["ticks"])==4
    assert not process_alive(direct["owned_runtime_pid"])
    result={"schema":"xace.xp008.player_proof.v1","ok":True,"world_contract_version":3,"render_fps_hashes_equal":True,"recorded_inputs_equal":True,"tick_count":30,"hash_log":a["hash_log"],"scenarios":outcomes,"direct_launch_without_package_argument":True,"tampered_world_rejected_before_launch":True,"input_method":"Godot InputEventKey through Input.parse_input_event and the production physical-key collector; automated, not manual user play","scope":"exported Windows Player plus native host, same machine; no remote session or clean-machine certification"}
    (out/"proof.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    return result

if __name__=="__main__":
    import argparse
    from tools.godot_vertical_slice_certification import find_godot
    parser=argparse.ArgumentParser();parser.add_argument("--out",default=str(ROOT/"tmp/xp008-final"));parser.add_argument("--template",required=True);parser.add_argument("--godot",default="")
    args=parser.parse_args();result=run(args.out,find_godot(args.godot),args.template);print(json.dumps(result,indent=2))

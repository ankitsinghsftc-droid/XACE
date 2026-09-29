"""XP-007 real compiler, package relocation and native runtime proof."""
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from tools.world_extensibility_proof import semantic_fixture,rehash,factory
from tools.xp005_reference_proof import fixture
from playable_package import RuntimeSupport,build_package,verify_archive,install_archive,runtime_command,digest


def package_fixture():
    cgs=semantic_fixture()
    mode=cgs["modes"][0]
    for actor in mode["actors"]:
        actor["components"][0]["defaults"]["parent_entity_id"]=0
    velocity=next(c for c in fixture()["modes"][0]["actors"][2]["components"] if c["type_id"]==5)
    velocity=copy.deepcopy(velocity);velocity["defaults"]["linear"]["x"]=1000000
    mode["actors"][0]["components"].append(velocity)
    mode["systems"]=[{"id":"MovementSystem","phase":"Simulation","reads":[1,5],"writes":[1],"depends_on":[],"deterministic":True}]
    rehash(cgs)
    return cgs


def compile_plan(cgs):
    package=factory.compile_portable_cgs(cgs)
    exe=ROOT/"target/debug/xace-system-graph-compiler.exe"
    payload={"systems":package.to_sgc_input(),"schema_version":package.schema_version,"cgs_hash":package.cgs_hash,"plan_version":1}
    proc=subprocess.run([str(exe)],input=json.dumps(payload),capture_output=True,text=True,timeout=30)
    if proc.returncode:raise RuntimeError(proc.stderr)
    return proc.stdout.encode(),package


def run(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    cgs=package_fixture();plan,package=compile_plan(cgs)
    runtime=(ROOT/"target/debug/xace_runtime.exe").read_bytes()
    support=RuntimeSupport(digest(runtime),"xace.runtime_executor.v1",tuple(package.to_sgc_input()))
    first=build_package(cgs,plan,runtime,support,package_id="project.semantic_proof",version="1.0.0",presentation_files={"presentation/godot/bindings.json":b'{"schema":"xace.presentation.v1","variant":"plain"}'})
    second=build_package(cgs,plan,runtime,support,package_id="project.semantic_proof",version="1.0.0",presentation_files={"presentation/godot/bindings.json":b'{"schema":"xace.presentation.v1","variant":"plain"}'})
    assert first==second
    (out/"semantic-proof.xace").write_bytes(first)
    destination,manifest=install_archive(first,out/"installed",support)
    relocated=out/"relocated"/manifest["package_content_hash"]
    if not relocated.exists():shutil.copytree(destination,relocated)
    command=runtime_command(relocated,support,ticks=4)+["--schedule-snapshot-out",str(out/"schedule.json")]
    env=dict(os.environ)
    # The child gets no Python/repository/toolchain search path; it is the packaged native host.
    env["PATH"]=str(Path(env.get("SystemRoot","C:/Windows"))/"System32")
    env.pop("PYTHONPATH",None);env.pop("CARGO_HOME",None);env.pop("RUSTUP_HOME",None)
    baseline_command=runtime_command(destination,support,ticks=4)+["--schedule-snapshot-out",str(out/"baseline-schedule.json")]
    baseline=subprocess.run(baseline_command,cwd=destination,env=env,capture_output=True,text=True,timeout=30)
    (out/"baseline-runtime.log").write_text(baseline.stdout+baseline.stderr,encoding="utf8")
    if baseline.returncode:raise RuntimeError(baseline.stdout+baseline.stderr)
    proc=subprocess.run(command,cwd=relocated,env=env,capture_output=True,text=True,timeout=30)
    (out/"runtime.log").write_text(proc.stdout+proc.stderr,encoding="utf8")
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    snapshots=json.loads((out/"schedule.json").read_text(encoding="utf8"))
    baseline_snapshots=json.loads((out/"baseline-schedule.json").read_text(encoding="utf8"))
    assert snapshots["ok"] and snapshots["tick_count"]==4 and snapshots["mismatched_ticks"]==[]
    assert snapshots["hash_log"]==baseline_snapshots["hash_log"]
    assert len({entry["world_hash"] for entry in snapshots["hash_log"]})==4

    report={"schema":"xace.xp007.package_proof.v1","ok":True,"deterministic_archive_sha256":digest(first),
        "gameplay_hash":manifest["gameplay_hash"],"package_content_hash":manifest["package_content_hash"],"runtime_sha256":support.executable_sha256,
        "baseline_runtime_exit":baseline.returncode,"relocation_hashes_equal":True,"relocated_runtime_exit":proc.returncode,"runtime_log":str(out/"runtime.log"),"schedule":snapshots,
        "scope":"native headless package; no Player/native engine/provider/remote-session claim"}
    (out/"proof.json").write_text(json.dumps(report,indent=2),encoding="utf8")
    return report

if __name__=="__main__":
    result=run(sys.argv[1] if len(sys.argv)>1 else ROOT/"tmp/xp007-proof")
    print(json.dumps({k:v for k,v in result.items() if k!="schedule"},indent=2))

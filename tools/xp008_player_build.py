"""Prepare a Player distribution using XP-007 verified package admission.

The trusted installer/build step emits a receipt outside package-controlled data.
Player verifies that receipt and every package byte before launching its sidecar.
Adding another game runs this data operation, without changing core/Player code.
"""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from playable_package import verify_files,read_installed,digest
from player_presentation import validate_presentation

def prepare_player(package_root,support,out):
    files=read_installed(package_root)
    manifest=verify_files(files,support)
    presentation=validate_presentation(files,manifest)
    settings=json.loads(files.get("presentation/player/settings.json",b"{}"))
    if not isinstance(settings,dict):raise ValueError("Player settings must be an object")
    bindings=settings.get("bindings",[])
    if settings.get("schema") != "xace.player.controls.v1" or not isinstance(bindings,list) or not 0<len(bindings)<=64:
        raise ValueError("Player requires versioned keyboard bindings")
    if type(settings.get("controller_id")) is not int or settings["controller_id"]<=0:
        raise ValueError("Player requires a positive controller identity")
    names=set()
    for binding in bindings:
        if not isinstance(binding,dict):raise ValueError("Keyboard binding must be an object")
        name=binding.get("action")
        if not isinstance(name,str) or not 0<len(name.encode())<=64 or name in names:
            raise ValueError("Invalid or duplicate wire action")
        names.add(name)
        if binding.get("kind") not in {"axis_1d","button"}:
            raise ValueError("Unsupported keyboard binding kind")
        for key in ("positive","negative"):
            value=binding.get(key,0)
            if type(value) is not int or not 0<=value<2**32:
                raise ValueError("Invalid physical key")
    out=Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/"apps/xace-player").iterdir():
        if source.is_file() and source.suffix in {".gd",".tscn",".godot"}:
            shutil.copy2(source,out/source.name)
    (out/"adapter").mkdir(exist_ok=True)
    for name in ("xace_adapter.gd","xace_entity_manager.gd","xace_transport.gd","xace_protocol.gd","xace_canonical_entities.gd","xace_native_contract.gd"):
        source=ROOT/"adapters/godot"/name
        shutil.copy2(source,out/"adapter"/name)
    for name,payload in files.items():
        path=out/"package"/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(payload)
    receipt={"schema":"xace.player.admission.v1","manifest_sha256":digest(files["playable.manifest.json"]),"runtime_sha256":support.executable_sha256,"gameplay_hash":manifest["gameplay_hash"],"presentation":presentation}
    (out/"admission.json").write_text(json.dumps(receipt,indent=2),encoding="utf8")
    return receipt


def export_player(project,destination,godot,template):
    """Export a real Windows release application using a caller-provided template."""
    import subprocess
    project=Path(project).resolve();destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    template=Path(template).resolve()
    if not template.is_file():raise FileNotFoundError(template)
    preset = '[preset.0]\nname="Windows Desktop"\nplatform="Windows Desktop"\nrunnable=true\nexport_filter="all_resources"\ninclude_filter="admission.json"\nexclude_filter="package/*"\nexport_path=""\nscript_export_mode=1\n[preset.0.options]\n'
    preset += 'custom_template/debug="'+template.as_posix()+'"\ncustom_template/release="'+template.as_posix()+'"\nbinary_format/architecture="x86_64"\nbinary_format/embed_pck=false\napplication/modify_resources=false\n'
    (project/"export_presets.cfg").write_text(preset,encoding="utf8")
    command=[str(godot),"--headless","--path",str(project),"--export-release","Windows Desktop",str(destination)]
    proc=subprocess.run(command,capture_output=True,text=True,timeout=90)
    destination.with_suffix(".export.log").write_text(proc.stdout+proc.stderr,encoding="utf8")
    if proc.returncode or "SCRIPT ERROR" in proc.stdout+proc.stderr:raise RuntimeError(proc.stdout+proc.stderr)
    shutil.copytree(project/"package",destination.parent/"package",dirs_exist_ok=True)
    return command

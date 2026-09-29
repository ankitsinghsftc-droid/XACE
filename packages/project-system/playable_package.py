"""XP-007 immutable playable packages. Import/verification never executes payloads.

Construction and installation reuse Factory and persisted SGC validation. Runtime
support is supplied by the trusted host, never inferred from package assertions.
"""
from __future__ import annotations
import copy
import dataclasses
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT/"packages", ROOT/"packages/builder-workspace/server", Path(__file__).resolve().parent):
    if str(path) not in sys.path: sys.path.insert(0,str(path))
from adapter_package_versioning import _sha256_json
from sgc_plan_validator import validate_sgc_plan_for_runtime_load
from sgc_identity import verify_sgc_identity

SCHEMA = "xace.playable_package.v1"
MANIFEST = "playable.manifest.json"
MAX_FILES = 4096
MAX_FILE_BYTES = 128*1024*1024
MAX_TOTAL_BYTES = 512*1024*1024
CORE_FILES = {"game.cgs.json", "compiled_schema.json", "execution_plan.json", "world.json", "world.manifest.json", "runtime/xace_runtime.exe"}

class PackageError(ValueError): pass

def require(ok, message):
    if not ok: raise PackageError(message)

def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("utf8")

def digest(data): return hashlib.sha256(data).hexdigest()

def safe_path(value):
    require(isinstance(value,str) and value and len(value)<=240 and "\\" not in value and ":" not in value, "invalid package path")
    path=PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix()==value and all(p not in {".",".."} for p in path.parts), "unsafe package path")
    for part in path.parts:
        require(re.fullmatch(r"[A-Za-z0-9_.-]+",part) is not None and not part.endswith(("."," ")), "nonportable package path")
        require(part.split(".")[0].upper() not in {"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}, "reserved device path")
    return value

def parse(data):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,"duplicate JSON key")
            result[key]=value
        return result
    try:return json.loads(data,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(PackageError("nonfinite JSON")))
    except (ValueError,UnicodeError) as exc:raise PackageError(str(exc)) from exc

@dataclasses.dataclass(frozen=True)
class RuntimeSupport:
    executable_sha256: str
    abi: str
    system_contracts: tuple[dict,...]
    geometry_profiles: tuple[str,...] = ("world.aabb.v1",)
    world_versions: tuple[int,...] = (2,3)

    def validate(self):
        require(re.fullmatch(r"[0-9a-f]{64}",self.executable_sha256) is not None,"invalid trusted runtime digest")
        require(self.abi=="xace.runtime_executor.v1","unsupported runtime ABI")
        require(len({s["id"] for s in self.system_contracts})==len(self.system_contracts),"duplicate host system contract")


def compiled_artifacts(cgs):
    factory=importlib.import_module("schema-factory.src.portable_compilation")
    package=factory.compile_portable_cgs(cgs)
    require(package.world_contract is not None,"playable package requires explicit compiled world")
    projection={"schema":"xace.compiled_schema_projection.v1", "cgs_hash":package.cgs_hash,"schema_version":package.schema_version,
        "blueprints":[dataclasses.asdict(b) for b in sorted(package.blueprint_registry.all_blueprints(),key=lambda b:b.id)],
        "components":[dataclasses.asdict(c) for c in sorted(package.component_registry.all_definitions(),key=lambda c:c.type_id)],
        "systems":package.to_sgc_input()}
    return package, {"game.cgs.json":encode(cgs),"compiled_schema.json":encode(projection),
        "world.json":package.world_contract.content_bytes,"world.manifest.json":package.world_contract.manifest_bytes}


def check_support(package,support):
    support.validate()
    world=package.world_contract.content()
    require(world["contract_version"] in support.world_versions,"unsupported world version")
    profiles=([p["id"] for p in world["geometry_profiles"] if p["required"]] if world["contract_version"]==3 else ["world.aabb.v1"])
    require(set(profiles)<=set(support.geometry_profiles),"unsupported required geometry profile")
    supported={s["id"]:s for s in support.system_contracts}
    for system in package.to_sgc_input():
        require(supported.get(system["id"])==system,"unsupported runtime executor contract: "+system["id"])
    return sorted(profiles)


def presentation_index(files):
    variants={}
    for path,data in sorted(files.items()):
        if path.startswith("presentation/"):
            parts=PurePosixPath(path).parts
            require(len(parts)>=3,"presentation files require a variant namespace")
            variants.setdefault(parts[1],[]).append({"path":path,"sha256":digest(data),"size":len(data)})
    return {key:{"schema":"xace.presentation_variant.v1","files":records,"content_hash":_sha256_json({"files":records})} for key,records in sorted(variants.items())}


def build_package(cgs, plan_bytes, runtime_bytes, support, *, package_id, version, presentation_files=None):
    """Return deterministic ZIP bytes; never launches runtime or payload scripts."""
    require(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",package_id) is not None,"invalid package ID")
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",version) is not None,"invalid package version")
    package,files=compiled_artifacts(copy.deepcopy(cgs))
    profiles=check_support(package,support)
    plan=parse(plan_bytes)
    validate_sgc_plan_for_runtime_load(cgs,encode(plan).decode())
    verify_sgc_identity(plan,package.to_sgc_input())
    require(digest(runtime_bytes)==support.executable_sha256,"runtime differs from trusted host build")
    files.update({"execution_plan.json":encode(plan),"runtime/xace_runtime.exe":runtime_bytes})
    for path,data in (presentation_files or {}).items():
        safe_path(path)
        require(path.startswith("presentation/") and isinstance(data,bytes),"presentation files need a separate portable namespace")
        files[path]=data
    gameplay={"cgs_hash":package.cgs_hash,"schema_version":package.schema_version,
        "compiled_schema_hash":digest(files["compiled_schema.json"]),"plan_hash":plan["plan_hash"],
        "world":package.world_contract.manifest()["world"],"required_geometry_profiles":profiles,
        "runtime_abi":support.abi,"runtime_sha256":support.executable_sha256,
        "executors":package.to_sgc_input(),"input_schema":"xace.input_packet.v1","event_schema":"xace.domain_event.v1","simulation_profile":"fixed64_60hz.v1","platform":"windows_x64"}
    manifest={"schema":SCHEMA,"package_id":package_id,"version":version,"gameplay":gameplay,
        "gameplay_hash":_sha256_json(gameplay),"presentation_variants":presentation_index(files),"files":[{"path":p,"size":len(b),"sha256":digest(b)} for p,b in sorted(files.items())]}
    manifest["package_content_hash"]=_sha256_json(manifest)
    files[MANIFEST]=encode(manifest)
    verify_files(files,support)
    return archive_files(files)


def archive_files(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_STORED) as archive:
        for path,data in sorted(files.items()):
            info=zipfile.ZipInfo(path,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_STORED
            info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
            archive.writestr(info,data)
    return out.getvalue()


def read_archive(data):
    require(len(data)<=MAX_TOTAL_BYTES+MAX_FILES*1024,"archive limit exceeded")
    files={};folded=set();total=0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            require(len(archive.infolist())<=MAX_FILES,"too many archive entries")
            for info in archive.infolist():
                name=safe_path(info.orig_filename)
                require(name==info.filename,"archive path normalization is forbidden")
                require(name.casefold() not in folded,"duplicate/case-colliding archive path")
                folded.add(name.casefold())
                require(not info.is_dir() and stat.S_IFMT(info.external_attr>>16) in {0,stat.S_IFREG},"archive links/special files are forbidden")
                require(not info.flag_bits&1 and info.compress_type in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED},"unsupported archive encoding")
                require(0<=info.file_size<=MAX_FILE_BYTES,"archive file limit exceeded")
                total+=info.file_size;require(total<=MAX_TOTAL_BYTES,"expanded archive limit exceeded")
                with archive.open(info) as stream:payload=stream.read(info.file_size+1)
                require(len(payload)==info.file_size,"archive size mismatch")
                files[name]=payload
    except (zipfile.BadZipFile,RuntimeError,OSError) as exc:raise PackageError(str(exc)) from exc
    return files


def verify_files(files,support):
    require(isinstance(files,dict) and len(files)<=MAX_FILES and CORE_FILES|{MANIFEST}<=files.keys(),"missing required package artifact")
    require(sum(len(b) for b in files.values())<=MAX_TOTAL_BYTES,"package size limit")
    for path,data in files.items():safe_path(path);require(len(data)<=MAX_FILE_BYTES,"package file limit")
    require(len({p.casefold() for p in files})==len(files),"case-colliding package path")
    folded={p.casefold() for p in files}
    for name in files:
        require(all(parent.as_posix().casefold() not in folded for parent in PurePosixPath(name).parents),"file/directory path collision")
    manifest=parse(files[MANIFEST]);require(isinstance(manifest,dict),"invalid manifest")
    require(set(manifest)=={"schema","package_id","version","gameplay","gameplay_hash","presentation_variants","files","package_content_hash"} and manifest["schema"]==SCHEMA,"unsupported manifest")
    require(isinstance(manifest["package_id"], str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",manifest["package_id"]) is not None,"invalid package ID")
    require(isinstance(manifest["version"],str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+",manifest["version"]) is not None,"invalid package version")
    require(manifest["presentation_variants"]==presentation_index(files),"presentation variant index mismatch")
    expected=copy.deepcopy(manifest);claimed=expected.pop("package_content_hash")
    require(claimed==_sha256_json(expected),"package identity mismatch")
    records=manifest["files"]
    require(isinstance(records,list) and all(isinstance(r,dict) and set(r)=={"path","size","sha256"} for r in records),"invalid file table")
    require([r["path"] for r in records]==sorted(files.keys()-{MANIFEST}),"file table differs from archive")
    for record in records:
        data=files[record["path"]]
        require(type(record["size"]) is int and record["size"]==len(data) and record["sha256"]==digest(data),"artifact checksum mismatch: "+record["path"])
    cgs=parse(files["game.cgs.json"])
    # Native file resolution belongs to packaged presentation resources, never
    # an absolute creator-machine path or a repository-relative dependency.
    for asset in cgs.get("assets", []):
        for key in ("source", "path", "file_path", "resolved_path"):
            value=asset.get(key)
            if value:
                safe_path(value)
                require(value.startswith("presentation/") and value in files,"asset location must reference a packaged presentation resource")

    package,expected_files=compiled_artifacts(cgs)
    for name,data in expected_files.items():require(files[name]==data,"artifact differs from authoritative Factory projection: "+name)
    profiles=check_support(package,support)
    plan=parse(files["execution_plan.json"]);validate_sgc_plan_for_runtime_load(cgs,files["execution_plan.json"].decode())
    verify_sgc_identity(plan,package.to_sgc_input())
    expected_gameplay={"cgs_hash":package.cgs_hash,"schema_version":package.schema_version,"compiled_schema_hash":digest(files["compiled_schema.json"]),
        "plan_hash":plan["plan_hash"],"world":package.world_contract.manifest()["world"],"required_geometry_profiles":profiles,
        "runtime_abi":support.abi,"runtime_sha256":support.executable_sha256,"executors":package.to_sgc_input(),
        "input_schema":"xace.input_packet.v1","event_schema":"xace.domain_event.v1","simulation_profile":"fixed64_60hz.v1","platform":"windows_x64"}
    require(manifest["gameplay"]==expected_gameplay and manifest["gameplay_hash"]==_sha256_json(expected_gameplay),"gameplay compatibility mismatch")
    require(digest(files["runtime/xace_runtime.exe"])==support.executable_sha256,"untrusted runtime executable")
    require(all(p in CORE_FILES|{MANIFEST} or p.startswith("presentation/") for p in files),"unknown authoritative package file")
    return copy.deepcopy(manifest)


def verify_archive(data,support): return verify_files(read_archive(data),support)


def read_installed(root):
    original=Path(root)
    attrs=original.lstat()
    require(not original.is_symlink() and not getattr(attrs,"st_file_attributes",0)&getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0),"installed root is a link")
    root=original.resolve(strict=True);files={}
    for path in sorted(root.rglob("*")):
        attrs=path.lstat()
        require(not path.is_symlink() and not getattr(attrs,"st_file_attributes",0)&getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0),"installed package contains a link")
        if path.is_file():
            require(attrs.st_size<=MAX_FILE_BYTES,"installed file limit")
            name=safe_path(path.relative_to(root).as_posix());files[name]=path.read_bytes()
            require(len(files)<=MAX_FILES and sum(map(len,files.values()))<=MAX_TOTAL_BYTES,"installed package limit")
    return files


def install_archive(data,install_root,support):
    """Content-addressed install; only the final pointer replacement activates it.

    Incomplete staging never changes the previous active package. Existing releases
    are verified and retained; no caller-owned directory is recursively removed.
    """
    files=read_archive(data);manifest=verify_files(files,support)
    root=Path(install_root).resolve();root.mkdir(parents=True,exist_ok=True)
    versions=root/"versions";versions.mkdir(exist_ok=True)
    require(versions.resolve().parent==root and not versions.is_symlink(),"unsafe versions directory")
    destination=versions/manifest["package_content_hash"]
    if destination.exists():verify_files(read_installed(destination),support)
    else:
        with tempfile.TemporaryDirectory(prefix="staging-",dir=versions) as tmp:
            stage=Path(tmp).resolve();require(stage.parent==versions.resolve(),"unsafe staging directory")
            for name,payload in files.items():
                target=stage/name;require(target.resolve().is_relative_to(stage),"extraction escaped staging")
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
            verify_files(read_installed(stage),support)
            stage.rename(destination)
    pointer=encode({"schema":"xace.playable_activation.v1","package_content_hash":manifest["package_content_hash"]})
    handle,temp=tempfile.mkstemp(prefix="active-",suffix=".tmp",dir=root)
    try:
        with os.fdopen(handle,"wb") as stream:stream.write(pointer);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,root/"active.json")
    finally:
        if Path(temp).exists():Path(temp).unlink()
    return destination,manifest


def runtime_command(installed_root,support,*,ticks=0):
    verify_files(read_installed(installed_root),support)
    root=Path(installed_root).resolve()
    require(type(ticks) is int and ticks>=0,"invalid tick limit")
    return [str(root/"runtime/xace_runtime.exe"),"--cgs",str(root/"game.cgs.json"),"--sgc-plan",str(root/"execution_plan.json"),
        "--world",str(root/"world.json"),"--world-manifest",str(root/"world.manifest.json"),"--ticks",str(ticks),"--tick-rate","60","--no-wait","--no-control"]

"""Two independent creator builds; retain binaries/evidence outside build output."""
import hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def source_inventory():
    files={}
    for folder in ['packages/core','packages/runtime-core','packages/engine-feedback','packages/network-core','examples/reference-mechanic']:
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and (path.suffix=='.rs' or path.name in {'Cargo.toml','Cargo.lock'}):
                files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name,path in [('Cargo.lock',ROOT/'Cargo.lock'),('Cargo.toml',ROOT/'Cargo.toml')]:
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return files

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    out.mkdir(parents=True)
    env=dict(os.environ);env.update(CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_DEV_INCREMENTAL='false',RUSTFLAGS='-C link-arg=/Brepro -C link-arg=/PDBALTPATH:xace_reference_host.pdb --remap-path-prefix='+str(ROOT)+'=/xace')
    linker=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/link.exe')
    assert linker.is_file()
    env['CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER']=str(linker)
    sources=source_inventory()
    (out/'source-files.json').write_text(json.dumps(sources,sort_keys=True,indent=2))
    rows=[]
    for name in ['first','second']:
        target=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo')/('nec011-reference-'+out.name+'-'+name)
        assert not target.exists()
        cmd=['cargo','build','--manifest-path',str(ROOT/'examples/reference-mechanic/Cargo.toml'),'--bin','xace_reference_host','--offline','--locked','--target-dir',str(target)]
        (out/(name+'-command.json')).write_text(json.dumps(dict(command=cmd,environment={k:env[k] for k in ['CARGO_PROFILE_DEV_DEBUG','CARGO_PROFILE_DEV_INCREMENTAL','RUSTFLAGS','CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER']}),indent=2))
        with (out/(name+'.txt')).open('wb') as log:r=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:raise RuntimeError(name+' creator build failed; inspect retained log')
        assert source_inventory()==sources,'Build inputs changed during compilation'
        binary=out/(name+'-host.exe');shutil.copyfile(target/'debug/xace_reference_host.exe',binary)
        rows.append(dict(build_id=name,executable_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),path=str(binary)));print(json.dumps(rows[-1]),flush=True)
    same=rows[0]['executable_sha256']==rows[1]['executable_sha256']
    (out/'builds.json').write_text(json.dumps(dict(ok=same,builds=rows),indent=2))
    assert same,'Independent builds differ; retain evidence and diagnose'
if __name__=='__main__':main(Path(sys.argv[1]).resolve())

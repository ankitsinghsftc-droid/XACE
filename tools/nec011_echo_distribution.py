"""Admit, package, relocate and execute the creator-built echo host without compilation."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
import native_executor_contract as contract
import playable_package as package_api

def main(out,build):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    out.mkdir(parents=True)
    reports=json.loads((build/'builds.json').read_text());assert reports['ok']
    recipe=json.loads((build/'first-command.json').read_text())
    exe=Path(reports['builds'][0]['path']);raw=exe.read_bytes();exehash=hashlib.sha256(raw).hexdigest()
    rustroot=Path(subprocess.check_output(['rustc','--print','sysroot'],text=True).strip())
    linker=Path(recipe['environment']['CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER'])
    from tools.nec011_echo_build import source_inventory
    files=json.loads((build/'source-files.json').read_text())
    assert files==source_inventory(),'Source differs from retained build inputs; rebuild before admission'
    fixtures=ROOT/'examples/nec011-echo/fixtures';cgs=json.loads((fixtures/'game.cgs.json').read_text());package,_=package_api.compiled_artifacts(cgs)
    compatibility=dict(runtime_abi='xace.runtime_executor.v1',numeric_profile='fixed64_y_up_neg_z_v1',simulation_profile='fixed64_60hz.v1',world_versions=[2,3],geometry_profiles=['world.aabb.v1'],snapshot_schema='xace.world_snapshot.v1',replay_schema='xace.epoch_replay.v1',input_schema='xace.input_packet.v1',event_schema='xace.domain_event.v1',platform='windows_x64')
    receipt=dict(schema=contract.SCHEMA,executor_id='nec011.echo_host.v1',source_files=files,toolchain=dict(rustc_verbose=subprocess.check_output(['rustc','-vV'],text=True),rustc_sha256=hashlib.sha256((rustroot/'bin/rustc.exe').read_bytes()).hexdigest(),linker_sha256=hashlib.sha256(linker.read_bytes()).hexdigest(),target='x86_64-pc-windows-msvc'),build=dict(command=recipe['command'],environment=recipe['environment'],source_digest=contract.digest(files),independent_outputs=[{k:r[k] for k in ['build_id','executable_sha256']} for r in reports['builds']]),executable_sha256=exehash,systems=package.to_sgc_input(),capabilities=['nec011.echo_graph.v1'],compatibility=compatibility,state_policy='all_gameplay_state_in_snapshot_no_hidden_mutable_state',shipping=dict(player_compilation=False,required_files={'runtime/xace_runtime.exe':exehash},notices=['Creator redistribution review required; private engineering proof only']))
    (out/'executor-receipt.json').write_text(json.dumps(receipt,indent=2))
    support=contract.admit(receipt,expected_receipt_digest=contract.digest(receipt),executable=exe,required_capabilities=['nec011.echo_graph.v1'],expected_compatibility=compatibility,package=package)
    archive=package_api.build_package(cgs,(fixtures/'execution_plan.json').read_bytes(),raw,support,package_id='nec011.echo',version='0.1.0');(out/'echo.xacepkg').write_bytes(archive)
    manifest=package_api.verify_archive(archive,support)
    # Fresh retained copy only; no installer cleanup or modification of existing data.
    installed=out/'relocated-game';installed.mkdir()
    for name,data in package_api.read_archive(archive).items():
        p=installed/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    commands=[]
    for name in ['first','second']:
        command=package_api.runtime_command(installed,support,ticks=8)+['--port','0','--print-every','1','--schedule-snapshot-out',str(out/(name+'-schedule.json'))]
        with (out/(name+'-run.txt')).open('wb') as log:r=subprocess.run(command,cwd=installed,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=45)
        commands.append(dict(command=command,returncode=r.returncode));assert r.returncode==0,'Relocated host failed; inspect retained log'
    from nec011_echo_session_proof import prove
    prove(installed/'runtime/xace_runtime.exe',installed/'game.cgs.json',installed/'execution_plan.json',out/'interactive-session')
    (out/'commands.json').write_text(json.dumps(commands,indent=2))
    (out/'proof.json').write_text(json.dumps(dict(ok=True,trusted_receipt_digest=contract.digest(receipt),executable_sha256=exehash,package_content_hash=manifest['package_content_hash'],relocated_executable=True,player_compilation=False,native_engine_shipping=False,clean_machine=False),indent=2))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())

"""Real Chromium explicit review/apply proof; filesystem fixture, not a native editor."""
import argparse,json,socket,subprocess,sys,threading,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'packages/builder-workspace/server'),str(ROOT/'packages/project-system/tests')]
from fastapi import FastAPI
from fastapi.responses import HTMLResponse,Response
import uvicorn
from native_reconciliation_routes import install_reconciliation_routes
from test_native_reconciliation import context,engine_edit,xace_edit,refresh,canonical

TEST=r'''
import '/native-review.js';
const get=id=>document.getElementById(id);
const check=(ok,message)=>{if(!ok)throw new Error(message);};
async function wait(test){for(let i=0;i<2000;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw new Error('UI timed out: '+get('status').textContent);}
try {
 get('refresh').click();await wait(()=>!get('approve').disabled);
 check(!get('apply').hidden&&get('apply').disabled,'Apply must require separate approval');
 get('approve').click();await wait(()=>!get('apply').disabled);
 const before=await (await fetch('/__proof/state')).json();
 check(!before.baseline&&before.cgs_unchanged,'Approval wrote project files');
 check(get('proposal').textContent.includes('"can_commit": false'),'Review approval claims publication');
 get('apply').click();await wait(()=>get('status').textContent.includes('saved and verified'));
 const after=await (await fetch('/__proof/state')).json();
 check(after.baseline&&!after.cgs_unchanged,'Apply did not publish verified pair');
 check(!after.blocked,'Completed save left recovery gate blocked');
 check(get('apply').disabled,'Apply remained reusable');
 check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
 document.body.dataset.testState='passed';document.body.dataset.checks='7';
} catch(error) {document.body.dataset.testState='failed';get('status').textContent=String(error.stack||error);}
'''


RECOVERY_TEST=r'''
import '/native-review.js';
const get=id=>document.getElementById(id);
async function wait(test){for(let i=0;i<2000;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw new Error('UI timed out: '+get('status').textContent);}
try {
 get('refresh').click();await wait(()=>!get('recovery').hidden);
 if(!get('approve').disabled||!get('apply').disabled)throw new Error('Pending recovery allowed approval');
 const button=[...get('recovery').querySelectorAll('button')].find(b=>b.textContent==='Finish approved save');
 if(!button)throw new Error('Explicit resume unavailable');button.click();
 await wait(()=>get('status').textContent.includes('Saved changes verified'));
 const state=await (await fetch('/__proof/state')).json();
 if(!state.baseline||state.blocked)throw new Error('Recovery did not verify and unblock');
 if(!get('recovery').hidden)throw new Error('Completed recovery remains selected');
 if(document.documentElement.scrollWidth>innerWidth)throw new Error('Horizontal overflow');
 document.body.dataset.testState='passed';document.body.dataset.checks='5';
} catch(error) {document.body.dataset.testState='failed';get('status').textContent=String(error.stack||error);}
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--width',type=int,default=1280);p.add_argument('--recovery',action='store_true');args=p.parse_args();out=args.out.resolve()
    assert out.is_relative_to(ROOT/'evidence/nec010/20261017') and not out.exists();out.mkdir(parents=True)
    browser=next((p for p in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')] if p.exists()),None);assert browser
    from test_native_materialization_host import HostTests
    project=out/'project';project.mkdir()
    host,ctx=HostTests().fixture(project)
    before=(project/'game.cgs.json').read_bytes()
    if args.recovery:
        from unittest.mock import patch
        from native_materialization import NativeMaterializationHost
        approval=HostTests().approve(host);commit=host.gateway.commit
        def interrupted(prepared):
            commit(prepared)
            raise RuntimeError('lost acknowledgement')
        with patch.object(host.gateway,'commit',side_effect=interrupted):
            try:host.apply('operator',approval,approval['proposal_digest'])
            except RuntimeError:pass
        assert host.status()['play_build_blocked']
        host=NativeMaterializationHost(project,lambda:None,host.gateway)
    app=FastAPI();install_reconciliation_routes(app,None,materialization_host=host)
    html=(ROOT/'packages/builder-workspace/server/native_reconciliation_review.html').read_text(encoding='utf-8').replace('src="/native-review.js"','src="/__proof/test.js"')
    @app.get('/__proof')
    async def page():return HTMLResponse(html)
    @app.get('/__proof/test.js')
    async def test():return Response(RECOVERY_TEST if args.recovery else TEST,media_type='text/javascript')
    @app.get('/__proof/state')
    async def state():return dict(baseline=(project/'.xace/authoring-baseline.native.json').exists(),cgs_unchanged=(project/'game.cgs.json').read_bytes()==before,blocked=host.status()['play_build_blocked'])
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        command=[str(browser),'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-extensions',f'--window-size={args.width},1000','--virtual-time-budget=45000','--dump-dom',f'--user-data-dir={out/"browser-profile"}',f'--screenshot={out/"review.png"}',f'http://127.0.0.1:{port}/__proof']
        result=subprocess.run(command,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'command.json').write_text(json.dumps(command,indent=2));(out/'dom.html').write_bytes(result.stdout);(out/'browser.log').write_bytes(result.stderr)
        assert result.returncode==0 and b'data-test-state="passed"' in result.stdout,result.stdout[-4000:].decode(errors='replace')
        proof=dict(ok=True,real_browser=str(browser),real_http=True,width=args.width,checks=5 if args.recovery else 7,recovery=args.recovery,filesystem_fixture=True,native_editor=False,verified_pair_written=True)
        (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
    finally:server.should_exit=True;thread.join(timeout=10)

if __name__=='__main__':main()

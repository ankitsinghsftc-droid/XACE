"""Real Chromium explicit review/apply proof; filesystem fixture, not a native editor."""
import asyncio,argparse,json,socket,subprocess,sys,threading,time,urllib.request
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
async function wait(test){for(let i=0;i<2000;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw new Error('UI timed out: '+get('status').textContent+' '+get('saved-status').textContent);}
try {
 get('refresh').click();await wait(()=>!get('approve').disabled);
 get('approve').click();await wait(()=>!get('apply').disabled);
 const proposal=get('proposal').textContent;
 get('watch-saved').checked=true;get('watch-saved').dispatchEvent(new Event('change'));
 await wait(()=>get('saved-status').textContent.includes('settle'));
 await fetch('/__proof/quiet');
 await wait(()=>get('saved-status').textContent.includes('available'));
 await fetch('/__proof/quiet');
 check(get('approve').disabled&&get('apply').disabled,'Notification retained approval');
 check(get('proposal').textContent===proposal,'Notification replaced review choices');
 let state;for(let i=0;i<100;i++){state=await(await fetch('/__proof/state')).json();if(state.observations.includes('unchanged'))break;await new Promise(r=>setTimeout(r,100));}
 check(state.observations.includes('unchanged'),'Unchanged saved revision was not suppressed');
 check(!state.baseline&&state.cgs_unchanged,'Monitor published project files');
 get('watch-saved').checked=false;get('watch-saved').dispatchEvent(new Event('change'));
 check(get('saved-status').textContent.includes('off'),'Monitor did not stop');
 get('refresh').click();await wait(()=>!get('approve').disabled);
 check(get('apply').disabled,'Fresh review reused old approval');
 check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
 document.body.dataset.testState='passed';document.body.dataset.checks='7';
} catch(error) {document.body.dataset.testState='failed';get('status').textContent=String(error.stack||error);}
'''



def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--width',type=int,default=1280);args=p.parse_args();out=args.out.resolve()
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();out.mkdir(parents=True)
    browser=next((p for p in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')] if p.exists()),None);assert browser
    from test_native_materialization_host import HostTests
    project=out/'project';project.mkdir()
    host,ctx=HostTests().fixture(project)
    before=(project/'game.cgs.json').read_bytes()
    observations=[];poll=host.poll_saved_changes
    def observe():
        result=poll();observations.append(result['state']);return result
    host.poll_saved_changes=observe
    app=FastAPI();install_reconciliation_routes(app,None,materialization_host=host)
    html=(ROOT/'packages/builder-workspace/server/native_reconciliation_review.html').read_text(encoding='utf-8').replace('src="/native-review.js"','src="/__proof/test.js"')
    @app.get('/__proof')
    async def page():return HTMLResponse(html)
    @app.get('/__proof/test.js')
    async def test():return Response(TEST,media_type='text/javascript')
    @app.get('/__proof/quiet')
    async def quiet():
        await asyncio.sleep(0.6)
        return dict(ok=True)
    @app.get('/__proof/state')
    async def state():return dict(baseline=(project/'.xace/authoring-baseline.native.json').exists(),cgs_unchanged=(project/'game.cgs.json').read_bytes()==before,blocked=host.status()['play_build_blocked'],observations=observations)
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        import urllib.request,base64
        from websockets.sync.client import connect
        command=[str(browser),'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-extensions','--remote-debugging-port=0',f'--user-data-dir={out/"browser-profile"}','about:blank']
        (out/'command.json').write_text(json.dumps(command))
        with (out/'browser.log').open('wb') as log:
            process=subprocess.Popen(command,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                port_file=out/'browser-profile/DevToolsActivePort'
                for _ in range(200):
                    if port_file.exists():break
                    time.sleep(.05)
                debug_port=int(port_file.read_text().splitlines()[0])
                targets=json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json'))
                with connect(next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page'),max_size=16*1024**2) as ws:
                    sequence=0
                    def call(method,params):
                        nonlocal sequence
                        sequence+=1;ws.send(json.dumps(dict(id=sequence,method=method,params=params)))
                        while True:
                            reply=json.loads(ws.recv(timeout=15))
                            if reply.get('id')==sequence:
                                assert 'error' not in reply,reply
                                return reply.get('result',{})
                    call('Emulation.setDeviceMetricsOverride',dict(width=args.width,height=1000,deviceScaleFactor=1,mobile=False))
                    call('Page.navigate',dict(url=f'http://127.0.0.1:{port}/__proof'))
                    for _ in range(600):
                        state=call('Runtime.evaluate',dict(expression='document.body && document.body.dataset.testState',returnByValue=True)).get('result',{}).get('value')
                        if state in ['passed','failed']:break
                        time.sleep(.05)
                    dom=call('Runtime.evaluate',dict(expression='document.documentElement.outerHTML',returnByValue=True))['result']['value']
                    (out/'dom.html').write_text(dom,encoding='utf-8')
                    png=call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))['data']
                    (out/'review.png').write_bytes(base64.b64decode(png))
                    assert state=='passed',dom[-2500:]
                    measured=call('Runtime.evaluate',dict(expression='innerWidth',returnByValue=True))['result']['value']
                    assert measured==args.width,measured
            finally:
                process.terminate();process.wait(timeout=15)
        proof=dict(ok=True,real_browser=str(browser),real_http=True,width=args.width,checks=7,quiet_seconds=0.5,filesystem_fixture=True,native_editor=False,verified_pair_written=False,monitor_only=True)
        (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
    finally:server.should_exit=True;thread.join(timeout=10)

if __name__=='__main__':main()

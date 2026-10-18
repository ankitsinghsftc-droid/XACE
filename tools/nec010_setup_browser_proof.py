"""Actual browser setup review/approval/apply; explicitly a filesystem fixture."""
import sys,json,socket,subprocess,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'packages/builder-workspace/server'),str(ROOT/'packages/project-system/tests')]
from fastapi import FastAPI
from fastapi.responses import HTMLResponse,Response
import uvicorn
from native_setup_routes import install_setup_routes
from test_native_setup_review import fixture
TEST=r'''
import '/native-setup.js';
const get=id=>document.getElementById(id);
const check=(ok,message)=>{if(!ok)throw Error(message);};
async function wait(test){for(let i=0;i<2000;i++){if(test())return;await new Promise(r=>setTimeout(r,20));}throw Error('Timed out: '+get('status').textContent);}
try {
check(get('apply').disabled,'Save enabled before review');get('open').click();await wait(()=>!get('approve').disabled);
check(get('files').textContent.includes('SHA-256:'),'Missing file preview');check(get('apply').disabled,'Review allowed unapproved save');
get('approve').click();await wait(()=>!get('apply').disabled);
let state=await(await fetch('/__proof/state')).json();check(!state.baseline&&!state.native,'Approval wrote files');
get('apply').click();await wait(()=>get('status').textContent.includes('saved and verified'));
state=await(await fetch('/__proof/state')).json();check(state.baseline&&state.native&&!state.blocked,'Saved pair not ready');
check(get('apply').disabled,'Approval reusable');check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
document.body.dataset.testState='passed';
}catch(error){document.body.dataset.testState='failed';get('status').textContent=String(error.stack||error);}
'''
def main(out,width):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists();out.mkdir(parents=True)
    project=out/'project';project.mkdir();host,review,_=fixture(project)
    app=FastAPI();install_setup_routes(app,review)
    html=(ROOT/'packages/builder-workspace/server/native_setup.html').read_text().replace('src="/native-setup.js"','type="module" src="/__proof/test.js"')
    @app.get('/__proof')
    async def page():return HTMLResponse(html)
    @app.get('/__proof/test.js')
    async def test():return Response(TEST,media_type='text/javascript')
    @app.get('/__proof/state')
    async def state():return dict(native=(project/'native.json').exists(),baseline=(project/'.xace/authoring-baseline.native.json').exists(),blocked=host.status()['play_build_blocked'])
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe');assert browser.exists()
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
                    call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1000,deviceScaleFactor=1,mobile=False))
                    call('Page.navigate',dict(url=f'http://127.0.0.1:{port}/__proof'))
                    for _ in range(600):
                        state=call('Runtime.evaluate',dict(expression='document.body && document.body.dataset.testState',returnByValue=True)).get('result',{}).get('value')
                        if state in ['passed','failed']:break
                        time.sleep(.05)
                    dom=call('Runtime.evaluate',dict(expression='document.documentElement.outerHTML',returnByValue=True))['result']['value']
                    (out/'dom.html').write_text(dom,encoding='utf-8')
                    png=call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))['data']
                    (out/'setup.png').write_bytes(base64.b64decode(png))
                    assert state=='passed',dom[-2500:]
                    measured=call('Runtime.evaluate',dict(expression='innerWidth',returnByValue=True))['result']['value']
                    assert measured==width,measured
            finally:
                process.terminate();process.wait(timeout=15)
        proof=dict(ok=True,real_browser=True,real_http=True,filesystem_fixture=True,native_editor=False,width=width,checks=7)
        (out/'proof.json').write_text(json.dumps(proof));print(json.dumps(proof))
    finally:server.should_exit=True;thread.join(timeout=10)
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),int(sys.argv[2]))

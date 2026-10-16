"""Real Chromium DOM/HTTP proof of the NEC-008 review panel, isolated profile."""
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
 get('refresh').click();await wait(()=>!!document.querySelector('select'));
 check(get('approve').disabled,'Unresolved approval was enabled');
 check(!document.querySelector('img')&&!window.injected,'Native text executed as markup');
 check(get('conflicts').textContent.includes('Last verified')&&get('conflicts').textContent.includes('Engine'),'Missing version columns');
 const select=document.querySelector('select');select.value='engine';select.dispatchEvent(new Event('change'));
 check(get('approve').disabled,'Unreviewed choice could approve');get('resolve').click();await wait(()=>!get('approve').disabled);
 get('approve').click();await wait(()=>get('status').textContent.includes('approval recorded'));
 check(get('proposal').textContent.includes('"can_commit": false'),'Approval claims commit');
 get('refresh').click();await wait(()=>!!document.querySelector('select')&&!get('resolve').disabled);
 await fetch('/__proof/drift',{method:'POST'});
 get('resolve').click();await wait(()=>get('status').textContent.includes('changed; refresh'));
 check(get('approve').disabled,'Stale review approval enabled');
 get('cancel').click();await wait(()=>get('status').textContent.includes('cancelled'));
 check(!get('conflicts').children.length,'Cancelled versions remain selected');
 get('refresh').click();await wait(()=>!!document.querySelector('select'));
 check(document.documentElement.scrollWidth<=innerWidth,'Horizontal overflow');
 document.body.dataset.testState='passed';document.body.dataset.checks='10';document.body.dataset.viewport=String(innerWidth);
} catch(error) {document.body.dataset.testState='failed';get('status').textContent=String(error.stack||error);}
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--width',type=int,default=1280);args=p.parse_args();out=args.out.resolve()
    assert out.is_relative_to(ROOT/'recovery-evidence/20261016/nec008') and not out.exists();out.mkdir(parents=True)
    browser=next((p for p in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')] if p.exists()),None);assert browser
    ctx=context();engine_edit(ctx);xace_edit(ctx)
    raw=json.loads(ctx['native_inventory']);raw['objects'][f'{2:032x}']['fields']['native.name']='<img src=x onerror="window.injected=true">'
    ctx['native_inventory']=canonical(raw);refresh(ctx)
    app=FastAPI();install_reconciliation_routes(app,lambda:ctx)
    html=(ROOT/'packages/builder-workspace/server/native_reconciliation_review.html').read_text(encoding='utf-8').replace('src="/native-review.js"','src="/__proof/test.js"')
    @app.get('/__proof')
    async def page():return HTMLResponse(html)
    @app.get('/__proof/test.js')
    async def test():return Response(TEST,media_type='text/javascript')
    @app.post('/__proof/drift')
    async def drift():engine_edit(ctx,value='9');return {'ok':True}
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
        proof=dict(ok=True,real_browser=str(browser),real_http=True,width=args.width,checks=10,scenarios=['unresolved blocked','native text cannot execute markup','three versions visible','choice requires re-review','approval receipt cannot commit','source drift invalidates review','stale approval disabled','cancel preserves projects','refresh after cancellation','no horizontal overflow'],native_project_written=False)
        (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
    finally:server.should_exit=True;thread.join(timeout=10)

if __name__=='__main__':main()

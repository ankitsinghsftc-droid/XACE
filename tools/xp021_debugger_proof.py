"""Actual browser walkthrough, historical verifier and independent running authority."""
import argparse,hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'packages/builder-workspace/server'))
from replay_debugger import ReplayDebugger,install_debugger_routes
from runtime_control_client import RuntimeControlClient,RuntimeControlConfig

def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
def serve(out,web,control,host,current):
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    app=FastAPI()
    install_debugger_routes(app,ReplayDebugger(out/'replays',(host,current),RuntimeControlClient(RuntimeControlConfig(port=control)),'proof-creator'))
    @app.get('/')
    def index():return FileResponse(out/'index.html')
    @app.get('/fixture.js')
    def script():return FileResponse(out/'fixture.js',media_type='text/javascript')
    uvicorn.run(app,host='127.0.0.1',port=web,log_level='warning')
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'recovery-evidence/xp021/walkthrough');p.add_argument('--serve',action='store_true');p.add_argument('--web',type=int);p.add_argument('--control',type=int);p.add_argument('--recording',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--current-host',type=Path,required=True);a=p.parse_args();out=a.out.resolve();package=a.package.resolve();host=a.current_host.resolve()
    if a.serve:return serve(out,a.web,a.control,package/'runtime/xace_runtime.exe',host)
    out.mkdir(parents=True,exist_ok=False);(out/'replays').mkdir()
    raw=a.recording.resolve().read_bytes();identity=hashlib.sha256(raw).hexdigest();(out/'replays'/f'{identity}.json').write_bytes(raw)
    workspace=ROOT/'packages/builder-workspace'
    subprocess.run(['node','--input-type=module','-e',"import {build} from 'esbuild'; await build({entryPoints:['tools/replay_debugger_browser_fixture.ts'],bundle:true,format:'esm',target:'chrome120',outfile:process.argv[1]});",str(out/'fixture.js')],cwd=workspace,check=True)
    (out/'index.html').write_text('<!doctype html><html><head><style>body{font:15px system-ui;background:#141820;color:#eee;padding:24px}button,input,select{padding:7px;margin:5px}pre{white-space:pre-wrap;max-height:300px;overflow:auto}label{display:block}</style></head><body><script type="module" src="/fixture.js"></script></body></html>')
    web,control,engine=port(),port(),port()
    command=[str(host),'--no-wait','--live-engine-accept','--port',str(engine),'--control-port',str(control),'--ruleset-root',str(out),'--quiet']
    for flag,name in [('cgs','game.cgs.json'),('sgc-plan','execution_plan.json'),('world','world.json'),('world-manifest','world.manifest.json')]:command+=['--'+flag,str(package/name)]
    processes=[];logs=[]
    def start(cmd,name):
        log=(out/name).open('w');logs.append(log);process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);processes.append(process);return process
    try:
        start(command,'authority.log');start([sys.executable,'-m','tools.xp021_debugger_proof','--serve','--out',str(out),'--web',str(web),'--control',str(control),'--recording',str(a.recording.resolve()),'--package',str(package),'--current-host',str(host)],'server.log')
        import urllib.request
        for _ in range(100):
            try:urllib.request.urlopen(f'http://127.0.0.1:{web}/api/debugger/recordings',timeout=1);break
            except OSError:time.sleep(.1)
        browser=next(path for path in [Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')] if path.exists())
        result=subprocess.run([str(browser),'--headless','--disable-gpu','--no-first-run',f'--user-data-dir={out/"browser-profile"}','--virtual-time-budget=30000','--dump-dom',f'--screenshot={out/"walkthrough.png"}','--window-size=1280,1000',f'http://127.0.0.1:{web}/'],capture_output=True,text=True,timeout=90)
        (out/'walkthrough.html').write_text(result.stdout,encoding='utf8');assert 'data-test-state="passed"' in result.stdout,result.stdout[-4000:]
        import html,re
        walkthrough=json.loads(html.unescape(re.search('data-walkthrough="([^"]+)"',result.stdout).group(1)))
        # Explicit creator pause/resume travels through the same HTTP boundary.
        for action in ['pause','play']:
            request=urllib.request.Request(f'http://127.0.0.1:{web}/api/debugger/control',data=json.dumps({'action':action,'confirm_session_wide':True}).encode(),headers={'content-type':'application/json','x-xace-creator-token':'proof-creator'})
            assert json.load(urllib.request.urlopen(request))['accepted']
        proof={'schema':'xace.xp021.creator_walkthrough.v1','ok':True,'walkthrough':walkthrough,'creator_pause_resume':True,'recording_id':identity,'scope':'Windows browser + actual historical host + separate running authority'}
        (out/'proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        for log in logs:log.close()
if __name__=='__main__':main()

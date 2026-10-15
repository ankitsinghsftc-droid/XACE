"""Observe native input framing without modifying the pinned authority or adapter."""
import sys, json, socket, threading, struct, hashlib, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools import xp017_mixed_session_proof as proof
BASE=ROOT/'recovery-evidence/20261015/xp022-ingress-batch'
OUT=BASE/'native-input-investigation';OUT.mkdir(exist_ok=False)
ART=BASE/'artifacts'
PROJECT=ROOT/'recovery-evidence/20261012/xp019/native/target-codex-task66-unreal-vertical-slice/XaceTask66.uproject'
original_write=proof.write
results=[]
for mode in ['observe','fragment','observe-repeat']:
    trace=OUT/(mode+'.wire.jsonl');stop=threading.Event();threads=[];sockets=[];lock=threading.Lock()
    def record(data):
        with lock:
            with trace.open('a',encoding='utf-8') as f:f.write(json.dumps(data,sort_keys=True)+'\n')
    def route(src,dst,direction):
        buffer=bytearray()
        try:
            while not stop.is_set():
                data=src.recv(65536)
                if not data:break
                buffer.extend(data)
                while len(buffer)>=4:
                    size=struct.unpack('<I',buffer[:4])[0]
                    if not 0<size<=4*1024*1024:raise ValueError('invalid frame')
                    if len(buffer)<size+4:break
                    frame=bytes(buffer[:size+4]);del buffer[:size+4]
                    obj=json.loads(frame[4:]);sync=obj.get('sync',{})
                    record(dict(direction=direction,kind=obj.get('msg_type'),tick=obj.get('tick'),next_tick=sync.get('next_tick'),sequence=sync.get('sequence'),bytes=len(frame),sha256=hashlib.sha256(frame).hexdigest()))
                    if mode=='fragment' and direction=='authority-to-unreal':
                        for piece in [frame[:1],frame[1:3],frame[3:7],frame[7:]]:
                            if piece:dst.sendall(piece)
                            time.sleep(.001)
                    else:dst.sendall(frame)
        except OSError as e:
            if not stop.is_set():record(dict(direction=direction,transport_closed=str(e)))
        except Exception as e:record(dict(direction=direction,error=repr(e)))
    def intercept(path,value):
        if Path(path).name=='unreal-config.json':
            value=dict(value);upstream=value['port'];listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(300);sockets.append(listener);value['port']=listener.getsockname()[1]
            def accept():
                try:
                    client,_=listener.accept();remote=socket.create_connection(('127.0.0.1',upstream),timeout=15);client.settimeout(300);remote.settimeout(300);sockets.extend([client,remote])
                    for a,b,d in [(client,remote,'unreal-to-authority'),(remote,client,'authority-to-unreal')]:
                        t=threading.Thread(target=route,args=(a,b,d),daemon=True);threads.append(t);t.start()
                except OSError as e:
                    if not stop.is_set():record(dict(error=repr(e)))
            t=threading.Thread(target=accept,daemon=True);threads.append(t);t.start()
        original_write(path,value)
    proof.write=intercept
    try:
        result=proof.scenario(OUT/mode,['unity','godot','unreal','player'],ART/'build',PROJECT,dict(parent=ART/'parent',candidate=ART/'candidate',record_replay=True))
        results.append(dict(mode=mode,ok=result['ok']))
    except Exception as e:
        results.append(dict(mode=mode,ok=False,error=repr(e)))
        raise
    finally:
        proof.write=original_write;stop.set()
        for s in sockets:
            try:s.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            s.close()
        for t in threads:t.join(timeout=2)
        (OUT/'progress.json').write_text(json.dumps(results,indent=2))
    print(mode+' passed',flush=True)
(OUT/'summary.json').write_text(json.dumps(dict(results=results,scope='Diagnostic real TCP proxy, no runtime or adapter changes; passing does not prove historical root cause.'),indent=2))

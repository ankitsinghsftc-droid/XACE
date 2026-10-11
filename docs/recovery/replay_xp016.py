"""Replay reviewed XP-016 text patches into the independent recovery worktree only.
Never execute arbitrary transcript commands. Exact-context matching; use the patch tool's first-forward-match ordering.
"""
from pathlib import Path
import json,re,hashlib,subprocess,sys
ROOT=Path(r'C:\Users\ankit\XACE-Recovery')
WORK=ROOT/'worktrees/xace'
INPUT=ROOT/'reconstruction/xp016'
LEDGER=INPUT/'applied.json'
PREFIX='C:/Users/ankit/Downloads/xace/target/xp016-work/'
def target(raw):
 assert raw.startswith(PREFIX),raw
 rel=raw[len(PREFIX):];p=WORK/rel
 assert p.resolve().is_relative_to(WORK.resolve()) and not set(Path(rel).parts)&{'target','tmp','.git'},raw
 return p

def apply(patch):
 lines=patch.splitlines();assert lines[0]=='*** Begin Patch'
 changes={};i=1
 while i<len(lines) and lines[i]!='*** End Patch':
  header=lines[i];i+=1
  if header.startswith('*** Add File: '):
   p=target(header[14:]);assert not p.exists() and p not in changes,str(p)
   content=[]
   while i<len(lines) and not lines[i].startswith('*** '):
    assert lines[i].startswith('+'),lines[i];content.append(lines[i][1:]);i+=1
   changes[p]='\n'.join(content)+'\n'
  elif header.startswith('*** Update File: '):
   p=target(header[17:]);original=p.read_text(encoding='utf8');data=original.splitlines();cursor=0
   while i<len(lines) and not lines[i].startswith(('*** Add','*** Update','*** Delete','*** End Patch')):
    anchor=lines[i];assert anchor.startswith('@@'),anchor;i+=1
    if anchor.startswith('@@ '):
     key=anchor[3:];matches=[j for j in range(cursor,len(data)) if data[j]==key]
     assert matches,('anchor',p,key);cursor=matches[0]+1
    old=[];new=[];eof=False
    while i<len(lines) and not lines[i].startswith(('@@','*** ')):
     line=lines[i];i+=1
     assert line and line[0] in ' +-',(p,line)
     if line[0] in ' -':old.append(line[1:])
     if line[0] in ' +':new.append(line[1:])
    if i<len(lines) and lines[i]=='*** End of File':eof=True;i+=1
    if not old:pos=len(data)
    else:
     matches=[j for j in range(cursor,len(data)-len(old)+1) if data[j:j+len(old)]==old and (not eof or j+len(old)==len(data))]
     assert matches,('context matches',str(p),len(matches),'\n'.join(old)[:180])
     pos=matches[0]
    data[pos:pos+len(old)]=new;cursor=pos+len(new)
   changes[p]='\n'.join(data)+'\n'
  else:raise RuntimeError('Unapproved operation '+header)
 result=[]
 for p,text in changes.items():
  before=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
  p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf8',newline='\n')
  result.append({'path':p.relative_to(WORK).as_posix(),'before_sha256':before,'after_sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 return result

def main():
 ledger=json.loads(LEDGER.read_text()) if LEDGER.exists() else []
 done={x['line'] for x in ledger}
 for item in json.loads((INPUT/'catalog.json').read_text()):
  ln=item['line']
  if ln in done:continue
  if ln>7830:break
  if item['failed']:
   ledger.append({'line':ln,'status':'excluded-original-failed-call'});LEDGER.write_text(json.dumps(ledger,indent=2));continue
  result=[]
  for name in item['patches']:result+=apply((INPUT/name).read_text(encoding='utf8'))
  if ln==7102:
   # Reviewed original shell edit: only shared Godot mirror and Player wrapper.
   s=(INPUT/f'{ln}-call.js').read_text(encoding='utf8');m=re.search(r'cmd:\s*',s);cmd,_=json.JSONDecoder().raw_decode(s[m.end():]);code=cmd.split("@'\n",1)[1].split("\n'@ | python",1)[0]
   assert 'shared.write_text' in code and 'player.write_text' in code
   subprocess.run([sys.executable,'-B','-c',code],cwd=WORK,check=True)
   result.append({'reviewed_shell_edit':'shared Godot canonical mirror and Player wrapper'})
  ledger.append({'line':ln,'status':'replayed-source-only','changes':result,'historical_output_line':item['result_line']});LEDGER.write_text(json.dumps(ledger,indent=2))
  print('REPLAYED',ln,len(result),flush=True)
if __name__=='__main__':main()

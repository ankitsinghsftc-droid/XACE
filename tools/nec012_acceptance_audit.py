"""Read-only source/evidence acceptance audit; writes only a new requested receipt."""
from pathlib import Path
import hashlib,json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
COMPACT=ROOT/'docs/evidence/nec012-completion-20261024'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def audit(source_commit):
    summary=json.loads((COMPACT/'summary.json').read_bytes())
    committed_sources={}
    for path,expected in summary['source_files'].items():
        assert sha(ROOT/path)==expected,path
        committed=subprocess.check_output(['git','show',source_commit+':'+path],cwd=ROOT)
        # Windows core.autocrlf=true: preserve raw tested checkout SHA and
        # separately verify Git's filtered blob identity, without rewriting either.
        filtered=subprocess.check_output(['git','hash-object','--path='+path,path],cwd=ROOT,text=True).strip()
        blob=subprocess.check_output(['git','rev-parse',source_commit+':'+path],cwd=ROOT,text=True).strip()
        assert filtered==blob,path
        committed_sources[path]=dict(git_blob=blob,git_content_sha256=hashlib.sha256(committed).hexdigest(),tested_checkout_sha256=expected)
    for name,row in summary['proofs'].items():
        path=COMPACT/row['file'];assert sha(path)==row['sha256'];proof=json.loads(path.read_bytes());assert proof['ok']
        assert proof.get('launcher_sha256',proof.get('new_launcher_sha256'))==summary['launcher_sha256']
    executable=ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe'
    assert sha(executable)==summary['launcher_sha256']
    lifecycle=json.loads((COMPACT/'lifecycle.json').read_bytes());assert len(lifecycle['checks'])==19 and all(lifecycle['checks'].values())
    counts=[]
    for i in range(3):
        log=(COMPACT/f'regression-{i}.txt').read_bytes();match=re.search(rb'Ran (\d+) tests?',log);assert match and b'\nOK' in log;counts.append(int(match[1]))
    assert counts==[291,208,14] and b'11 passed; 0 failed' in (COMPACT/'launcher-tests.txt').read_bytes()
    seal=json.loads((COMPACT/'seal.json').read_bytes());assert seal['ok'] and len(seal['protected_files'])==55
    for row in seal['protected_files']:assert sha(Path(row['path']))==row['sha256']
    return dict(schema='xace.nec012.acceptance_audit.v1',ok=True,source_commit=source_commit,source_identities=committed_sources,launcher_sha256=summary['launcher_sha256'],python_tests=sum(counts),rust_tests=11,lifecycle_checks=19,recovered_seal_files_unchanged=55,scope='Shared Windows native-host service; native editor/build certification remains NEC013-015',clean_machine_certified=False,steam_certified=False)
if __name__=='__main__':
    out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists()
    result=audit(sys.argv[2]);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

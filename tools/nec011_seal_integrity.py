"""Verify immutable recovered XP022 bytes; separately report current source drift.
Unlike the NEC001 handoff gate, NEC011 permits version-controlled new source.
This never rewrites the baseline or certifies the missing original historical seal.
"""
import json,hashlib,zipfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=Path('C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def verify():
    receipt=json.loads((ROOT/'docs/recovery/evidence/xp022-closeout-20261015/baseline-receipt.json').read_text())
    assert sha(BASE/'baseline.json')==receipt['sha256']
    baseline=json.loads((BASE/'baseline.json').read_text());protected=[]
    assert baseline['schema']=='xace.recovery_baseline.v1' and not baseline['original_seal']
    for row in baseline['files']:
        p=(BASE/row['path']).resolve();assert p.is_relative_to(BASE.resolve())
        assert p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],str(p)
        protected.append(dict(path=str(p),sha256=row['sha256']))
    protected.append(dict(path=str(BASE/'baseline.json'),sha256=receipt['sha256']))
    source=json.loads((BASE/'source-manifest.json').read_text());drift=[]
    with zipfile.ZipFile(BASE/'source.zip') as archive:
        assert sorted(archive.namelist())==sorted(r['path'] for r in source['files'])
        for row in source['files']:
            assert hashlib.sha256(archive.read(row['path'])).hexdigest()==row['sha256']
            p=(ROOT/row['path']).resolve();assert p.is_relative_to(ROOT)
            current=sha(p) if p.is_file() else None
            if current!=row['sha256']:drift.append(dict(path=row['path'],baseline_sha256=row['sha256'],current_sha256=current))
    return dict(schema='xace.nec011.seal_integrity.v1',ok=True,original_seal=False,protected_files=protected,baseline_manifest_sha256=receipt['sha256'],source_archive_entries=len(source['files']),current_source_deviations=drift,release_certified=False)
if __name__=='__main__':
    out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();out.parent.mkdir(parents=True,exist_ok=True)
    result=verify();out.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='protected_files'},indent=2))

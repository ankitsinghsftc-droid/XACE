"""Versioned native-resource bindings inside existing presentation variants.
Pure data: no filesystem access, native decoding, gameplay or CGS mutation.
"""
from playable_package import require,safe_path,parse,encode,digest,MAX_FILE_BYTES,MAX_FILES
ENGINES={'godot','unity','unreal'}
SCHEMA='xace.native_package_resources.v1'
LOCATION_FIELDS=('source','path','file_path','resolved_path')

def _assets(cgs):
 rows=cgs.get('assets',[])
 require(type(rows) is list and all(type(a) is dict and type(a.get('id')) is str for a in rows),'Invalid asset registry')
 result={a['id']:a for a in rows};require(len(result)==len(rows),'Duplicate asset IDs');return result

def verify_catalogs(cgs,files):
 """Return exact (asset ID, original source) pairs backed by packaged native bytes."""
 assets=_assets(cgs);covered=set()
 for engine in sorted(ENGINES):
  name=f'presentation/{engine}/native-resources.json'
  if name not in files:continue
  catalog=parse(files[name]);require(type(catalog) is dict and set(catalog)=={'schema','engine','assets'} and catalog['schema']==SCHEMA and catalog['engine']==engine,'Invalid native resource catalog')
  rows=catalog['assets'];require(type(rows) is list and len(rows)<=MAX_FILES,'Native resource count limit')
  seen=set();ordered=[]
  for row in rows:
   require(type(row) is dict and set(row)=={'id','asset_type','source','path','sha256'},'Invalid native resource record')
   aid=row['id'];require(type(aid) is str and aid in assets and aid not in seen,'Foreign/duplicate native resource');seen.add(aid);ordered.append(aid)
   asset=assets[aid];source=row['source'];safe_path(source);safe_path(row['path'])
   require(not source.startswith('presentation/') and row['path']==f'presentation/{engine}/{source}','Native resource namespace mismatch')
   require(asset.get('status')=='LINKED' and asset.get('source')==source and asset.get('asset_type')==row['asset_type'],'Native resource differs from CGS')
   require({key for key in LOCATION_FIELDS if asset.get(key)}=={'source'},'Ambiguous native resource locations')
   require(row['path'] in files and digest(files[row['path']])==row['sha256'],'Missing/tampered native resource bytes')
   covered.add((aid,source))
  require(ordered==sorted(ordered),'Native resource records must be sorted')
 return covered

def prepare_resources(cgs,engine,resources):
 """Build a catalog from explicit project-relative resource byte inputs."""
 require(engine in ENGINES and type(resources) is dict and len(resources)<=MAX_FILES,'Invalid native resource inputs')
 files={}
 for source,data in sorted(resources.items()):
  safe_path(source);require(not source.startswith('presentation/') and type(data) is bytes and len(data)<=MAX_FILE_BYTES,'Invalid native resource payload')
  target=f'presentation/{engine}/{source}';safe_path(target);files[target]=data
 records=[]
 for aid,asset in sorted(_assets(cgs).items()):
  source=asset.get('source')
  if not source or source.startswith('presentation/'):continue
  safe_path(source);require(source in resources,'Native linked resource bytes were not supplied: '+aid)
  records.append(dict(id=aid,asset_type=asset['asset_type'],source=source,path=f'presentation/{engine}/{source}',sha256=digest(resources[source])))
 name=f'presentation/{engine}/native-resources.json';require(name not in files,'Reserved native resource catalog path')
 files[name]=encode(dict(schema=SCHEMA,engine=engine,assets=records));verify_catalogs(cgs,files);return files

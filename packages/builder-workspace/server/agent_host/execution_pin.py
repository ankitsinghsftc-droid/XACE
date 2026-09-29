"""Non-secret local provenance for operator-built execution artifacts."""
import json
import os
from pathlib import Path
import re
import tempfile

BASE_IMAGE = 'python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e'
PACKAGE_INTEGRITY = 'atv3HF0mubqB0J/XkQ2JopqKzXJ+/7aQtTB2MkJ9MrraujMIz8zbCCLylLkN3PzpVGTJzzQFN/wD1oq8oJPJKg=='
SCHEMA = 'xace.execution_artifact_pin.v1'


def pin_path():
    configured=os.environ.get('XACE_EXECUTION_STATE_PATH')
    if configured: return Path(configured).resolve()
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'XACE/agent-execution/backend.json'


def pinned_image(fallback):
    path=pin_path()
    if not path.exists(): return fallback
    value=json.loads(path.read_text(encoding='utf8'))
    if (not isinstance(value,dict) or value.get('schema')!=SCHEMA or value.get('base_image')!=BASE_IMAGE or
        value.get('package_integrity')!=PACKAGE_INTEGRITY or
        not re.fullmatch(r'sha256:[0-9a-f]{64}',str(value.get('image_id','')))):
        raise ValueError('Invalid isolated runtime pin; repair setup')
    return value['image_id']


def record_build(image_id, *, repair_invalid=False):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image_id): raise ValueError('Invalid image identity')
    path=pin_path(); path.parent.mkdir(parents=True,exist_ok=True)
    previous=None
    if path.exists():
        try: previous=pinned_image('')
        except (ValueError,TypeError):
            if not repair_invalid: raise
    value={'schema':SCHEMA,'image_id':image_id,'previous_image_id':previous,
           'base_image':BASE_IMAGE,'package_integrity':PACKAGE_INTEGRITY,'provenance':'operator_local_verified_build'}
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as file:
        json.dump(value,file,sort_keys=True); file.flush(); os.fsync(file.fileno()); temporary=Path(file.name)
    os.replace(temporary,path)
    return value

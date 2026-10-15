"""Explicit trusted Blueprint-project staging, with no Unreal launch or source writes.

The staged project remains capable of executing its own editor/plugin code when a
separately authorized caller opens it. This is a checked copy, not a sandbox.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from authoring_identity import canonical, require


def _regular(path: Path) -> None:
    info = path.lstat()
    require(not path.is_symlink() and not (getattr(info, 'st_file_attributes', 0) &
            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)), 'Linked project content refused')


def _hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(project_file: Path) -> dict:
    project_file = Path(project_file).absolute()
    for parent in [project_file, *project_file.parents]: _regular(parent)
    require(project_file.suffix == '.uproject' and project_file.is_file(), 'Unreal project descriptor required')
    descriptor = json.loads(project_file.read_text(encoding='utf-8-sig'))
    require(type(descriptor) is dict and not descriptor.get('Modules'),
            'Native C++ project modules require a separately certified build/staging profile')
    root = project_file.parent
    files = [project_file]
    for directory in ['Content', 'Config', 'Plugins']:
        top = root/directory
        if not top.exists(): continue
        _regular(top)
        for base, dirs, names in os.walk(top, followlinks=False):
            for name in dirs + names: _regular(Path(base)/name)
            # Build caches are not needed in a trusted source/content copy.
            dirs[:] = sorted(d for d in dirs if d not in {'Intermediate', 'Saved', 'DerivedDataCache'})
            files.extend(Path(base)/name for name in sorted(names))
            require(len(files) <= 20000, 'Staging file limit')
    require(sum(p.stat().st_size for p in files) <= 2 * 1024**3, 'Staging byte limit')
    rows = [dict(path=p.relative_to(root).as_posix(), sha256=_hash(p),
                 bytes=str(p.stat().st_size)) for p in sorted(files)]
    return dict(schema='xace.unreal_trusted_copy_inventory.v1', project=project_file.name, files=rows)


def stage(project_file: Path, destination: Path, *, trusted_project: bool,
          expected_inventory_digest: str) -> dict:
    require(trusted_project is True, 'Explicit trusted-project approval required')
    source = Path(project_file).absolute()
    dest = Path(destination).absolute()
    for parent in [dest.parent, *dest.parent.parents]:
        if parent.exists(): _regular(parent)
    for parent in [source, *source.parents]: _regular(parent)
    source = source.resolve(strict=True)
    dest = dest.resolve()
    require(not dest.exists() and not dest.is_relative_to(source.parent)
            and not source.parent.is_relative_to(dest), 'Fresh independent destination required')
    observed = inventory(source)
    require(hashlib.sha256(canonical(observed)).hexdigest() == expected_inventory_digest,
            'Source inventory changed since approval')
    dest.mkdir(parents=True)
    for row in observed['files']:
        src = source.parent/row['path']; target = dest/row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        _regular(src)
        shutil.copyfile(src, target)
        require(_hash(target) == row['sha256'], 'Source changed during copy; staged copy incomplete')
    require(inventory(source) == observed, 'Source drift during copy; staged copy incomplete')
    receipt = dict(schema='xace.unreal_trusted_copy_receipt.v1', source=str(source),
                   inventory=observed, inventory_digest=expected_inventory_digest,
                   trusted_project=True, engine_launched=False)
    (dest/'xace-trusted-copy.json').write_bytes(canonical(receipt))
    return receipt

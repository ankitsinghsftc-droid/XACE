"""Stage a fresh package from existing source artifacts and an explicitly pinned host."""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'packages'), str(ROOT/'packages/project-system')]
from tools.xp007_package_proof import compile_plan
from playable_package import RuntimeSupport, build_package, digest


def stage(base, host, out):
    if out.exists(): raise ValueError('choose a new package output directory')
    cgs = json.loads((base/'game.cgs.json').read_text())
    plan, compiled = compile_plan(cgs)
    runtime = host.read_bytes()
    support = RuntimeSupport(digest(runtime), 'xace.runtime_executor.v1', tuple(compiled.to_sgc_input()))
    visuals = {p.relative_to(base).as_posix():p.read_bytes() for p in (base/'presentation').rglob('*') if p.is_file() and p.suffix != '.import'}
    archive = build_package(cgs, plan, runtime, support, package_id='reference.activation', version='1.0.0', presentation_files=visuals)
    with zipfile.ZipFile(io.BytesIO(archive)) as z: z.extractall(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'host', 'out'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args(); stage(args.base.resolve(), args.host.resolve(), args.out.resolve())

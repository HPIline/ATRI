"""Pack reproducible review artifacts below GitHub's individual-file limit.

The archives preserve complete STEP/STL data. They are not manufacturing release
certificates; every package includes the current open-gate status.
"""
from pathlib import Path
import gzip
import hashlib
import json
import shutil
import zipfile


def package(out):
    out=Path(out);dest=out/'packages';dest.mkdir(exist_ok=True)
    step=out/'cad/ATRI-v2-review.step'
    if not step.is_file():raise FileNotFoundError(step)
    with step.open('rb') as source,(dest/'ATRI-v2-review.step.gz').open('wb') as target:
        with gzip.GzipFile(filename='',fileobj=target,mode='wb',mtime=0,compresslevel=9) as compressed:shutil.copyfileobj(source,compressed)
    for folder,filename in [('manufacturing','ATRI-v2-manufacturing-review.zip'),('sim','ATRI-v2-simulation-review.zip')]:
        paths=sorted(p for p in (out/folder).rglob('*') if p.is_file())
        if not paths:raise ValueError('Empty artifact folder '+folder)
        with zipfile.ZipFile(dest/filename,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for path in paths:
                info=zipfile.ZipInfo(str(path.relative_to(out)),date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,path.read_bytes())
            info=zipfile.ZipInfo('GATES-OPEN.json',date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,(out/'gates.json').read_bytes())
        with zipfile.ZipFile(dest/filename) as check:
            if check.testzip() is not None:raise ValueError('Archive CRC verification failed')
    with gzip.open(dest/'ATRI-v2-review.step.gz','rb') as source:
        restored=hashlib.file_digest(source,'sha256').hexdigest()
    with step.open('rb') as source:expected=hashlib.file_digest(source,'sha256').hexdigest()
    if restored!=expected:raise ValueError('STEP compression round-trip failed')
    rows=[]
    for path in sorted(dest.iterdir()):
        if path.suffix not in ('.zip','.gz'):continue
        size=path.stat().st_size
        if size>=100*1024*1024:raise ValueError('Artifact exceeds GitHub per-file limit: '+path.name)
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        rows.append(dict(file=path.name,bytes=size,sha256=digest))
    result=dict(release_ready=False,gate_status='G0-G4 OPEN',step_uncompressed_sha256=expected,artifacts=rows)
    (dest/'checksums.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':print(json.dumps(package(Path(__file__).parent/'out')))

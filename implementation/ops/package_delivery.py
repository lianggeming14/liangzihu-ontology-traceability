"""Package an explicit source allowlist; never include live data or credentials."""
from pathlib import Path
import hashlib
import json
import zipfile

BASE=Path(__file__).resolve().parents[1]
OUTPUT=BASE.parent / '交付文档' / '梁子湖农业本体数据库_本地工程版_v0.3.zip'
DIRECTORIES=('agri','migrations','contracts','web','ops','tests')
FILES=('README.txt','LEGACY_KIMI.txt','验证结果.txt','启动说明.txt','启动系统.cmd','run_server.py','requirements.txt','requirements-postgresql.txt','requirements-media.txt','PLATFORM_INTEGRATION.txt','DEVICE_PLATFORM_MAPPING.txt','DATA_INTAKE_GUIDE.txt','DATABASE_CORE_V0.3.txt','IMPLEMENTATION_STATUS.json','database-gate.json','.gitignore')
SUFFIXES={'.py','.sql','.json','.html','.css','.js','.cjs','.txt','.xml','.png'}

def collect():
    files=[]
    for name in FILES:
        path=BASE/name
        if not path.is_file():
            raise RuntimeError('Missing release file: '+name)
        files.append(path)
    for directory in DIRECTORIES:
        for path in (BASE/directory).rglob('*'):
            relative=path.relative_to(BASE)
            if any(part.startswith('.') or part=='__pycache__' or part.startswith('agri-ui-') for part in relative.parts):
                continue
            if path.is_file() and path.suffix in SUFFIXES:
                files.append(path)
    for name in ('api-contract-check.json','environment-status.json','sqlite-adapter-check.json','sqlite-backup-check.json','http-intake-check.json'):
        path=BASE/'runtime'/name
        if path.is_file(): files.append(path)
    return sorted(set(files),key=lambda p:p.relative_to(BASE).as_posix())


def main():
    selected=collect()
    OUTPUT.parent.mkdir(exist_ok=True)
    manifest={'format':'agri-source-release/1','version':'0.3.0','excludes':['live databases','raw evidence assets','tokens and passwords','Kimi runtime and historical logs','downloaded dependencies','PostgreSQL binaries'],'files':[]}
    with zipfile.ZipFile(OUTPUT,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            relative=path.relative_to(BASE).as_posix()
            raw=path.read_bytes()
            archive.writestr('implementation/'+relative,raw)
            manifest['files'].append({'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
        archive.writestr('RELEASE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(OUTPUT) as archive:
        if archive.testzip() is not None: raise RuntimeError('ZIP integrity failed')
        names=archive.namelist()
        forbidden=('implementation/data/','implementation/.kimi','api-tokens.json','pg-local-password.txt')
        if any(any(token in name for token in forbidden) for name in names):
            raise RuntimeError('Unexpected private file in release')
    checksum=hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix('.zip.sha256.txt').write_text(checksum+'  '+OUTPUT.name+chr(10),encoding='utf-8')
    print(json.dumps({'archive':str(OUTPUT),'file_count':len(selected),'bytes':OUTPUT.stat().st_size,'sha256':checksum},ensure_ascii=False))

if __name__=='__main__':main()

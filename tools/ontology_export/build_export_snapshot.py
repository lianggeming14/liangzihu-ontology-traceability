"""Create a bounded, reviewed incremental export snapshot; no git/network mutation."""
from pathlib import Path
import sys, json, os
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from build_github_snapshot import zip_bytes,groups_for,stable_read
from restore_github_snapshot import checked_path,forbidden_reason,scan_secrets,digest,FORMAT,ARCHIVE_LIMIT,FILE_LIMIT,TOTAL_LIMIT,FILE_COUNT_LIMIT,load_verified
paths=['.gitignore']
for folder in ['tools/ontology_export','outputs/liangzihu-ontology-20261015']:
 for base,dirs,files in os.walk(ROOT/folder,followlinks=False):
  dirs[:]=[d for d in dirs if d not in {'node_modules','__pycache__','.pytest_cache'}]
  for name in files:
   if name.endswith('.xlsx.inspect.ndjson'):continue
   paths.append((Path(base)/name).relative_to(ROOT).as_posix())
payloads=[]
for name in sorted(set(paths)):
 checked_path(name)
 reason=forbidden_reason(name)
 if reason:raise RuntimeError(name+': '+reason)
 data,_=stable_read(ROOT,name);scan_secrets(data,name);payloads.append((name,data))
if len(payloads)>FILE_COUNT_LIMIT or sum(len(d) for _,d in payloads)>TOTAL_LIMIT:raise RuntimeError('snapshot budget exceeded')
out=ROOT/'.github-upload/ontology-export';out.mkdir(parents=True,exist_ok=True)
manifest={'format':FORMAT,'created_at':datetime.now(timezone.utc).isoformat(),'source':{'selection_mode':'reviewed-incremental','scope':['tools/ontology_export','outputs/liangzihu-ontology-20261015','.gitignore']},'limits':{'archive_bytes':ARCHIVE_LIMIT,'file_bytes':FILE_LIMIT,'total_bytes':TOTAL_LIMIT,'file_count':FILE_COUNT_LIMIT},'archives':[],'files':[],'excluded':['source-cache','live-database','credentials','node_modules']}
for index,group in enumerate(groups_for(payloads),101):
 name=f'snapshot-{index:03d}.zip';packed=zip_bytes(group);(out/name).write_bytes(packed)
 manifest['archives'].append({'name':name,'size':len(packed),'sha256':digest(packed),'file_count':len(group),'uncompressed_size':sum(len(d) for _,d in group)})
 for p,d in group:manifest['files'].append({'path':p,'archive':name,'size':len(d),'sha256':digest(d)})
p=out/'snapshot-manifest.json';p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
_,verified=load_verified(p)
print(json.dumps({'status':'verified','files':len(verified),'archives':manifest['archives'],'output':str(out)},ensure_ascii=False))

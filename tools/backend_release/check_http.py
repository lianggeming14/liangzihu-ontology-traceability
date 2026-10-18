"""Read-only release HTTP check and rolled-back synthetic preview on loopback."""
from pathlib import Path
import http.cookiejar
import json
import sys
import urllib.request
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'implementation'))
from integrations.liangzihu import load_bundle,load_profile,read_records,make_batch
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def request(path,body=None):
    data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None
    req=urllib.request.Request('http://127.0.0.1:8787/api/v1'+path,data=data,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=60) as response:result=json.load(response)
    return result.get('data',result)
health=request('/health')
request('/auth/demo',{'role':'admin'})
before=request('/stats')['counts']
profile=request('/integration/profiles?source_id=liangzihu-platform')['items']
assert len(profile)==1
records,meta=read_records(ROOT/'implementation/integrations/liangzihu/synthetic-core-example.json')
payload=load_bundle('synthetic-http-release-check')
payload['batch']=make_batch(load_profile('synthetic-http-release-check'),records,meta['observed_at'],'release-preview-20261019','synthetic')
preview=request('/integration/bundles/preview',payload)
after=request('/stats')['counts']
assert before==after,'Preview changed persistent counts'
assert request('/integration/profiles?source_id=synthetic-http-release-check')['items']==[]
spec=request('/openapi.json')
assert health['version']=='0.4.0'
result={'checked_at':datetime.now(timezone.utc).isoformat(),'transport':'actual_loopback_HTTP','health':health,
        'installed_source_profiles':len(profile),'installed_source_tables':len(profile[0]['definition']['tables']),
        'synthetic_preview_counts':preview['batch']['counts'],'preview_rolled_back':True,
        'entity_count_before':before['entities'],'entity_count_after':after['entities'],
        'documented_operations':sum(len(v) for v in spec['paths'].values()),'postgresql_verified':False,
        'production_records_imported':False}
(ROOT/'outputs/backend-integration-20261019/http-release-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))

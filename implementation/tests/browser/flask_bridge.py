"""Real Flask HTTP-boundary bridge for UI tests where listening sockets are disabled."""
import base64
import json
import tempfile
import sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE));sys.path.insert(0,str(BASE/'.deps'))
from agri.app import create_app
temporary=tempfile.TemporaryDirectory(prefix='agri-ui-',dir=str(BASE/'tests'/'browser'))
app=create_app({'DATABASE_URL':'sqlite:///'+str(Path(temporary.name)/'ui.db'),'ALLOWED_HOSTS':['localhost','127.0.0.1'],'DEMO_MODE':True})
from agri.seed import seed_demo
manifest=seed_demo(app.extensions['agri_service'],BASE,persist_manifest=False)
client=app.test_client(use_cookies=False)
print(json.dumps({'ready':True,'public_code':manifest['public_code']}),flush=True)
for line in sys.stdin:
    try:
        item=json.loads(line)
        response=client.open(item['path'],method=item.get('method','GET'),
                  headers=item.get('headers',{}),data=base64.b64decode(item.get('body','')),
                  base_url='http://localhost:8787',environ_base={'REMOTE_ADDR':'127.0.0.1'})
        print(json.dumps({'id':item['id'],'status':response.status_code,'headers':dict(response.headers),
                          'body':base64.b64encode(response.data).decode()}),flush=True)
    except Exception as exc:
        print(json.dumps({'id':item.get('id'),'error':str(exc)}),flush=True)

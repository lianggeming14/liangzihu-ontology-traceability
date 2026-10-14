"""Local engineering server; binds loopback and seeds only explicit demo data."""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE / '.deps'))
from agri.app import create_app

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8787)
    p.add_argument('--no-seed',action='store_true')
    p.add_argument('--open-browser',action='store_true')
    p.add_argument('--no-demo-login',action='store_true')
    args=p.parse_args()
    data=BASE / 'data';data.mkdir(exist_ok=True)
    tokens_file=data / 'api-tokens.json'
    if not tokens_file.exists():
        tokens={secrets.token_urlsafe(32): {'id':'local-api-admin','tenant_id':'demo-farm','roles':['admin']}}
        tokens_file.write_text(json.dumps(tokens,indent=2),encoding='utf-8')
    app=create_app({'DEMO_MODE':not args.no_demo_login})
    if not args.no_seed:
        from agri.seed import seed_demo
        from agri.service import Service
        from agri.ontology_core import seed_core_demo
        manifest=seed_demo(Service(app.extensions['agri_db']),BASE)
        seed_core_demo(app.extensions['agri_service'],BASE)
        print('Synthetic demo is ready. Public path: /trace/'+manifest['public_code'],flush=True)
    print('Local engineering application: http://127.0.0.1:'+str(args.port),flush=True)
    print('Backend: '+app.extensions['agri_db'].backend+'; PostgreSQL and field validation are separate gates.',flush=True)
    if args.open_browser:
        import threading, webbrowser
        threading.Timer(1.0, lambda: webbrowser.open('http://127.0.0.1:'+str(args.port))).start()
    app.run(host='127.0.0.1',port=args.port,debug=False,use_reloader=False)

if __name__=='__main__':main()

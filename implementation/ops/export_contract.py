"""Regenerate and verify the implemented API contract without opening a port."""
from pathlib import Path
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from agri.app import create_app
from jsonschema import Draft202012Validator

with tempfile.TemporaryDirectory(prefix='agri-contract-') as folder:
    app=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///'+str(Path(folder)/'contract.db'),'DEMO_MODE':False})
    contract=app.test_client().get('/api/v1/openapi.json').json
    actual=set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api/v1/'):continue
        path=re.sub(r'<(?:[^:>]+:)?([^>]+)>',r'{\1}',rule.rule)
        actual.update((path,m.lower()) for m in rule.methods-{'OPTIONS','HEAD'})
    documented={(p,m) for p,ops in contract['paths'].items() for m in ops if m in {'get','post','put','patch','delete'}}
    if actual!=documented:raise RuntimeError('Route contract mismatch: '+repr(actual^documented))
    for schema in contract['components']['schemas'].values():Draft202012Validator.check_schema(schema)
    (BASE/'contracts/openapi.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'implemented_api_operations':len(actual),'documented_api_operations':len(documented),'operation_set_matches':True,'json_schemas_checked':len(contract['components']['schemas']),'json_schema_valid':True,'contract_file':'contracts/openapi.json','scope':'Route coverage and JSON Schema syntax; response payloads are not fully typed'}
    (BASE/'runtime/api-contract-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

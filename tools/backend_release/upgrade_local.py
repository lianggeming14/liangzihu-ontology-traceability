"""Install reviewed source definitions into an explicit local SQLite database.

Default: consistent copy, migrate and preview only. --apply creates a verified
backup before modifying the named database. Never imports demonstration records.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from contextlib import closing

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'implementation'
sys.path.insert(0,str(BASE))
from agri.sqlite_db import SQLiteDatabase
from agri.source_mapping import SourceMappingService
from integrations.liangzihu import load_bundle
from ops.backup_sqlite import copy_database, output_path, inspect


def fingerprints(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as conn:
        result={}
        for table,order in [('entities','tenant_id,entity_key'),('ontology_packages','tenant_id,package_id,version'),
                            ('ontology_display','tenant_id,package_id,package_version')]:
            rows=conn.execute('SELECT * FROM '+table+' ORDER BY '+order).fetchall()
            result[table]={json.dumps(r[:3],ensure_ascii=False):hashlib.sha256(json.dumps(r,ensure_ascii=False,default=str).encode()).hexdigest() for r in rows}
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,required=True);p.add_argument('--tenant',required=True)
    p.add_argument('--source-id',required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    original=args.database.resolve(strict=True)
    if not original.is_relative_to((BASE/'data').resolve()):raise ValueError('Only explicit implementation/data SQLite databases are supported')
    before=fingerprints(original)
    payload=load_bundle(args.source_id)
    actor={'id':'local-definition-upgrade-v04','tenant_id':args.tenant,'roles':['admin']}
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'data_imported':False,'postgresql_verified':False,'source_id':args.source_id}
    with tempfile.TemporaryDirectory(prefix='lzhu-upgrade-') as folder:
        candidate=Path(folder)/'preflight.db'
        with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(candidate)) as destination:
            source.backup(destination)
        test_db=SQLiteDatabase('sqlite:///'+str(candidate))
        report['preflight_migrations']=test_db.migrate()
        preview=SourceMappingService(test_db).preview_source_bundle(args.tenant,actor,payload)
        assert fingerprints(candidate)==before, 'Preview modified existing records'
        report.update(preflight_passed=True,package_count=preview['package_count'],table_count=preview['table_count'])
    if args.apply:
        name='before-source-mapping-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.db'
        backup=copy_database(original,output_path(name))
        report['backup']={'path':backup['backup'],'sha256':backup['sha256'],'integrity_check':backup['integrity_check']}
        db=SQLiteDatabase('sqlite:///'+str(original))
        report['migrations']=db.migrate()
        service=SourceMappingService(db)
        result=service.mutate('install_source_bundle',args.tenant,actor,payload,'local-definition-v04:'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
        after=fingerprints(original)
        assert all(all(after[table].get(key)==value for key,value in rows.items()) for table,rows in before.items()), 'Existing record changed; review backup before proceeding'
        assert len(after['entities'])==len(before['entities']), 'Definition-only install created entities'
        report.update(applied=True,existing_rows_preserved=True,entity_count=len(after['entities']),package_count=len(after['ontology_packages']),installed_bundle_packages=result['package_count'])
        report['integrity']=inspect(original)['integrity_check']
    else:report['applied']=False
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()

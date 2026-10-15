"""Validate package payloads against v0.3 in an isolated temporary SQLite database.

No application server, configured DATABASE_URL, credential, or network is used.
SQLite behavior is not PostgreSQL or production acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
IMPLEMENTATION=ROOT/'implementation'
sys.path.insert(0,str(IMPLEMENTATION))


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def dependency_order(packages):
    by_key={}
    for package in packages:
        key=(package.get('package_id'),package.get('version'))
        if key in by_key: raise ValueError('重复本体包版本: '+repr(key))
        by_key[key]=package
    result=[];visiting=set();done=set()
    def visit(key):
        if key in done:return
        if key in visiting:raise ValueError('本体依赖成环: '+repr(key))
        if key not in by_key:raise ValueError('缺少精确版本依赖；请同时提供依赖包: '+repr(key))
        visiting.add(key)
        for dep in by_key[key].get('dependencies',[]):visit((dep.get('package_id'),dep.get('version')))
        visiting.remove(key);done.add(key);result.append(by_key[key])
    for key in by_key:visit(key)
    return result


def validate_packages(packages):
    from agri.ontology_core import OntologyService,validate_core
    from agri.sqlite_db import SQLiteDatabase
    from agri.service import DomainError
    if not isinstance(packages,list) or not packages:raise ValueError('需要至少一个本体包')
    for package in packages:validate_core('register_package',package)
    ordered=dependency_order(packages)
    # Registration permits future identity names. A self-contained workbook
    # instead requires explicit endpoints in its exact dependency closure.
    by_key={(p['package_id'],p['version']):p for p in ordered}
    def reachable_identities(package,seen=None):
        seen=set() if seen is None else seen
        key=(package['package_id'],package['version'])
        if key in seen:return set()
        seen.add(key)
        identities={t['identity_type'] for t in package['types']}
        for dep in package.get('dependencies',[]):
            identities.update(reachable_identities(by_key[(dep['package_id'],dep['version'])],seen))
        return identities
    for package in ordered:
        available=reachable_identities(package)|set(OntologyService.CORE_TYPES)|{'*'}
        for predicate in package.get('predicates',[]):
            unknown=(set(predicate['subject_types'])|set(predicate['object_types']))-available
            if unknown:raise ValueError(package['package_id']+': unknown_endpoint_identity '+','.join(sorted(unknown))+'；需启用对应类型和精确依赖')
    results=[]
    with tempfile.TemporaryDirectory(prefix='ontology-package-validation-') as temp:
        isolated=(Path(temp)/'validation.sqlite').resolve()
        if isolated.parent!=Path(temp).resolve():raise ValueError('临时验证路径不合法')
        db=SQLiteDatabase('sqlite:///'+str(isolated));migration=db.migrate();db.migrate()
        service=OntologyService(db)
        actor={'id':'offline-workbook-validator','roles':['admin']};tenant='offline-package-validation'
        for index,package in enumerate(ordered):
            try:
                result=service.mutate('register_package',tenant,actor,package,'offline-package-'+str(index))
            except DomainError as exc:
                raise ValueError(package['package_id']+'@'+package['version']+': '+exc.code+' '+exc.message) from exc
            results.append({'package_id':package['package_id'],'version':package['version'],
                'types':len(package['types']),'properties':len(package.get('properties',[])),
                'predicates':len(package.get('predicates',[])),'content_hash':result['content_hash']})
        counts=service.query('stats',tenant,actor)['counts']
        if any(counts.get(k,0) for k in ('entities','observations','assertions','relations','evidence')):
            raise ValueError('离线定义验证不得产生业务对象或观测')
    return {'status':'passed','schema':'current-v0.3','backend':'sqlite-development-isolated',
            'production_database_touched':False,'postgresql_verified':False,'network_used':False,
            'migration':migration['migration'],'packages':results,
            'definition_counts':{'packages':len(results),'types':sum(x['types'] for x in results),
                                 'properties':sum(x['properties'] for x in results),'predicates':sum(x['predicates'] for x in results)}}


def load_packages(path):
    path=Path(path)
    if path.is_dir():
        manifest=path/'manifest.json'
        if manifest.exists():
            meta=json.loads(manifest.read_text(encoding='utf-8'))
            packages=[]
            for row in meta['packages']:
                candidate=(path/row['file']).resolve()
                if candidate.parent!=path.resolve():raise ValueError('manifest文件路径越界')
                content=candidate.read_bytes()
                if hashlib.sha256(content).hexdigest()!=row['sha256']:raise ValueError('文件哈希不匹配: '+row['file'])
                packages.append(json.loads(content))
            return packages
        raise ValueError('目录必须含manifest.json')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data,list):return data
    if isinstance(data,dict) and 'packages' in data and 'package_id' not in data:return data['packages']
    return [data]


def main(argv=None):
    parser=argparse.ArgumentParser(description='只在临时SQLite中验证本体JSON，不导入现有数据库')
    parser.add_argument('packages',help='单包JSON、包数组JSON，或带manifest.json的导出目录')
    parser.add_argument('--report',type=Path,help='可选输出验证报告JSON')
    args=parser.parse_args(argv)
    try:
        report=validate_packages(load_packages(args.packages))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())

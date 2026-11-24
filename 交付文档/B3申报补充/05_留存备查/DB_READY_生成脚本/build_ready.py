"""Generate the repaired source-simulation edition and a strictly loaded database.

Never reads the previous baseline or anomaly answers. Existing L1/L2 files are read-only.
"""
import argparse,csv,json,hashlib,shutil,sys,copy
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
from decimal import Decimal
import business_source,environment_source,integration_source
from normalization import canonical_number,canonical_boolean,canonical_time
from quality_checks import structural_checks,observation_checks
from business_checks import run_checks

VERSION='DB-READY-1.0.0'
READS=set()
def install_guard(project,out):
    def guard(event,args):
        if event!='open' or not isinstance(args[0],(str,bytes,Path)):return
        try:p=Path(args[0]).resolve()
        except (ValueError,TypeError,OSError):return
        mode=args[1] if len(args)>1 else 'r'
        if not p.is_relative_to(project):return
        if isinstance(mode,str) and any(c in mode for c in 'wax+'):
            if not p.is_relative_to(out):raise PermissionError('Source revision writes only to db_ready')
        else:
            if p.is_relative_to(project/'output/reference'):raise PermissionError('Old baseline/answers cannot be source-repair inputs')
            READS.add(p.relative_to(project).as_posix())
    sys.addaudithook(guard)
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True,default=str)+'\n','utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fields(rows):return list(dict.fromkeys(k for r in rows for k in r if not k.startswith('_l2_')))
def write_csv(p,rows,cols=None):
    p.parent.mkdir(parents=True,exist_ok=True);cols=cols or fields(rows)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,cols,extrasaction='ignore',lineterminator='\n');w.writeheader()
        for r in rows:w.writerow({k:('true' if v else 'false') if isinstance(v,bool) else ('' if v is None else v) for k,v in r.items() if k in cols})
def cell(v):
    if v is None:return ''
    if isinstance(v,bool):return 'true' if v else 'false'
    if isinstance(v,(int,float,Decimal)):return canonical_number(str(v))
    return str(v)
def read_catalog(p,spec):
    out=[]
    for r in csv.DictReader(p.open(encoding='utf-8-sig',newline='')):
        n={}
        for k,v in r.items():
            if k.startswith('_l2_'):continue
            t=spec.get('columns',{}).get(k,{}).get('type','string');types=t if isinstance(t,list) else [t]
            n[k]=None if v=='' else (v.lower()=='true' if 'boolean' in types else (int(v) if 'integer' in types else (float(v) if 'number' in types else v)))
        out.append(n)
    return out
def canonicalize(t,schema):
    for name,rows in t.items():
        for r in rows:
            for k,v in list(r.items()):
                spec=schema.get('tables',{}).get(name,{}).get('columns',{}).get(k,{})
                if isinstance(v,str) and v and (spec.get('format')=='date-time' or (name,k)==('sources','retrieved_at')):
                    r[k]=v if len(v)==10 else canonical_time(v)
                if k=='quality_flag' and v=='baseline_valid':r[k]='source_generated_valid'
                if k in {'generation_run_id','rule_version'} and name not in {'attachments','document_versions','documents','media_annotations','attachment_links','spatial_layer_registry'}:r[k]=VERSION+'-20251031' if k=='generation_run_id' else VERSION
        cols=fields(rows)
        t[name]=[{col:r.get(col) for col in cols} for r in rows]
    return t
def definitions():
    return [dict(id=f'GRADE-{s}-{g}-V1',species_id=s,grade=g,lower_bound_g=500 if g=='A' else 1,upper_bound_g=None if g=='A' else 500,lower_inclusive=True,upper_inclusive=False,unit='g',version='1',basis='explicit_synthetic_weight_interval',upper_bound_status='unbounded' if g=='A' else 'finite') for s in ['SP01','SP02'] for g in ['A','B']]
def assert_check(checks,code,ok,detail=None):checks.append({'code':code,'passed':bool(ok),'detail':detail})
def validate(t,schema,root):
    annotated={name:[{k:cell(v) for k,v in r.items()}|{'_l2_row_key':name+':'+str(r['id'])} for r in rows] for name,rows in t.items()}
    si,sc,_=structural_checks(annotated,schema);oi,oc=observation_checks(annotated,set());bi,bc,_=run_checks(annotated,schema,{'blocked_fields':set()})
    errors=[i for i in si+oi+bi if i['action'] in {'review','quarantine'}]
    checks=[{'code':c['code'],'passed':not c['failed_count'] and not c['blocked_count'],'detail':{'checked':c['checked_count'],'failed':c['failed_count'],'blocked':c['blocked_count']}} for c in sc+oc+bc]
    orig=business_source.validate_business({k:t[k] for k in business_source.TABLES})
    checks.extend({'code':'SOURCE_'+c.get('check_id',c.get('name','check')),'passed':bool(c.get('passed',c.get('ok',False))),'detail':c} for c in orig)
    assert_check(checks,'NO_ERROR_TOKENS',not any(v in {'P99','source_unit_x2'} for rows in annotated.values() for r in rows for v in r.values()))
    assert_check(checks,'NO_UNRESOLVED_L2_ROWS',not any(k.startswith('_l2_') for rows in t.values() for r in rows for k in r))
    # Coverage is defined per occupied main group per calendar month, including partial months.
    expected=set()
    for r in t['pond_cohort_occupancy']:
        if r['role']!='main':continue
        a=datetime.fromisoformat(r['entered_at']);b=datetime.fromisoformat(r['left_at']);y,m=a.year,a.month
        while (y,m)<=(b.year,b.month):
            expected.add((r['pond_id'],r['cohort_id'],f'{y:04}-{m:02}'));m+=1
            if m==13:y,m=y+1,1
    got={(r['pond_id'],r['cohort_id'],r['sampled_at'][:7]) for r in t['growth_samples']}
    assert_check(checks,'MAIN_MONTHLY_SAMPLING_COMPLETE',expected<=got,{'expected':len(expected),'covered':len(expected&got),'missing':sorted(expected-got)})
    ind=defaultdict(list)
    for r in t['harvest_grade_individuals']:ind[r['harvest_grade_item_id']].append(r)
    grade_bad=[]
    for r in t['harvest_grade_items']:
        group=ind[r['id']];ws=[v['weight_g'] for v in group]
        if len(group)!=r['count'] or sum(ws)!=round(r['net_weight_kg']*1000) or not all((w>=500 if r['grade']=='A' else 1<=w<500) for w in ws):grade_bad.append(r['id'])
    assert_check(checks,'HARVEST_GRADE_INDIVIDUAL_EVIDENCE',not grade_bad,grade_bad)
    file_bad=[]
    for table,col in [('attachments','relative_path'),('spatial_layer_registry','relative_path'),('document_versions','relative_path'),('documents','full_text_path'),('sources','local_path')]:
        for r in t[table]:
            if r.get(col):
                p=root/r[col]
                if not p.exists() or (r.get('sha256') and sha(p)!=r['sha256']):file_bad.append([table,r['id'],r[col]])
    assert_check(checks,'ATTACHMENT_AND_SOURCE_FILES',not file_bad,file_bad)
    ctx_bad=[];idx={name:{r['id']:r for r in rows} for name,rows in t.items()}
    for link in t['attachment_links']:
        a=idx['attachments'][link['attachment_id']];b=idx[link['entity_table']][link['entity_id']]
        for key in ['pond_id','cohort_id']:
            if a.get(key) and b.get(key) and a[key]!=b[key]:ctx_bad.append([link['id'],key])
    assert_check(checks,'ATTACHMENT_ENTITY_CONTEXT',not ctx_bad,ctx_bad)
    return checks,errors

def generate(project,out):
    base=project/'output';schema=json.loads((base/'schemas/schema.json').read_text('utf-8-sig'))
    schema.update(schema_version=VERSION,encoding='UTF-8 BOM',csv_scope='csv',provenance='source_registry and scenario/revision.json; generated source revision')
    # Store source script and source catalog hashes, rather than treating earlier baseline rows as inputs.
    paths=[base/'public_sources/era5_2025.json',base/'public_sources/attachment/sample_manifest.json',base/'public_sources/weather_download.json',base/'scenario/assumptions.json',base/'schemas/schema.json',project/'数据审阅意见.md']
    catalogs=['attachments','attachment_links','media_annotations','documents','document_versions','spatial_layer_registry']
    paths.extend(base/'l2_cleaned/normalized'/f'{name}.csv' for name in catalogs)
    inputs=[{'path':p.relative_to(project).as_posix(),'sha256':sha(p)} for p in paths]
    for folder in ['assets','public_sources','scenario']:shutil.copytree(base/folder,out/folder,dirs_exist_ok=True)
    cfg={'seed':20251031,'year':2025,'mode':'full','generation_run_id':VERSION+'-20251031','weather_path':str(out/'public_sources/era5_2025.json')}
    t=business_source.generate(cfg);t.update(environment_source.generate(cfg,t));integration_source.ROOT=out;integration_source.integrate(t,cfg)
    for name in catalogs:t[name]=read_catalog(base/'l2_cleaned/normalized'/f'{name}.csv',schema['tables'][name])
    catalog_changes=[];idx={name:{r['id']:r for r in rows} for name,rows in t.items()}
    for link in t['attachment_links']:
        attachment=idx['attachments'][link['attachment_id']];target=idx[link['entity_table']][link['entity_id']]
        for key in ['pond_id','cohort_id']:
            if attachment.get(key) and target.get(key) and attachment[key]!=target[key]:
                catalog_changes.append({'table':'attachments','id':attachment['id'],'field':key,'before':attachment[key],'after':target[key],'reason':'通用合成格式样例在新主养采样对象中的上下文修订；非真实现场影像重标'})
                attachment[key]=target[key]
    write_csv(out/'reports/catalog_revisions.csv',catalog_changes,['table','id','field','before','after','reason'])
    t['grade_definitions']=definitions()
    # Keep documented file paths rooted inside this self-contained edition.
    for r in t['patrol_events']:
        r['dead_size_g']=round(r['dead_weight_kg']*1000/r['dead_count'],3) if r['dead_count'] else None
        r['dead_size_status']='derived_from_same_simulated_mortality_events' if r['dead_count'] else 'not_applicable_no_dead_fish'
    t['source_registry']=[dict(id=name,table=name,origin_kind='weather_reanalysis' if name=='weather_observations' else ('reused_format_asset_catalog' if name in catalogs else 'revised_rule_simulation'),generation_run_id=cfg['generation_run_id'],seed=cfg['seed'],rule_version=VERSION,timezone='Asia/Shanghai') for name in t]
    canonicalize(t,schema)
    # New tables and new FK columns are declared as part of the edition schema.
    schema['tables'].pop('record_provenance',None)
    for name,rows in t.items():
        entry=schema['tables'].setdefault(name,{'columns':{},'required':['id'],'primary_key':['id'],'foreign_keys':[]})
        entry.pop('path',None);entry.pop('row_count',None);entry['csv_path']='csv/'+name+'.csv'
        for col in fields(rows):
            if col in entry['columns']:continue
            vals=[r.get(col) for r in rows];non=[v for v in vals if v is not None]
            typ='boolean' if non and all(isinstance(v,bool) for v in non) else ('integer' if non and all(isinstance(v,int) and not isinstance(v,bool) for v in non) else ('number' if non and all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in non) else 'string'))
            entry['columns'][col]={'type':[typ,'null'] if len(non)<len(vals) else typ,'description':col,'unit':'g' if col.endswith('_g') else ''}
        for col,target in [('grade_definition_id','grade_definitions'),('grade_pass_definition_id','grade_definitions'),('occupancy_id','pond_cohort_occupancy'),('ledger_balance_id','fish_daily_balance'),('harvest_grade_item_id','harvest_grade_items')]:
            if col in entry['columns'] and not any(f['field']==col for f in entry['foreign_keys']):entry['foreign_keys'].append({'field':col,'references':{'table':target,'field':'id'},'nullable':True})
        if name=='grade_definitions':entry['foreign_keys'].append({'field':'species_id','references':{'table':'species','field':'id'},'nullable':False})
        if name=='harvest_grade_individuals':
            for col,target in [('harvest_id','harvests'),('pond_id','ponds'),('cohort_id','cohorts'),('species_id','species')]:entry['foreign_keys'].append({'field':col,'references':{'table':target,'field':'id'},'nullable':False})
    roles=json.loads((base/'l2_cleaned/scripts/roles.json').read_text('utf-8'));roles.pop('source_views/feeding_legacy',None)
    roles['harvest_grade_individuals']={'role':'business','description_zh':'模拟采收分级个体明细','additive':False,'measurement_policy_zh':'与出塘总表及规格汇总择一计量，不重复累计'}
    roles['grade_definitions']={'role':'master','description_zh':'物种体重规格定义','additive':False,'measurement_policy_zh':'定义维表，不累计'}
    dump(out/'schema/table_roles.json',roles)
    schema['table_roles']={name:roles[name]['role'] for name in t}
    for name,rows in t.items():write_csv(out/'csv'/f'{name}.csv',rows)
    return t,schema,inputs

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[3]);p.add_argument('--output-root',type=Path);a=p.parse_args();project=a.project_root.resolve();out=(a.output_root or project/'output/db_ready').resolve()
    if out.parent!=project/'output' or not out.name.startswith('db_ready'):raise SystemExit('Output must be a new output/db_ready* folder')
    out.mkdir(parents=True,exist_ok=True);install_guard(project,out);t,schema,inputs=generate(project,out);print(json.dumps({'stage':'source_revision_generated','tables':len(t),'rows':sum(map(len,t.values()))}),flush=True)
    assumptions=json.loads((out/'scenario/assumptions.json').read_text('utf-8'))
    assumptions['rule_version']=VERSION
    assumptions['anomalies']={'enabled':False,'ratio':0,'reason':'正式入库模拟修订版不执行错误注入'}
    assumptions['db_ready_revision']={'version':VERSION,'precedence':'本节优先于旧版同项假设','business':getattr(business_source,'REVISION_METADATA',{}),'environment':getattr(environment_source,'REVISION_METADATA',{})}
    dump(out/'scenario/assumptions.json',assumptions)
    dump(out/'scenario/config.json',{'seed':20251031,'year':2025,'mode':'full','rule_version':VERSION,'generation_run_id':VERSION+'-20251031','anomaly_ratio':0,'edition':'database_ready_synthetic_revision'})
    checks,errors=validate(t,schema,out)
    dump(out/'reports/data_checks.json',checks);write_csv(out/'reports/remaining_errors.csv',errors,['table','record_id','field','code','message','evidence'])
    bad=[r for r in checks if not r['passed']]
    dump(out/'schema/schema.json',schema)
    if bad or errors:dump(out/'reports/acceptance.json',{'passed':False,'failed_checks':bad,'errors':errors});raise SystemExit('Acceptance failed; see reports')
    from database_io import build_database
    db=build_database(out,t,schema)
    assert not db['errors'],db
    assert all(sha(project/r['path'])==r['sha256'] for r in inputs)
    again=business_source.generate({'seed':20251031,'year':2025,'mode':'full'})
    deterministic=all(again[k]==t[k] for k in ['harvest_grade_individuals','harvest_grade_items'])
    assert deterministic
    summary={'passed':True,'version':VERSION,'dataset_kind':'revised_synthetic_source_edition','tables':len(t),'rows':sum(map(len,t.values())),'row_counts':{k:len(v) for k,v in t.items()},'checks':len(checks),'failed_checks':[],'remaining_errors':0,'database':db,'source_input_hashes_unchanged':True,'forbidden_baseline_or_answers_used':False,'same_seed_grading_reproduced':deterministic,'seed':20251031,'data_entry_directory':'csv/'}
    dump(out/'reports/acceptance.json',summary);dump(out/'reports/source_inputs.json',inputs);dump(out/'reports/read_access.json',{'read_paths':sorted(READS),'old_baseline_and_answers_reads':0})
    dump(out/'scenario/revision.json',{'version':VERSION,'seed':20251031,'business':getattr(business_source,'REVISION_METADATA',{}),'environment':getattr(environment_source,'REVISION_METADATA',{}),'basis':'本版本修正模拟源并完整重建，不是已冻结L2盲清洗结果，不使用旧基准或答案回填','legitimate_nulls':'未施药、未确诊、低于检出限、无水、无死鱼等允许明确状态下的空值'})
    print(json.dumps({'stage':'ready','tables':len(t),'rows':summary['rows'],'checks':len(checks),'errors':0,'db':db.get('database_path')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()

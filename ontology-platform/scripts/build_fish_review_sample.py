"""Build an isolated, reproducible 10% relational/ontology/PostGIS design preview.

No governed platform facts, users, jobs or source journals are changed. Source
records remain synthetic/unverified. The preview is not formal adoption.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID, uuid5

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from sqlalchemy import (create_engine, MetaData, Table, Column, Text, Integer,
    BigInteger, Boolean, Numeric, Date, DateTime, JSON, insert, select, text, ForeignKeyConstraint)
from sqlalchemy.schema import CreateTable, AddConstraint
from lzo.ingestion.fish_package import load_package
from lzo.gis.fish_gis import build_gis_plan
from lzo.storage.migration import runtime_settings

SCHEMA='fish_review_10pct_v1'
NS=UUID('78a49e11-fced-4a7a-942e-765249845f8c')
OUT=ROOT/'docs/fish/review-sample'


def table_route(table):
    if table=='record_provenance':return 'reference'
    if table=='event_registry':return 'index'
    return 'telemetry' if table in {'water_observations','weather_observations','price_observations',
        'water_test_results','growth_individuals','fish_daily_balance'} else 'entity'


def review_target(settings,ownership,package):
    from sqlalchemy.engine import make_url
    import os
    url=make_url(settings.gis_migration_database_url)
    if (os.environ.get('APP_ENV')!='test' or ownership.get('contract')!='fish-l1-synthetic-runtime-v1'
            or Path(ownership['worktree']).resolve()!=ROOT.resolve() or url.host!='127.0.0.1'
            or url.port!=ownership['pg_port'] or url.database!='lzo_gis' or url.username!='lzo_gis_owner'):
        raise ValueError('Owned loopback fish GIS preview target required')


def stable(row):
    return hashlib.sha256(f'{row.table}:{row.row_number}:{row.pk}'.encode()).hexdigest()


def choose(audit, required):
    """Exact 10% seed, stratified by table/status, then explicit FK closure."""
    target=(audit.summary['physical_rows']+9)//10
    chosen={};reason={}
    def add(row,why):
        key=(row.table,row.row_number)
        if key not in chosen:chosen[key]=row;reason[key]=why;return True
        return False
    # All small master tables and the GIS feature owners fit inside the seed.
    index={(r.table,r.pk):r for r in audit.iter_rows() if r.status in ('accepted','needs_review')}
    for table,rows in audit.rows.items():
        if len(rows)<=50:
            for row in rows:add(row,'small_table_coverage')
        else:
            for status in sorted({r.status for r in rows}):
                add(min((r for r in rows if r.status==status),key=stable),'status_coverage')
    for item in required:
        add(index[item['table'],item['pk']],'gis_owner')
    # Approximately ten percent per table; final fill remains deterministic.
    for table,rows in sorted(audit.rows.items()):
        quota=(len(rows)+9)//10
        have=sum(t==table for t,n in chosen)
        for row in sorted(rows,key=stable):
            if have>=quota or len(chosen)>=target:break
            if add(row,'stratified_seed'):have+=1
    for row in sorted(audit.iter_rows(),key=stable):
        if len(chosen)>=target:break
        add(row,'seed_fill')
    if len(chosen)!=target:raise ValueError('Seed cannot meet exact ten percent size')
    seed_count=len(chosen)
    outgoing=defaultdict(list)
    for edge in audit.relations:outgoing[edge['table'],edge['row_number']].append(edge)
    pending=list(chosen)
    while pending:
        key=pending.pop()
        for edge in outgoing[key]:
            if edge['status']!='resolved':continue
            row=index.get((edge['target_table'],edge['target_pk']))
            if row is not None and add(row,'foreign_key_dependency'):pending.append((row.table,row.row_number))
    return chosen,reason,seed_count,outgoing


def sql_type(spec):
    value=spec.get('type','string')
    if isinstance(value,list):value=next((x for x in value if x!='null'),'string')
    if spec.get('format')=='date-time':return DateTime(timezone=True)
    if spec.get('format')=='date':return Date()
    return {'integer':BigInteger,'number':Numeric,'boolean':Boolean}.get(value,Text)()


def typed(value,spec):
    if value is None:return None
    if spec.get('format')=='date-time':return datetime.fromisoformat(value)
    if spec.get('format')=='date':return date.fromisoformat(value)
    kind=spec.get('type')
    if kind=='number' or isinstance(kind,list) and 'number' in kind:return Decimal(str(value))
    return value


def bulk(connection,table,values):
    for start in range(0,len(values),500):connection.execute(insert(table),values[start:start+500])


def main():
    base=ROOT/'.runtime/source-imports/wuchangfish-l1-2025-01/1eb0bab8f86f'
    audit=load_package(base/'extracted/output',base/'source-manifest.json')
    required=json.loads((ROOT/'docs/fish/gis-required-identities.json').read_text(encoding='utf-8'))['identities']
    chosen,reasons,seed,outgoing=choose(audit,required)
    package=audit.summary['package_sha256']
    settings=runtime_settings()
    ownership=json.loads((ROOT/'.runtime/fish-l1-acceptance/ownership.json').read_text())
    review_target(settings,ownership,package)
    engine=create_engine(settings.gis_migration_database_url)
    metadata=MetaData(schema=SCHEMA)
    raw=Table('raw_records',metadata,Column('table_name',Text,primary_key=True),Column('row_number',Integer,primary_key=True),
        Column('source_pk',Text),Column('payload',JSON),Column('normalized',JSON),Column('status',Text),
        Column('issues',JSON),Column('sample_reason',Text),Column('package_sha256',Text))
    nodes=Table('ontology_nodes',metadata,Column('node_id',Text,primary_key=True),Column('table_name',Text),
        Column('source_pk',Text),Column('class_iri',Text),Column('role',Text),Column('properties',JSON),
        Column('nature',Text),Column('source_row',Integer),Column('adoption_status',Text))
    edges=Table('ontology_relations',metadata,Column('edge_id',Integer,primary_key=True),Column('from_node',Text),
        Column('field_name',Text),Column('target_table',Text),Column('target_pk',Text),Column('to_node',Text),
        Column('resolution',Text),Column('source_row',Integer),Column('list_index',Integer))
    definitions=Table('field_dictionary',metadata,Column('table_name',Text,primary_key=True),Column('field_name',Text,primary_key=True),Column('definition',JSON))
    model_table=Table('ontology_model',metadata,Column('kind',Text,primary_key=True),Column('iri',Text,primary_key=True),Column('definition',JSON))
    gis=Table('gis_features',metadata,Column('asset_id',Text,primary_key=True),Column('owner_node',Text),
        Column('layer_id',Text),Column('layer_name',Text),Column('feature_id',Text),Column('geometry_json',JSON),Column('metadata',JSON))
    canonical={};valid=[r for r in chosen.values() if r.status in ('accepted','needs_review')]
    bytable=defaultdict(list)
    for row in valid:bytable[row.table].append(row)
    ids={(r.table,r.pk):str(uuid5(NS,package+':'+r.table+':'+r.pk)) for r in valid}
    constraint_count=0;omitted=[]
    for name,spec in audit.schema['tables'].items():
        canonical[name]=Table('data_'+name,metadata,*[Column(field,sql_type(desc),primary_key=field=='id')
            for field,desc in spec['columns'].items()],Column('_source_row',Integer),Column('_data_nature',Text))
    for name,spec in audit.schema['tables'].items():
        for number,fk in enumerate(spec.get('foreign_keys',[])):
            field,target=fk['field'],fk['references']['table']
            if field not in spec['columns']:continue
            missing=[r for r in bytable[name] if r.normalized.get(field) is not None and (target,str(r.normalized[field])) not in ids]
            if missing:
                omitted.append({'table':name,'field':field,'target':target,'rows':len(missing),'reason':'source_target_unusable; retained in relation ledger'})
                continue
            canonical[name].append_constraint(ForeignKeyConstraint([field],[f'{SCHEMA}.data_{target}.id'],
                name=f'fk_{name}_{number}',deferrable=True,initially='DEFERRED'))
            constraint_count+=1
    OUT.mkdir(parents=True,exist_ok=True)
    report={'contract':'fish-10pct-structure-review-v1','package_sha256':package,'data_nature':'synthetic; weather imported_unverified',
        'formal_adoption':False,'seed_rows':seed,'full_input_rows':audit.summary['physical_rows'],
        'dependency_rows':len(chosen)-seed,'total_sample_rows':len(chosen),'business_tables':len(canonical),
        'schema_fields':audit.summary['schema_field_count'],'reference_only_tables':['record_provenance'],
        'foreign_key_constraints':constraint_count,'unconstrained_source_anomalies':omitted,'tables':[]}
    plan=build_gis_plan(base/'extracted/output',audit,[{'table':t,'pk':pk,'resource_id':value} for (t,pk),value in ids.items()])
    relation_values=[]
    for row in valid:
        for edge in outgoing[row.table,row.row_number]:
            target=ids.get((edge.get('target_table'),edge.get('target_pk')))
            if edge['status']=='resolved' and target is None:raise ValueError('Resolved relationship escaped sample closure')
            relation_values.append({'edge_id':len(relation_values)+1,'from_node':ids[row.table,row.pk],
                'field_name':edge['field'],'target_table':edge.get('target_table'),'target_pk':edge.get('target_pk'),
                'to_node':target if edge['status']=='resolved' else None,'resolution':edge['status'],
                'source_row':row.row_number,'list_index':edge.get('list_index')})
    with engine.begin() as connection:
        exists=connection.execute(text('SELECT to_regnamespace(:schema)'),{'schema':SCHEMA}).scalar_one()
        if exists is not None:raise ValueError('Review schema already exists; refusing overwrite')
        connection.execute(text(f'CREATE SCHEMA {SCHEMA}'))
        metadata.create_all(connection)
        bulk(connection,raw,[{'table_name':r.table,'row_number':r.row_number,'source_pk':r.pk,'payload':r.payload,
            'normalized':r.normalized,'status':r.status,'issues':r.issues,'sample_reason':reasons[r.table,r.row_number],
            'package_sha256':package} for r in chosen.values()])
        for name,spec in audit.schema['tables'].items():
            bulk(connection,canonical[name],[{**{field:typed(r.normalized.get(field),desc) for field,desc in spec['columns'].items()},
                '_source_row':r.row_number,'_data_nature':r.nature} for r in bytable[name]])
            rows=[r for r in chosen.values() if r.table==name]
            report['tables'].append({'name':name,'raw_rows':len(rows),'canonical_rows':len(bytable[name]),
                'full_rows':len(audit.rows.get(name,[])),'statuses':dict(Counter(r.status for r in rows)),
                'role':table_route(name),'columns':spec['columns'],'examples':[r.normalized for r in bytable[name][:5]]})
        bulk(connection,nodes,[{'node_id':ids[r.table,r.pk],'table_name':r.table,'source_pk':r.pk,
            'class_iri':'urn:lzo:fish-l1:class:'+r.table if table_route(r.table)=='entity' else None,'role':table_route(r.table),'properties':r.normalized,
            'nature':r.nature,'source_row':r.row_number,'adoption_status':'design_preview_not_formally_adopted'} for r in valid])
        bulk(connection,edges,relation_values)
        bulk(connection,definitions,[{'table_name':name,'field_name':field,'definition':desc}
            for name,spec in audit.schema['tables'].items() for field,desc in spec['columns'].items()])
        model=json.loads((ROOT/'datasets/fish/ontology-model.json').read_text(encoding='utf-8'))
        bulk(connection,model_table,[{'kind':kind,'iri':item['iri'],'definition':item}
            for kind in ('classes','properties','relations') for item in model[kind]])
        bulk(connection,gis,[{'asset_id':f['asset_id'],'owner_node':ids[(f['entity']['table'],f['entity']['pk'])]
            if f['entity']['table'] else ids['spatial_layer_registry',f['layer_id']], 'layer_id':f['layer_id'],
            'layer_name':f['layer_name'],'feature_id':f['feature_id'],'geometry_json':f['geometry'],'metadata':f} for f in plan['features']])
        connection.execute(text(f'ALTER TABLE {SCHEMA}.gis_features ADD COLUMN geom geometry(Geometry,4326)'))
        connection.execute(text(f'UPDATE {SCHEMA}.gis_features SET geom=ST_SetSRID(ST_GeomFromGeoJSON(geometry_json::text),4326)'))
        connection.execute(text(f'CREATE INDEX gis_review_geometry ON {SCHEMA}.gis_features USING gist(geom)'))
        connection.execute(text(f'ALTER TABLE {SCHEMA}.ontology_relations ADD FOREIGN KEY(from_node) REFERENCES {SCHEMA}.ontology_nodes(node_id), ADD FOREIGN KEY(to_node) REFERENCES {SCHEMA}.ontology_nodes(node_id)'))
        connection.execute(text(f'ALTER TABLE {SCHEMA}.gis_features ADD FOREIGN KEY(owner_node) REFERENCES {SCHEMA}.ontology_nodes(node_id)'))
        connection.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        report['checks']={'postgresql':'passed','deferred_foreign_keys':'passed','resolved_edges_without_target':0,
            'invalid_gis_geometries':connection.execute(text(f'SELECT count(*) FROM {SCHEMA}.gis_features WHERE NOT ST_IsValid(geom)')).scalar_one(),
            'raw_readback_count':connection.execute(select(text('count(*)')).select_from(raw)).scalar_one(),
            'ontology_nodes':len(valid),'ontology_relations':len(relation_values),'gis_features':len(plan['features'])}
        report['ponds']=[dict(row) for row in connection.execute(text(f'''SELECT n.source_pk, f.feature_id,
            f.metadata->'measurements' AS measurements,ST_Area(geom::geography) AS derived_area_m2,
            ST_Perimeter(geom::geography) AS derived_perimeter_m,ST_AsGeoJSON(geom)::json AS geometry
            FROM {SCHEMA}.gis_features f JOIN {SCHEMA}.ontology_nodes n ON f.owner_node=n.node_id
            WHERE f.layer_name='ponds' ORDER BY n.source_pk''')).mappings()]
        report['checked_at']=datetime.now(timezone.utc).isoformat()
    engine.dispose()
    ddl=['-- PostgreSQL + PostGIS isolated review schema; create in an empty schema.',f'CREATE SCHEMA {SCHEMA};']
    ddl.extend(str(CreateTable(t,include_foreign_key_constraints=[]).compile(dialect=engine.dialect))+';' for t in metadata.tables.values())
    ddl.extend(str(AddConstraint(fk).compile(dialect=engine.dialect))+';' for t in metadata.tables.values() for fk in t.foreign_key_constraints)
    ddl.extend([f'ALTER TABLE {SCHEMA}.gis_features ADD COLUMN geom geometry(Geometry,4326);',
        f'CREATE INDEX gis_review_geometry ON {SCHEMA}.gis_features USING gist(geom);',
        f'ALTER TABLE {SCHEMA}.ontology_relations ADD FOREIGN KEY(from_node) REFERENCES {SCHEMA}.ontology_nodes(node_id), ADD FOREIGN KEY(to_node) REFERENCES {SCHEMA}.ontology_nodes(node_id);',
        f'ALTER TABLE {SCHEMA}.gis_features ADD FOREIGN KEY(owner_node) REFERENCES {SCHEMA}.ontology_nodes(node_id);'])
    (OUT/'schema.sql').write_text('\n'.join(line.rstrip() for line in '\n'.join(ddl).splitlines())+'\n',encoding='utf-8')
    (OUT/'readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    render(report)
    print(json.dumps({k:report[k] for k in ('seed_rows','dependency_rows','total_sample_rows','foreign_key_constraints','checks')},ensure_ascii=False))


def render(report):
    template=(ROOT/'scripts/fish_review_template.html').read_text(encoding='utf-8')
    payload=json.dumps(report,ensure_ascii=False,default=str).replace('<','\\u003c')
    (OUT/'index.html').write_text(template.replace('__REVIEW_DATA__',payload),encoding='utf-8')


if __name__=='__main__':main()

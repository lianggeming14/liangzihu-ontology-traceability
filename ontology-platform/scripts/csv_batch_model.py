"""Lossless CSV reception, explicit typed cells and batch-scoped relationships."""
from collections import Counter,defaultdict
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID,uuid5

IDENTITY=UUID('78a49e11-fced-4a7a-942e-765249845f8c')
NUMERIC=re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')


def infer_definition(field,values):
    values=[value for value in values if value.strip()]
    result={'type':'string','description':field,'schema_basis':'observed_csv_values','unit':None}
    if (not values or field in {'id','version','seed','generation_run_id','rule_version','individual_number'}
            or field.endswith(('_id','_ids','_code','_number','_version'))):return result
    if all(value.strip().lower() in {'true','false'} for value in values):
        result['type']='boolean';return result
    if field.endswith(('_at','_on','_date')):
        definition={**result,'format':'date-time' if field.endswith('_at') else 'date'}
        try:
            for value in values:normalize_cell(value,definition)
        except ValueError:pass
        else:return definition
    if all(NUMERIC.fullmatch(value.strip()) and Decimal(value.strip()).is_finite() for value in values):
        result['type']='number'
    return result


def normalize_cell(value,definition):
    if not isinstance(value,str):raise ValueError('Source CSV cells must remain strings')
    if not value.strip():return None
    kind=definition.get('type','string')
    if isinstance(kind,list):kind=next((x for x in kind if x!='null'),'string')
    if definition.get('format')=='date-time':
        try:parsed=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
        except ValueError:raise ValueError('Invalid date-time') from None
        if parsed.tzinfo is None:raise ValueError('Date-time has no explicit offset')
        return value.strip()
    if definition.get('format')=='date':
        try:date.fromisoformat(value.strip())
        except ValueError:raise ValueError('Invalid date') from None
        return value.strip()
    if kind in {'number','integer'}:
        try:number=Decimal(value.strip())
        except InvalidOperation:raise ValueError('Invalid numeric') from None
        if not number.is_finite():raise ValueError('Non-finite numeric')
        if kind=='integer':
            if number!=number.to_integral_value():raise ValueError('Non-integral count')
            return int(number)
        return str(number)
    if kind=='boolean':
        if value.strip().lower() not in {'true','false'}:raise ValueError('Invalid boolean')
        return value.strip().lower()=='true'
    return value


def read_tables(directory,manifest):
    directory=Path(directory).resolve()
    tables,metadata={},{ }
    for item in manifest['members']:
        if item.get('member_role')!='csv' or item.get('is_csv') is not True:continue
        path=(directory/item['path']).resolve()
        if not path.is_relative_to(directory):raise ValueError('CSV path escapes extraction')
        payload=path.read_bytes()
        if len(payload)!=item['bytes'] or hashlib.sha256(payload).hexdigest()!=item['sha256']:
            raise ValueError('Extracted CSV differs from verified manifest')
        table=path.stem
        if not re.fullmatch(r'[a-z][a-z0-9_]*',table) or table in tables:raise ValueError('Invalid or repeated logical table')
        with path.open(encoding=item['encoding'],newline='') as stream:
            reader=csv.reader(stream,strict=True);header=next(reader)
            if header!=item['header'] or len(header)!=len(set(header)):raise ValueError('CSV header changed')
            rows=[];locations=[]
            for values in reader:
                if not values:continue
                if len(values)!=len(header):raise ValueError('CSV column count differs')
                rows.append(dict(zip(header,values)));locations.append(reader.line_num)
        if len(rows)!=item['row_count']:raise ValueError('CSV row count changed')
        tables[table]=rows;metadata[table]={**item,'line_ends':locations}
    if len(tables)!=manifest['csv_file_count']:raise ValueError('Not every business CSV was received')
    return tables,metadata


def data_nature(table,row,registry):
    origin=registry.get(table,'')
    if row.get('is_synthetic','').strip().lower()=='true' or row.get('is_fictional','').strip().lower()=='true':return 'synthetic'
    if origin=='revised_rule_simulation' or 'fictional' in row.get('source_system','') or row.get('identity_status')=='fictional':return 'synthetic'
    return 'imported_unverified'


def build_snapshot(tables,definitions,rules,package_sha256,*,metadata=None):
    if not re.fullmatch(r'[0-9a-f]{64}',package_sha256):raise ValueError('Invalid source package hash')
    metadata=metadata or {}
    schema={'tables':{}}
    shared=defaultdict(list)
    for spec in definitions.get('tables',{}).values():
        for field,definition in spec['columns'].items():shared[field].append(definition)
    for table,rows in sorted(tables.items()):
        fields=metadata.get(table,{}).get('header') or (list(rows[0]) if rows else list(definitions.get('tables',{}).get(table,{}).get('columns',{})))
        if 'id' not in fields:raise ValueError('Every current CSV table must declare its stable id')
        columns={}
        for field in fields:
            if not re.fullmatch(r'[a-z][a-z0-9_]*',field):raise ValueError('Invalid source field name')
            known=definitions.get('tables',{}).get(table,{}).get('columns',{}).get(field)
            if known is None and field in shared:
                kinds={(str(d.get('type','string')),d.get('format'),d.get('unit')) for d in shared[field]}
                if len(kinds)==1:known=shared[field][0]
            definition=copy.deepcopy(known) if known is not None else infer_definition(field,[r.get(field,'') for r in rows])
            definition['schema_basis']='prior_field_dictionary' if known is not None else 'observed_csv_values'
            columns[field]=definition
        schema['tables'][table]={'columns':columns,'primary_key':['id'],'path':metadata.get(table,{}).get('path',table+'.csv')}
    registry={row.get('table',row['id']):row.get('origin_kind','') for row in tables.get('source_registry',[])}
    raw,nodes,index=[],[],{}
    duplicate=conflicting=quarantined=0
    issues_total=0
    by_table={}
    for table,rows in sorted(tables.items()):
        groups=defaultdict(list)
        for position,payload in enumerate(rows,1):groups[payload.get('id','')].append((position,payload))
        counts=Counter()
        for key,group in groups.items():
            conflict=len({json.dumps(payload,sort_keys=True,ensure_ascii=False) for _,payload in group})>1
            for occurrence,(position,payload) in enumerate(group):
                if set(payload)!=set(schema['tables'][table]['columns']) or any(not isinstance(x,str) for x in payload.values()):
                    raise ValueError('CSV row fields or cell types differ from its declared header')
                properties={};issues=[]
                for field,definition in schema['tables'][table]['columns'].items():
                    try:properties[field]=normalize_cell(payload[field],definition)
                    except ValueError as error:
                        properties[field]=None;issues.append({'field':field,'code':'invalid_typed_value','reason':str(error)})
                status='needs_review' if issues else 'accepted'
                if not key.strip():status='quarantined';quarantined+=1
                elif conflict:status='conflicting_duplicate';conflicting+=1
                elif occurrence:status='duplicate';duplicate+=1
                item={'table_name':table,'row_number':position,'source_pk':key,'payload':dict(payload),
                    'status':status,'issues':issues,'sample_reason':'full_csv_batch'}
                raw.append(item);counts[status]+=1;issues_total+=len(issues)
                if status not in {'accepted','needs_review'}:continue
                identifier=str(uuid5(IDENTITY,package_sha256+':'+table+':'+key))
                record_role='reference' if table in {'grade_definitions','source_registry'} else ('telemetry' if table in {'water_observations','weather_observations','price_observations','water_test_results','growth_individuals','fish_daily_balance','harvest_grade_individuals'} else 'index' if table=='event_registry' else 'entity')
                node={'node_id':identifier,'table_name':table,'source_pk':key,'role':record_role,
                    'source_row':position,'properties':properties,'nature':data_nature(table,payload,registry)}
                nodes.append(node);index[table,key]=node
        by_table[table]={'rows':len(rows),'fields':len(schema['tables'][table]['columns']),'statuses':dict(counts)}
    raw.sort(key=lambda item:(item['table_name'],item['row_number']))
    nodes.sort(key=lambda item:(item['table_name'],item['source_pk']))
    relations=[];seen=set()
    grouped=defaultdict(list)
    for rule in rules:
        if rule['kind'] in {'scalar','delimited','polymorphic'}:grouped[rule['source_table']].append(rule)
    for node in nodes:
        table,key=node['table_name'],node['source_pk'];payload=tables[table][node['source_row']-1]
        for rule in grouped[table]:
            value=payload.get(rule['field'],'')
            if not value.strip():continue
            target=rule.get('target_table')
            if rule['kind']=='polymorphic':target=rule.get('cases',{}).get(payload.get(rule['discriminator_field'])) or 'external_'+payload.get(rule['discriminator_field'],'unknown')
            values=[v.strip() for v in value.split(rule.get('separator',';'))] if rule['kind']=='delimited' else [value]
            for offset,target_pk in enumerate(values):
                if not target_pk:continue
                edge_key=(node['node_id'],rule['field'],target,target_pk,offset)
                if edge_key in seen:continue
                seen.add(edge_key);bound=index.get((target,target_pk))
                relations.append({'edge_id':len(relations)+1,'from_node':node['node_id'],'field_name':rule['field'],
                    'target_table':target,'target_pk':target_pk,'to_node':bound['node_id'] if bound else None,
                    'resolution':'resolved' if bound else 'unresolved','source_row':node['source_row'],'list_index':offset,
                    'evidence':rule.get('evidence','explicit CSV relation rule')})
    snapshot={'package_sha256':package_sha256,'schema':schema,'raw':raw,'nodes':nodes,'relations':relations,
        'source_schema':'csv_batch_'+package_sha256[:12],'dataset_label':'CSV DB-ready full batch 2026-11-09',
        'dataset_nature':'synthetic revised rule simulation; weather reanalysis; reused asset catalog'}
    report={'contract':'csv-batch-model/1','raw_rows':len(raw),'instances':len(nodes),'relations':len(relations),
        'resolved_relations':sum(e['resolution']=='resolved' for e in relations),'duplicate_rows':duplicate,
        'conflicting_rows':conflicting,'quarantined_rows':quarantined,'invalid_typed_cells':issues_total,
        'source_tables':len(schema['tables']),'schema_fields':sum(len(s['columns']) for s in schema['tables'].values()),
        'tables':by_table,'data_nature_counts':dict(Counter(n['nature'] for n in nodes)),
        'original_cells_preserved':True,'formal_adoption':False,'raw_payload_public':False}
    return snapshot,report

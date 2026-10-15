"""Build worksheet JSON + v0.3 definitions offline. Does not author XLSX or touch live databases."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from workbook_to_packages import SHEETS,rows_to_packages,write_output

VERSION='0.1.0'
LABELS=dict(pair.split('=',1) for pair in (
'enabled=是否启用导出|package_id=领域包标识|version=精确版本|namespace=命名空间|label=中文显示名称|description=概念边界与说明|'
'type_id=语义类标识|identity_type=独立身份类型|property_id=属性标识|applies_to=适用语义类（JSON数组）|value_type=目标值类型|unit=显式单位|'
'enum_values=枚举值（JSON数组）|usage=用途|required=本库必填|cardinality=单值或多值|minimum=最小值|maximum=最大值|'
'predicate_id=链接类型标识|subject_types=起点身份类型（JSON数组）|object_types=终点身份类型（JSON数组）|'
'subject_semantic_types=起点本包语义类（JSON数组）|object_semantic_types=终点本包语义类（JSON数组）|dimension=检索维度建议|'
'irreflexive=禁止自连|acyclic=禁止成环|depends_on_package_id=依赖包标识|depends_on_version=依赖精确版本|handling=映射处理策略|'
'source_table=源表|source_column=源列|source_sql_type=源SQL类型|source_path=源码路径|source_line=源码起始行|source_url=固定提交源码链接|notes=处理说明|'
'source_nullable=源SQL可空|source_primary_key=源主键成员|source_unique=源单列唯一|source_default=源默认表达式（不执行）|'
'source_checks=源CHECK表达式（JSON数组）|source_enum_values=源直接枚举（JSON数组）|target_table=终点源表|'
'source_columns=起点外键列（JSON数组）|target_columns=终点键列（JSON数组）|source_constraint=源约束名称|'
'source_cardinality=SQL外键基数事实|source_optional=SQL允许缺少引用|source_on_delete=源删除行为|source_on_update=源更新行为|'
'dimension_basis=维度标签依据|domain=领域编码|classification=来源分类|boundary=概念边界|column_count=字段数|'
'foreign_key_count=外键数|primary_key=源主键列（JSON数组）|kind=种类|definition=源定义（不执行）|name_inferred=约束名是否推定|'
'expression=表达式（不执行）|row_kind=目录项类别|reason=待处理原因|action=接入前处理步骤|sha256=源文件SHA256|bytes=字节数|'
'statements=SQL语句数|ddl_count=DDL条数|unparsed_count=未解析DDL数|status=解析状态|operation=DDL操作|object=目标对象|'
'sql=完整DDL（不执行）|parts=子操作（JSON数组）|source_commit=源提交|source_type_label=起点类型中文名|target_type_label=终点类型中文名'
).split('|'))
PROVENANCE=['source_path','source_line','source_url']
def dump(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def source_fields(s):return {'source_path':s.get('path',''),'source_line':s.get('line',''),'source_url':s.get('url','')}
def class_id(t):return 'lzhu:'+t['name']
def property_id(t,c):return 'lzhu:'+t['name']+'.'+c['name']
def sheet(name,keys,rows):
    return {'name':name,'columns':[{'key':k,'label':LABELS.get(k,k),'width':42 if k in {'description','notes','boundary','action','definition','sql','source_url'} else 24} for k in keys],'rows':rows}
def sensitive_field(name):
    # Business quality-certificate references are not authentication credentials.
    if name in {'credential_id','credential_ids'}:return False
    return bool(re.search(r'(^|_)(password|secret|credential|token|otp|totp|mfa|passkey|private_key|auth_version|recovery_code)(_|$)',name))
def property_mapping(c,table_name=None):
    sql=c['sql_type'].lower().strip();enum=c.get('enum_values',[]);notes=[]
    def mapped(handling,value='',cardinality='single',notes=''):
        return {'handling':handling,'value_type':value,'cardinality':cardinality,'notes':notes}
    if table_name=='users' and c['name'] in {'enabled','wecom_identity_evidence'}:
        return mapped('deferred_identity_policy',notes='仅为来源账户状态或身份核验资料；不映射本库赋权。接入前须明确来源身份与本库授权的隔离规则。')
    if table_name=='flight_files' and c['name']=='parent_external_ids':
        return mapped('deferred_array_identity',cardinality='many',notes='外部父记录标识数组，需先确认来源系统、目标类型及外部身份映射，再构造数据血缘；不作为普通业务值，也不声称已绑定父关系。')
    if sensitive_field(c['name']):return mapped('deferred_credentials',notes='认证凭证或认证状态保留在原系统安全边界。')
    if re.search(r'\bjsonb?\b',sql):return mapped('deferred_json',notes='JSON须定义字段路径、结构版本和对象/属性映射；不能整体冒充普通文本属性。')
    if re.search(r'\b(geometry|geography|point|polygon|linestring)\b',sql):return mapped('deferred_geometry',notes='保留坐标参考系，映射本库空间字段或空间对象，不转成普通字符串。')
    if re.search(r'\b(vector|halfvec|sparsevec)\b',sql):return mapped('deferred_vector',notes='向量需外部索引/模型接口及版本，不作为普通标量。')
    if sql in {'bytea','xml','hstore','record'}:return mapped('deferred_binary',notes='二进制或复合载荷转证据原件引用及摘要，不默默强转。')
    if '[]' in sql:
        if sql=='text[]':return mapped('array_scalar','string','many','文本数组逐元素映射；本库数组长度1至100，元素空白/业务含义由接入映射复核。SQL空数组映射为属性缺省。')
        return mapped('deferred_array_identity',cardinality='many',notes='标识数组须确认目标类型、身份映射和链接语义后拆为关系；不能猜测外键。')
    if enum and (sql=='text' or re.match(r'^(var)?char',sql)):
        return mapped('enum','enum',notes='枚举来自单列直接CHECK IN；复杂条件另列在约束目录，未自动移植。')
    if re.match(r'^(smallint|integer|bigint|int[248]?|smallserial|serial|bigserial)\b',sql):value='integer'
    elif re.match(r'^(numeric|decimal|real|double precision|float[48]?)\b',sql):
        value='decimal';notes.append('精确小数接入用十进制字符串，不先转浮点再声称保持精度。')
    elif sql in {'bool','boolean'}:value='boolean'
    elif sql.startswith('timestamp'):
        value='datetime';notes.append('接入须含明确时区；无时区值不能默认为UTC。')
    elif sql in {'text','uuid','date','time'} or re.match(r'^(var)?char\s*\(',sql):
        value='string'
        if sql=='date':notes.append('日期字符串YYYY-MM-DD；不伪造时区/零点，格式由接入映射显式校验。')
        elif sql=='uuid':notes.append('源UUID只作为来源标识，本库主键独立生成，通过外部身份映射关联。')
        elif sql=='time':notes.append('仅时刻字符串；补业务日期/时区后才能形成事件时间。')
    else:return mapped('deferred_unknown_type',notes='SQL类型未明确定义目标值域，须人工建模后启用。')
    return mapped('identity' if c.get('primary_key') else 'scalar',value,notes=' '.join(notes))
def dimension_for(f):
    text=' '.join(f['columns'])+' '+f['referenced_table']
    for pattern,dim,note in [
        ('evidence|artifact|image|source|snapshot|observation|provenance','provenance','证据/来源列名推导；不等同于因果或可信断言。'),
        ('field|plot|parcel|zone|farm|location|spatial|gis','spatial','空间/归属对象名推导；FK不证明空间包含。'),
        ('user|owner|operator|worker|expert|reviewer|actor|creator|assignee|member','participation','人员角色列名推导；角色由具体列定义。'),
        ('parent|part|component|batch|lot','composition','层级/批次列名推导；不自动施加无环、包含或谱系约束。'),
        ('event|task|order|workflow|step|run|job|request','workflow','流程对象名推导；不据此推导已执行或已完成。')]:
        if re.search(pattern,text):return dim,note
    return 'association','显式外键关联；未自动推定业务因果。'

def build_workbook_data(catalog,labels):
    if not catalog['coverage']['all_structural_ddl_parsed'] or not catalog['coverage']['all_references_resolved']:
        raise ValueError('源结构审计未通过，不生成可导入本体')
    tables=catalog['tables'];by_name={t['name']:t for t in tables};meta=labels['tables'];domains=labels['domains']
    missing=sorted(set(by_name)-set(meta))
    if missing:raise ValueError('领域分类缺失: '+','.join(missing))
    if any(not isinstance(meta[t['name']].get('default_import'),bool) for t in tables):raise ValueError('default_import必须是原生布尔值')
    rows={kind:[] for kind in ['packages','types','properties','predicates','dependencies']}
    extras={name:[] for name in ['源表清单','约束枚举','待映射项','源码覆盖','DDL审计']}
    enabled_domains={meta[t['name']]['domain'] for t in tables if meta[t['name']]['default_import']}
    fields=labels.get('field_labels',{})
    for domain in sorted({meta[t['name']]['domain'] for t in tables}):
        d=domains[domain]
        rows['packages'].append({'enabled':domain in enabled_domains,'package_id':'lzhu.'+domain,'version':VERSION,'namespace':'urn:lzhu:'+domain+':',
            'label':d['label'],'description':d['description']+' 固定源提交 '+catalog['source']['commit']+'。此包定义来源系统记录类；不是已经完成农业业务概念等价对齐的目标本体。',
            'source_commit':catalog['source']['commit'],'notes':'结构来自公开仓库固定提交，不含生产实例。'})
    for t in tables:
        name=t['name'];m=meta[name];active=m['default_import'];package='lzhu.'+m['domain'];base={'package_id':package,'version':VERSION};tid=class_id(t)
        rows['types'].append({**base,'enabled':active,'type_id':tid,'identity_type':tid,'label':m['label'],
            'description':m['boundary']+' 来源表 '+name+'；来源记录具有独立身份，源主键通过外部身份映射关联本库主键。',
            'source_table':name,'classification':m['classification'],'domain':m['domain'],**source_fields(t['source']),
            'notes':'默认导入' if active else '技术/安全结构仅编目；明确业务用途后启用领域包、类型及必要属性。'})
        extras['源表清单'].append({'source_table':name,'label':m['label'],'domain':m['domain'],'classification':m['classification'],
            'enabled':active,'type_id':tid,'identity_type':tid,'package_id':package,'boundary':m['boundary'],'column_count':len(t['columns']),
            'foreign_key_count':len(t['foreign_keys']),'primary_key':dump(t['primary_key']),**source_fields(t['source'])})
        fkcols={c for f in t['foreign_keys'] for c in f['columns']}
        for c in t['columns']:
            mapping=property_mapping(c,name);handling=mapping['handling'];reason=mapping['notes'];enabled=active and not handling.startswith('deferred')
            if c['name'] in fkcols:
                enabled=False
                if not handling.startswith('deferred'):
                    handling='deferred_foreign_key';reason='显式外键默认通过链接和外部身份映射接入，避免标识字符串与关系形成两份事实。 '+reason
            if not active:enabled=False;reason='来源表默认仅编目，未启用导入。 '+reason
            label=fields.get(c['name'],c['name'])
            row={**base,'enabled':enabled,'property_id':property_id(t,c),'label':m['label']+' · '+label,
                'description':'来源记录属性 '+name+'.'+c['name']+'。'+reason,'applies_to':dump([tid]),'value_type':mapping['value_type'],
                'unit':'','enum_values':dump(c.get('enum_values',[])) if mapping['value_type']=='enum' else '',
                'usage':'attribute','required':False,'cardinality':mapping['cardinality'],'minimum':None,'maximum':None,
                'handling':handling,'source_table':name,'source_column':c['name'],'source_sql_type':c['sql_type'],
                'source_nullable':c['nullable'],'source_primary_key':c['primary_key'],'source_unique':c['unique'],'source_default':c.get('default') or '',
                'source_checks':dump([x['expression'] for x in c.get('checks',[])]),'source_enum_values':dump(c.get('enum_values',[])),**source_fields(c['source']),
                'notes':reason+' 本库required固定FALSE；SQL约束只留作来源事实，未自动执行。'}
            rows['properties'].append(row)
            if not enabled or mapping['cardinality']=='many' or c['sql_type'].lower() in {'date','time'} or label==c['name']:
                extras['待映射项'].append({'row_kind':'property','package_id':package,'source_table':name,'source_column':c['name'],'property_id':row['property_id'],
                    'enabled':enabled,'handling':handling,'source_sql_type':c['sql_type'],'reason':reason or '中文标签待业务确认。',
                    'action':'完成明确映射前保持停用。' if not enabled else '导出前复核语义、多值规则和标签。',**source_fields(c['source'])})
        for c in t['constraints']:
            enums=[]
            if c['kind']=='check':enums=[{'column':col['name'],'values':col['enum_values']} for col in t['columns'] if col.get('enum_values') and col.get('enum_source')==c.get('source')]
            extras['约束枚举'].append({'row_kind':'constraint','source_table':name,'source_constraint':c['name'],'kind':c['kind'],'source_columns':dump(c.get('columns',[])),
                'definition':c.get('definition',''),'expression':c.get('expression',''),'source_enum_values':dump(enums),'target_table':c.get('referenced_table',''),
                'target_columns':dump(c.get('referenced_columns',[])),'name_inferred':c.get('name_inferred',False),**source_fields(c['source']),
                'notes':'源SQL约束仅供映射依据，不自动在本库执行。'+(' 名称按PostgreSQL规则推定，非实库核验。' if c.get('name_inferred') else '')})
        for idx in t.get('indexes',[]):
            extras['约束枚举'].append({'row_kind':'index','source_table':name,'source_constraint':idx['name'],'kind':'unique_index' if idx['unique'] else 'index',
                'source_columns':dump(idx['columns']),'definition':idx['sql'],'expression':idx.get('where') or '','source_enum_values':'[]','target_table':'',
                'target_columns':'[]','name_inferred':False,**source_fields(idx['source']),'notes':'索引独立标记；部分唯一索引不等价于全表单列唯一。'})
    foreign_keys=[(t,f) for t in tables for f in t['foreign_keys']]
    for offset in range(0,len(foreign_keys),500):
        chunk=foreign_keys[offset:offset+500];part=offset//500+1;package='lzhu.links'+str(part)
        active=any(meta[t['name']]['default_import'] and meta[f['referenced_table'].split('.')[-1]]['default_import'] for t,f in chunk)
        rows['packages'].append({'enabled':active,'package_id':package,'version':VERSION,'namespace':'urn:lzhu:links'+str(part)+':',
            'label':'来源关系桥接包 '+str(part),'description':'固定源提交 '+catalog['source']['commit']+'。显式SQL外键的跨包链接；端点使用独立身份类型，方向是引用方到被引用方。维度只是检索建议，不推定因果、无环或空间包含。',
            'source_commit':catalog['source']['commit'],'notes':'每包最多500条链接；安全/技术端点默认停用。'})
        rows['types'].append({'enabled':active,'package_id':package,'version':VERSION,'type_id':'lzhu:IntegrationRelation'+str(part),
            'identity_type':'lzhu:IntegrationRelation'+str(part),'label':'关系登记辅助类型 '+str(part),
            'description':'满足每个本体包至少一个类型的登记约束；不是来源SQL表，不生成实例；真实链接使用来源记录身份类型。',
            'source_table':'','classification':'integration_helper','domain':'links','source_path':'','source_line':'','source_url':'','notes':'工具新增的登记辅助类型，非SQL提取。'})
        for domain in sorted(enabled_domains):
            rows['dependencies'].append({'enabled':active,'package_id':package,'version':VERSION,'depends_on_package_id':'lzhu.'+domain,
                'depends_on_version':VERSION,'notes':'先登记启用的来源记录类型，再登记跨包链接。'})
        for t,f in chunk:
            target=by_name[f['referenced_table'].split('.')[-1]];sm=meta[t['name']];tm=meta[target['name']]
            cols=f['columns'];colmap={c['name']:c for c in t['columns']};enabled=sm['default_import'] and tm['default_import']
            unique=any(c['kind'] in {'primary_key','unique'} and set(c['columns'])==set(cols) for c in t['constraints'])
            optional=any(colmap[c]['nullable'] for c in cols);dim,basis=dimension_for(f)
            rows['predicates'].append({'enabled':enabled,'package_id':package,'version':VERSION,'predicate_id':'lzhu:fk:'+t['name']+':'+f['name'],
                'label':sm['label']+' → '+tm['label']+'（'+','.join(cols)+'）',
                'description':'源显式外键 '+t['name']+'('+','.join(cols)+') → '+target['name']+'('+','.join(f['referenced_columns'])+')。'+basis,
                'subject_types':dump([class_id(t)]),'object_types':dump([class_id(target)]),'subject_semantic_types':'','object_semantic_types':'',
                'dimension':dim,'irreflexive':False,'acyclic':False,'source_table':t['name'],'source_type_label':sm['label'],'source_columns':dump(cols),
                'target_table':target['name'],'target_type_label':tm['label'],'target_columns':dump(f['referenced_columns']),'source_constraint':f['name'],
                'source_cardinality':'one_to_one' if unique else 'many_to_one','source_optional':optional,
                'source_on_delete':f.get('on_delete','NO ACTION'),'source_on_update':f.get('on_update','NO ACTION'),'dimension_basis':basis,**source_fields(f['source']),
                'notes':'SQL键基数与可空只供映射参考；删改动作不自动级联到本库。'+('技术/安全端点默认停用。' if not enabled else '')})
    for item in catalog['files']:
        extras['源码覆盖'].append({k:item[k] for k in ['sha256','bytes','statements','ddl_count','unparsed_count']})
        extras['源码覆盖'][-1].update({'source_path':item['path'],'source_commit':catalog['source']['commit'],
            'source_url':catalog['source']['repository'].rstrip('/')+'/blob/'+catalog['source']['commit']+'/'+item['path'],'notes':'公开仓库结构定义，未读取生产数据。SHA256/bytes为本地提取文本副本；GitHub页面提取可能去掉末尾换行，不等同Git blob原始字节摘要。'})
    for item in catalog['ddl_audit']:
        extras['DDL审计'].append({'status':item['status'],'operation':item['operation'],'object':item.get('object',''),'sql':item.get('sql',''),
            'parts':dump(item.get('parts',[])),**source_fields(item['source'])})
    sheets=[]
    extra_keys={
      'packages':['source_commit','notes'],
      'types':['source_table','classification','domain']+PROVENANCE+['notes'],
      'properties':['handling','source_table','source_column','source_sql_type','source_nullable','source_primary_key','source_unique','source_default','source_checks','source_enum_values']+PROVENANCE+['notes'],
      'predicates':['source_table','source_type_label','source_columns','target_table','target_type_label','target_columns','source_constraint','source_cardinality','source_optional','source_on_delete','source_on_update','dimension_basis']+PROVENANCE+['notes'],
      'dependencies':['notes']}
    for name,(kind,keys) in SHEETS.items():sheets.append(sheet(name,keys+extra_keys[kind],rows[kind]))
    for name,items in extras.items():
        keys=list(dict.fromkeys(k for row in items for k in row))
        sheets.append(sheet(name,keys,items))
    counts={kind:{'total':len(items),'enabled':sum(r['enabled'] for r in items)} for kind,items in rows.items()}
    return {'schema_version':'liangzihu-workbook-data/1','source':catalog['source'],'source_counts':catalog['counts'],'coverage':catalog['coverage'],
        'definition_counts':counts,'sheets':sheets,'policy':['来源记录本体与显式链接；农业业务概念等价关系另行确认。','enabled只影响离线定义导出；不会连接或写入生产库。',
        '主键、必填、唯一、CHECK、默认值和删改动作保留为来源事实，不宣称本库全部执行。','停用行保留完整结构；技术/安全默认仅编目。',
        '全部属性usage=attribute；观测、断言和事件须使用相应接入契约。']}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=Path('outputs/liangzihu-ontology-20261015/schema_catalog.json'))
    parser.add_argument('--labels',type=Path,default=Path('tools/ontology_export/domain_labels.json'))
    parser.add_argument('--output',type=Path,default=Path('outputs/liangzihu-ontology-20261015/workbook_data.json'))
    parser.add_argument('--packages-dir',type=Path,default=Path('outputs/liangzihu-ontology-20261015/packages'))
    args=parser.parse_args(argv)
    catalog=json.loads(args.catalog.read_text(encoding='utf-8'));labels=json.loads(args.labels.read_text(encoding='utf-8'))
    data=build_workbook_data(catalog,labels)
    machine={SHEETS[s['name']][0]:s['rows'] for s in data['sheets'] if s['name'] in SHEETS}
    packages,report=rows_to_packages(machine)
    data['validation']=report['validation']
    data['input_hashes']={'schema_catalog_sha256':hashlib.sha256(args.catalog.read_bytes()).hexdigest(),'domain_labels_sha256':hashlib.sha256(args.labels.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    manifest=write_output(packages,report,args.output,args.packages_dir)
    manifest['source_kind']='generated_workbook_data';manifest['source_data']=manifest.pop('source_workbook');manifest['source_data_sha256']=manifest.pop('workbook_sha256')
    (args.packages_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'counts':data['definition_counts'],'validation':report['validation'],'packages_dir':str(args.packages_dir)},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())

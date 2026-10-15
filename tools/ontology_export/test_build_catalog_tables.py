"""Meaningful generator checks from synthetic DDL; no XLSX authoring."""
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from extract_schema import extract
from build_catalog_tables import build_workbook_data,property_mapping,VERSION
from workbook_to_packages import SHEETS,rows_to_packages

def source(tmp_path):
    (tmp_path/'001.sql').write_text("""
CREATE TABLE users(id uuid PRIMARY KEY, display_name text NOT NULL, password_hash text);
CREATE TABLE fields(id uuid PRIMARY KEY, owner_id uuid REFERENCES users(id), area numeric(20,6),
 state text CHECK(state IN ('active','inactive')), surveyed date, tags text[], geom geometry(Point,4326),
 details jsonb, related_ids uuid[], created_at timestamptz);
CREATE TABLE sessions(token_hash char(64) PRIMARY KEY, user_id uuid REFERENCES users(id));
""",encoding='utf-8')
    catalog=extract(tmp_path)
    labels={'domains':{'business':{'label':'业务','description':'业务记录'},'security':{'label':'安全','description':'安全记录'}},
        'tables':{n:{'label':n,'domain':'security' if n=='sessions' else 'business',
                    'classification':'security' if n=='sessions' else 'business','default_import':n!='sessions',
                    'boundary':'来源记录'} for n in ['users','fields','sessions']},
        'field_labels':{'id':'来源标识','state':'来源状态'}}
    return catalog,labels

def data_sheet(data,name):return next(s['rows'] for s in data['sheets'] if s['name']==name)

def test_generator_preserves_all_columns_and_explicit_mapping_boundaries(tmp_path):
    cat,labels=source(tmp_path);data=build_workbook_data(cat,labels)
    props={r['source_table']+'.'+r['source_column']:r for r in data_sheet(data,'属性定义')}
    assert len(props)==cat['counts']['columns']
    assert all(p['required'] is False and p['usage']=='attribute' for p in props.values())
    assert props['fields.owner_id']['enabled'] is False
    for name in ['geom','details','related_ids']:
        assert props['fields.'+name]['enabled'] is False
        assert props['fields.'+name]['handling'].startswith('deferred_')
    assert props['users.password_hash']['enabled'] is False
    assert props['fields.surveyed']['value_type']=='string'
    assert props['fields.tags']['cardinality']=='many' and props['fields.tags']['enabled']
    assert props['fields.state']['value_type']=='enum'
    assert json.loads(props['fields.state']['enum_values'])==['active','inactive']
    assert props['fields.id']['enabled'] and props['fields.id']['source_primary_key']
    assert props['fields.area']['value_type']=='decimal'
    assert props['fields.created_at']['value_type']=='datetime'

def test_real_service_registration_has_independent_identity_and_no_live_mutation(tmp_path):
    cat,labels=source(tmp_path);data=build_workbook_data(cat,labels)
    rows={SHEETS[s['name']][0]:s['rows'] for s in data['sheets'] if s['name'] in SHEETS}
    packages,report=rows_to_packages(rows)
    assert report['validation']['status']=='passed'
    assert report['validation']['production_database_touched'] is False
    assert report['validation']['postgresql_verified'] is False
    assert VERSION=='0.1.0'
    bridge=next(p for p in packages if p['package_id']=='lzhu.links1')
    assert bridge['predicates'][0]['subject_types']==['lzhu:fields']
    assert bridge['predicates'][0]['object_types']==['lzhu:users']
    assert 'subject_semantic_types' not in bridge['predicates'][0]
    assert len(bridge['predicates'])==1
    assert len(data_sheet(data,'关系类型'))==2
    assert cat['source']['commit'] in bridge['description']

def test_audit_coverage_and_partial_unique_are_source_facts(tmp_path):
    cat,labels=source(tmp_path)
    data=build_workbook_data(cat,labels)
    assert len(data_sheet(data,'源表清单'))==3
    assert len(data_sheet(data,'约束枚举'))==cat['counts']['constraints']
    assert len(data_sheet(data,'源码覆盖'))==1
    assert all(r['source_url'] for r in data_sheet(data,'DDL审计'))
    relations=data_sheet(data,'关系类型')
    field_fk=next(r for r in relations if r['source_table']=='fields')
    assert field_fk['source_cardinality']=='many_to_one'
    assert field_fk['source_optional'] is True
    assert field_fk['irreflexive'] is False and field_fk['acyclic'] is False
    assert field_fk['enabled'] is True

def test_missing_metadata_and_bad_coverage_fail_closed(tmp_path):
    cat,labels=source(tmp_path);del labels['tables']['fields']
    with pytest.raises(ValueError,match='分类缺失'):build_workbook_data(cat,labels)
    cat['coverage']['all_references_resolved']=False
    with pytest.raises(ValueError,match='审计未通过'):build_workbook_data(cat,labels)

@pytest.mark.parametrize('sql', ['public.vector(512)','jsonb','geometry(Geometry,4326)','uuid[]','bytea','custom_unknown'])
def test_non_scalar_types_never_get_guessed_as_string(sql):
    mapping=property_mapping({'name':'payload','sql_type':sql})
    assert mapping['handling'].startswith('deferred_')
    assert mapping['value_type']==''


def test_business_certificate_ids_are_not_authentication_credentials():
    mapping=property_mapping({'name':'credential_ids','sql_type':'uuid[]'})
    assert mapping['handling']=='deferred_array_identity'
    auth=property_mapping({'name':'execution_token','sql_type':'uuid'})
    assert auth['handling']=='deferred_credentials'


@pytest.mark.parametrize('table,column,sql,handling', [
    ('users','enabled','boolean','deferred_identity_policy'),
    ('users','wecom_identity_evidence','text','deferred_identity_policy'),
    ('flight_files','parent_external_ids','text[]','deferred_array_identity'),
])
def test_source_identity_policy_and_parent_links_require_explicit_mapping(table,column,sql,handling):
    mapping=property_mapping({'name':column,'sql_type':sql},table)
    assert mapping['handling']==handling
    assert mapping['value_type']==''
    # Identical generic field names in other record types retain their meanings.
    if column=='enabled':
        ordinary=property_mapping({'name':column,'sql_type':sql},'devices')
        assert ordinary['value_type']=='boolean'
        assert ordinary['handling']=='scalar'

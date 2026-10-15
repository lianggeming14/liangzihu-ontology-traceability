"""Converter tests use in-memory row arrays; no workbook authoring API is used."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from workbook_to_packages import rows_to_packages,WorkbookError,write_output
from validate_packages import validate_packages,load_packages


def fixture_rows():
    return {
      'packages':[{'enabled':True,'package_id':'lzh.field','version':'1.0.0','namespace':'https://example.test/lzh/field/','label':'田块本体'}],
      'types':[{'enabled':True,'package_id':'lzh.field','version':'1.0.0','type_id':'lzh:Field','identity_type':'field','label':'田块'}],
      'properties':[{'enabled':True,'package_id':'lzh.field','version':'1.0.0','property_id':'lzh:field.area','label':'面积','applies_to':'["lzh:Field"]','value_type':'decimal','unit':'ha','usage':'attribute','required':False,'cardinality':'single','minimum':0,'handling':'scalar','source_sql_type':'numeric(12,3)'}],
      'predicates':[{'enabled':True,'package_id':'lzh.field','version':'1.0.0','predicate_id':'lzh:adjacent','label':'相邻','subject_types':'["field"]','object_types':'["field"]','subject_semantic_types':'["lzh:Field"]','object_semantic_types':'["lzh:Field"]','dimension':'space','irreflexive':True,'acyclic':False}],
      'dependencies':[]}


def test_rows_export_only_definitions_in_isolated_database():
    packages,report=rows_to_packages(fixture_rows())
    assert report['validation']['status']=='passed'
    assert report['validation']['production_database_touched'] is False
    assert report['validation']['postgresql_verified'] is False
    assert packages[0]['properties'][0]['applies_to']==['lzh:Field']
    assert packages[0]['predicates'][0]['irreflexive'] is True
    assert 'source_sql_type' not in packages[0]['properties'][0]
    assert report['validation']['definition_counts']=={'packages':1,'types':1,'properties':1,'predicates':1}

@pytest.mark.parametrize('sql,handling,cardinality',[
 ('jsonb','scalar','single'),('geometry(Point,4326)','scalar','single'),('text[]','scalar','single'),
 ('bytea','scalar','single'),('hstore','scalar','single'),('xml','scalar','single'),
 ('text[]','array_scalar','single'),('numeric','deferred_numeric','single'),
])
def test_unsupported_source_types_are_not_silently_coerced(sql,handling,cardinality):
    tables=fixture_rows();prop=tables['properties'][0];prop.update(source_sql_type=sql,handling=handling,cardinality=cardinality,value_type='string')
    with pytest.raises(WorkbookError):rows_to_packages(tables)


def test_disabled_composite_fields_remain_explicitly_reported():
    tables=fixture_rows();prop=deepcopy(tables['properties'][0]);prop.update(enabled=False,property_id='lzh:field.geometry',source_sql_type='geometry',handling='deferred_geometry')
    tables['properties'].append(prop)
    packages,report=rows_to_packages(tables)
    assert len(packages[0]['properties'])==1
    assert report['skipped_rows'][0]['handling']=='deferred_geometry'
    assert report['skipped_rows'][0]['reason']=='enabled=FALSE'


def test_explicit_scalar_array_is_preserved():
    tables=fixture_rows();tables['properties'][0].update(source_sql_type='text[]',handling='array_scalar',cardinality='many',value_type='string',unit=None,minimum=None)
    packages,_=rows_to_packages(tables)
    assert packages[0]['properties'][0]['cardinality']=='many'

@pytest.mark.parametrize('column,value', [('applies_to','lzh:Field'),('applies_to','["lzh:Field","lzh:Field"]'),('required','FALSE'),('minimum','0'),('enabled','TRUE'),('package_id',123)])
def test_ambiguous_cell_values_fail_closed(column,value):
    tables=fixture_rows();tables['properties'][0][column]=value
    with pytest.raises(WorkbookError):rows_to_packages(tables)


def test_duplicate_and_missing_definition_references_fail():
    tables=fixture_rows();tables['types'].append(deepcopy(tables['types'][0]))
    with pytest.raises(WorkbookError,match='重复定义'):rows_to_packages(tables)
    tables=fixture_rows();tables['properties'][0]['applies_to']='["missing"]'
    with pytest.raises(ValueError,match='unknown_property_class'):rows_to_packages(tables)


def test_cross_package_identity_relation_and_topological_order():
    tables=fixture_rows()
    tables['packages'].insert(0,{'enabled':True,'package_id':'lzh.bridge','version':'1.0.0','namespace':'https://example.test/lzh/bridge/','label':'跨域关系'})
    tables['types'].append({'enabled':True,'package_id':'lzh.bridge','version':'1.0.0','type_id':'bridge:LinkRecord','identity_type':'bridge_record','label':'关系记录'})
    tables['dependencies'].append({'enabled':True,'package_id':'lzh.bridge','version':'1.0.0','depends_on_package_id':'lzh.field','depends_on_version':'1.0.0'})
    tables['predicates'].append({'enabled':True,'package_id':'lzh.bridge','version':'1.0.0','predicate_id':'bridge:references','label':'引用田块','subject_types':'["bridge_record"]','object_types':'["field"]','dimension':'identity'})
    packages,_=rows_to_packages(tables)
    assert [p['package_id'] for p in packages]==['lzh.field','lzh.bridge']
    assert 'object_semantic_types' not in packages[1]['predicates'][0]


def test_exact_dependencies_and_cycles_rejected():
    tables=fixture_rows();tables['dependencies']=[{'enabled':True,'package_id':'lzh.field','version':'1.0.0','depends_on_package_id':'missing','depends_on_version':'1.0.0'}]
    with pytest.raises(ValueError,match='缺少精确版本依赖'):rows_to_packages(tables)
    tables['dependencies'][0]['depends_on_package_id']='lzh.field'
    with pytest.raises(ValueError,match='依赖成环'):rows_to_packages(tables)


def test_output_manifest_loads_verifies_and_detects_tampering(tmp_path):
    packages,report=rows_to_packages(fixture_rows())
    source=tmp_path/'source-fixture.txt';source.write_text('in-memory rows, not an authored workbook',encoding='utf-8')
    folder=tmp_path/'packages';manifest=write_output(packages,report,source,folder)
    assert load_packages(folder)==packages
    assert validate_packages(load_packages(folder))['status']=='passed'
    payload=folder/manifest['packages'][0]['file'];payload.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='文件哈希不匹配'):load_packages(folder)


def test_semantic_type_from_other_package_cannot_sneak_into_same_package_ref():
    tables=fixture_rows();tables['predicates'][0]['object_semantic_types']='["external:Field"]'
    with pytest.raises(ValueError,match='unknown_relation_class'):rows_to_packages(tables)


def test_timestamptz_cannot_be_relabeled_as_plain_string():
    tables=fixture_rows()
    tables['properties'][0].update(source_sql_type='timestamptz',handling='scalar',value_type='string',unit=None,minimum=None)
    with pytest.raises(WorkbookError,match='timestamp'):rows_to_packages(tables)


def test_unknown_endpoint_identity_cannot_pass_self_contained_export():
    tables=fixture_rows()
    tables['predicates'][0].update(subject_types='["lzhu:disabled_source"]',subject_semantic_types=None)
    with pytest.raises(ValueError,match='unknown_endpoint_identity'):rows_to_packages(tables)


def test_missing_sheet_dimensions_do_not_disable_actual_read_budgets(monkeypatch):
    import workbook_to_packages as converter
    monkeypatch.setattr(converter,'MAX_ROWS',2)
    monkeypatch.setattr(converter,'MAX_COLUMNS',3)
    class ReadOnlySheet:
        max_row=None;max_column=None
        def __init__(self,rows):self.rows=rows;self.reset=False
        def reset_dimensions(self):self.reset=True
        def iter_rows(self):yield from self.rows
    sheet=ReadOnlySheet([(None,)*2]*4)
    assert len(list(converter._bounded_sheet_rows(sheet,'test')))==4
    assert sheet.reset is True
    with pytest.raises(WorkbookError,match='预算'):
        list(converter._bounded_sheet_rows(ReadOnlySheet([(None,)*4]),'test'))
    with pytest.raises(WorkbookError,match='预算'):
        list(converter._bounded_sheet_rows(ReadOnlySheet([(None,)]*5),'test'))

def test_final_artifact_workbook_read_only_roundtrip_preserves_source_hash():
    import hashlib
    from workbook_to_packages import read_workbook
    path=Path(__file__).resolve().parents[2]/'outputs/liangzihu-ontology-20261015/梁子湖项目_本体与关系全量结构导出.xlsx'
    if not path.exists():pytest.skip('Final XLSX artifact not present in this checkout')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    tables=read_workbook(path)
    assert len(tables['properties'])==2114
    assert len(tables['predicates'])==555
    packages,report=rows_to_packages(tables)
    assert report['validation']['definition_counts']=={'packages':18,'types':124,'properties':979,'predicates':409}
    assert report['validation']['production_database_touched'] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before

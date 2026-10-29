import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[3]


def module():
    path=ROOT/'scripts/build_drawing_gis.py'
    assert path.is_file(), 'Drawing builder missing'
    spec=importlib.util.spec_from_file_location('drawing_builder',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_identity_uses_real_uuid_and_rejects_duplicate_owners():
    m=module();entry={'dataset':'real','data_nature':'imported_unverified','resource_id':'x','spatial_ids':['A']}
    assert m.identity_index([entry,dict(entry,dataset='demo',resource_id='y')])['A']['resource_id']=='x'
    with pytest.raises(ValueError):m.identity_index([entry,dict(entry,resource_id='z')])


def test_annotation_does_not_become_physical_facility():
    m=module();record={'representation_id':'point','geometry':{'type':'Point','coordinates':[1,1]},'label':'pump','kind':'facility',
        'identity_scope':'drawing_annotation_not_verified_unique_asset','area_original':12,'area_unit':None}
    item=m.feature_record(record,'pdf-01',{'resource_id':'x'})
    assert item['kind']=='facility_annotation' and item['area_m2'] is None
    assert item['ledger_area']['unit'] is None


def test_drawing_identity_is_persistent_and_source_hash_checked():
    m=module()
    item={'asset_id':'detail-miaoxia','source_hash':'9258ee26b29860579c900aeb1dbf3a4ca6d2cef6c02ec2d317e3349f4157c91a'}
    assert m.drawing_identity(item)=='pdf-01'
    with pytest.raises(ValueError):m.drawing_identity(dict(item,source_hash='0'*64))


def test_empty_untranscribed_table_keeps_context():
    m=module();table={'name':'Area','unit':'mu','rows':[],'status':'untranscribed'}
    rows=m.table_annotations('pdf-03',0,table,'review.json')
    assert len(rows)==1 and rows[0]['record_type']=='table'
    assert rows[0]['table']['status']=='untranscribed'

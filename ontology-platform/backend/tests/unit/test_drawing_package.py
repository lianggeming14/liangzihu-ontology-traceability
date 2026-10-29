import copy
import importlib.util
import pytest


def package():
    return {'schema_version':'drawing-gis/1','dataset_id':'liangzihu-asbuilt-2026','version':1,
        'drawings':[{'drawing_id':'pdf-01','source_sha256':'a'*64,'page_size_pt':[100,100],
                     'coordinate_system':'PDF_LANDSCAPE_LOCAL','coordinate_units':'pt','georeferenced':False}],
        'features':[{'feature_id':'F1','drawing_id':'pdf-01','entity_id':'9f450d79-3c82-45cb-bd6b-1721b7924db1',
                     'kind':'field','label':'F1','data_nature':'imported_unverified',
                     'geometry':{'type':'Polygon','coordinates':[[[1,1],[9,1],[9,9],[1,1]]]},
                     'area_m2':None,'length_m':None}],
        'annotations':[], 'coverage':{'semantic_complete':False,'unresolved':['unregistered paper coordinates']}}


def test_drawing_package_module_exists():
    assert importlib.util.find_spec('lzo.gis.drawing_package') is not None


@pytest.mark.parametrize('field',['label','entity_id','kind'])
def test_api_required_fields_rejected_before_import(field):
    from lzo.gis.drawing_package import seal_package
    p=package();del p['features'][0][field]
    with pytest.raises(ValueError):seal_package(p)


@pytest.mark.parametrize('identity',['9f450d793c8245cbbd6b1721b7924db1','9F450D79-3C82-45CB-BD6B-1721B7924DB1','urn:uuid:9f450d79-3c82-45cb-bd6b-1721b7924db1'])
def test_identity_must_equal_uuid_returned_to_clients(identity):
    from lzo.gis.drawing_package import seal_package
    p=package();p['features'][0]['entity_id']=identity
    with pytest.raises(ValueError):seal_package(p)


def test_digest_and_mutation():
    from lzo.gis.drawing_package import seal_package, validate_package
    p=seal_package(package())
    assert validate_package(p)['content_sha256']==p['content_sha256']
    p['features'][0]['label']='changed'
    with pytest.raises(ValueError,match='digest'):validate_package(p)


@pytest.mark.parametrize('bad', [float('nan'),float('inf'),True,101,-1])
def test_coordinates_must_be_finite_numeric_and_inside_page(bad):
    from lzo.gis.drawing_package import seal_package
    p=package();p['features'][0]['geometry']['coordinates'][0][0][0]=bad
    with pytest.raises(ValueError):seal_package(p)


def test_duplicates_unknown_drawing_and_open_ring():
    from lzo.gis.drawing_package import seal_package
    p=package();p['features'].append(copy.deepcopy(p['features'][0]))
    with pytest.raises(ValueError):seal_package(p)
    p=package();p['features'][0]['drawing_id']='missing'
    with pytest.raises(ValueError):seal_package(p)
    p=package();p['features'][0]['geometry']['coordinates'][0][-1]=[3,3]
    with pytest.raises(ValueError):seal_package(p)


@pytest.mark.parametrize('field,value',[('area_m2',10),('length_m',2),('data_nature','synthetic')])
def test_paper_geometry_cannot_claim_ground_metrics_or_mix_demo(field,value):
    from lzo.gis.drawing_package import seal_package
    p=package();p['features'][0][field]=value
    with pytest.raises(ValueError):seal_package(p)


def test_missing_unit_remains_unknown_and_duplicate_label_allowed():
    from lzo.gis.drawing_package import seal_package
    p=package();p['features'][0]['ledger_area']={'value':'12.34','unit':None}
    other=copy.deepcopy(p['features'][0]);other.update(feature_id='other',entity_id=None)
    p['features'].append(other)
    result=seal_package(p)
    assert result['features'][0]['ledger_area']['unit'] is None
    assert len(result['features'])==2

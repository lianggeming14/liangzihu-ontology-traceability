import copy
import importlib.util
import pytest
from sqlalchemy import create_engine, text
from test_drawing_package import package


def test_store_module_exists():
    assert importlib.util.find_spec('lzo.gis.drawing_store') is not None


@pytest.fixture
def store(tmp_path):
    from lzo.gis.drawing_store import DrawingStore
    engine=create_engine('sqlite:///'+str(tmp_path/'drawings.sqlite3'))
    value=DrawingStore(engine);value.initialize_offline()
    yield value
    engine.dispose()


def populated(store):
    from lzo.gis.drawing_package import seal_package
    p=package()
    for i in range(2,6):
        item=copy.deepcopy(p['features'][0]);item.update(feature_id=f'F{i}',entity_id=None,kind='pond' if i%2 else 'field')
        p['features'].append(item)
    p['annotations']=[{'annotation_id':f'A{i}','drawing_id':'pdf-01','text_original':f'water {i}','record_type':'native_text'} for i in range(5)]
    p=seal_package(p);store.import_package(p);return p


def test_replay_conflict_and_atomicity(store):
    from lzo.gis.drawing_package import seal_package
    p=populated(store)
    assert store.import_package(p)['status']=='unchanged'
    p['features'][0]['label']='different';p=seal_package(p)
    with pytest.raises(ValueError,match='version'):store.import_package(p)
    assert store.feature('F1')['label']=='F1'
    assert len(store.features(limit=100)['features'])==5


def test_pagination_filters_detail_and_unknown_units(store):
    populated(store);all_ids=[];cursor=None
    while True:
        page=store.features(drawing_id='pdf-01',limit=2,cursor=cursor)
        assert page['type']=='DrawingFeaturePage' and page['coordinate_units']=='pt'
        all_ids.extend(r['feature_id'] for r in page['features']);cursor=page['next_cursor']
        if cursor is None:break
    assert all_ids==['F1','F2','F3','F4','F5']
    assert len(store.features(kind='pond')['features'])==2
    assert store.features(bbox='50,50,60,60')['features']==[]
    assert store.feature('9f450d79-3c82-45cb-bd6b-1721b7924db1')['feature_id']=='F1'
    assert store.feature('F1')['area_m2'] is None
    assert store.coverage()['semantic_complete'] is False


def test_annotation_pagination_no_omission(store):
    populated(store);seen=[];cursor=None
    while True:
        p=store.annotations(drawing_id='pdf-01',limit=2,cursor=cursor)
        seen.extend(r['annotation_id'] for r in p['items']);cursor=p['next_cursor']
        if not cursor:break
    assert seen==['A0','A1','A2','A3','A4']


def test_invalid_and_stale_cursor(store):
    from lzo.gis.drawing_package import seal_package
    p=populated(store);cursor=store.features(limit=2)['next_cursor']
    with pytest.raises(ValueError):store.features(cursor=cursor,kind='pond')
    for bbox in ['nan,1,2,3','5,5,1,1','1,2,3']:
        with pytest.raises(ValueError):store.features(bbox=bbox)
    for size in [0,1001]:
        with pytest.raises(ValueError):store.features(limit=size)
    with pytest.raises(ValueError):store.features(cursor='not-json')
    p['version']=2;store.import_package(seal_package(p))
    with pytest.raises(ValueError,match='stale'):store.features(cursor=cursor)


def test_empty_store_and_unknown_drawing_fail(store):
    with pytest.raises(LookupError):store.drawings()
    populated(store)
    with pytest.raises(LookupError):store.feature('unknown')
    with pytest.raises(LookupError):store.features(drawing_id='pdf-99')

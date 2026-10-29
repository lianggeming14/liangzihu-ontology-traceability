"""Actual PostGIS tests use a fresh owned schema; no shared tables are changed."""
import copy
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from lzo.gis.drawing_package import seal_package
from lzo.gis.drawing_store import DrawingStore

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture
def drawing_pg():
    url=os.environ.get('LZO_DRAWING_TEST_DATABASE_URL')
    if not url:pytest.skip('Explicit isolated PostGIS test URL not supplied')
    schema='drawing_test_'+uuid4().hex
    owner=create_engine(url)
    with owner.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(url,connect_args={'options':f'-c search_path={schema},public'})
    try:
        with engine.begin() as c:
            c.execute(text('CREATE TABLE store_schema_version(version integer); INSERT INTO store_schema_version VALUES(4)'))
            c.execute(text((ROOT/'database/gis/005_drawings.sql').read_text('utf8')))
        yield DrawingStore(engine)
    finally:
        engine.dispose()
        with owner.begin() as c:c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        owner.dispose()


def source_package():
    import json
    return json.loads((ROOT/'datasets/drawings/package.json').read_text('utf8'))


def test_actual_source_geometries_have_srid_zero_and_roundtrip(drawing_pg):
    p=source_package();assert drawing_pg.import_package(p)['status']=='imported'
    assert drawing_pg.import_package(p)['status']=='unchanged'
    with drawing_pg.engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM gis_drawing_features')).scalar_one()==len(p['features'])
        assert c.execute(text('SELECT count(*) FROM gis_drawing_features WHERE public.ST_SRID(paper_geom)<>0 OR paper_geom IS NULL')).scalar_one()==0
        # Source validity is measured, never silently fixed or claimed verified.
        assert c.execute(text('SELECT count(*) FROM gis_drawing_features WHERE public.ST_IsEmpty(paper_geom)')).scalar_one()==0
        assert c.execute(text('SELECT version FROM store_schema_version')).scalar_one()==5
    ids=[];cursor=None
    while True:
        page=drawing_pg.features(limit=17,cursor=cursor);ids.extend(f['feature_id'] for f in page['features']);cursor=page['next_cursor']
        if not cursor:break
    assert sorted(ids)==sorted(f['feature_id'] for f in p['features'])
    first=p['features'][0]
    assert drawing_pg.feature(first['entity_id'])['geometry']==first['geometry']


def test_failure_rolls_back_every_table(drawing_pg):
    p=source_package()
    with drawing_pg.engine.begin() as c:
        c.execute(text("ALTER TABLE gis_drawing_annotations ADD CHECK(annotation_id NOT LIKE '%native%')"))
    with pytest.raises(Exception):drawing_pg.import_package(p)
    with drawing_pg.engine.connect() as c:
        for table in ['gis_drawing_datasets','gis_drawings','gis_drawing_features','gis_drawing_annotations']:
            assert c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()==0


def test_changed_content_cannot_replace_same_version(drawing_pg):
    p=source_package();drawing_pg.import_package(p)
    altered=copy.deepcopy(p);altered['features'][0]['label']='changed'
    with pytest.raises(ValueError,match='version'):drawing_pg.import_package(seal_package(altered))
    assert drawing_pg.feature(p['features'][0]['feature_id'])['label']==p['features'][0]['label']

"""Verify a reviewed package in an explicitly configured owned GIS database."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from sqlalchemy import create_engine,text
from lzo.gis.drawing_package import validate_package
from lzo.gis.drawing_store import DrawingStore


def main():
    package=validate_package(json.loads((ROOT/'datasets/drawings/package.json').read_text('utf8')))
    owner_url=os.environ['LZO_GIS_MIGRATION_DATABASE_URL']
    app_url=os.environ['LZO_GIS_DATABASE_URL']
    owner=create_engine(owner_url);app=create_engine(app_url)
    if owner.dialect.name!='postgresql' or app.dialect.name!='postgresql':raise ValueError('Actual PostgreSQL required')
    try:
        store=DrawingStore(owner)
        with owner.connect() as c:
            if c.execute(text('SELECT current_user')).scalar_one()!='lzo_gis_owner':raise ValueError('Explicit GIS owner required')
        imported=store.import_package(package)
        replay=store.import_package(package)
        with owner.connect() as c:
            counts=dict(c.execute(text('''SELECT count(*) AS total,
                count(*) FILTER(WHERE ST_SRID(paper_geom)=0) AS local_srid_zero,
                count(*) FILTER(WHERE ST_IsValid(paper_geom)) AS valid,
                count(*) FILTER(WHERE ST_IsEmpty(paper_geom)) AS empty
                FROM gis_drawing_features WHERE dataset_id=:dataset AND version=:version'''),
                {'dataset':package['dataset_id'],'version':package['version']}).mappings().one())
            invalid=[dict(r) for r in c.execute(text('''SELECT feature_id, ST_IsValidReason(paper_geom) AS reason
                FROM gis_drawing_features WHERE dataset_id=:dataset AND version=:version AND NOT ST_IsValid(paper_geom)'''),
                {'dataset':package['dataset_id'],'version':package['version']}).mappings()]
        reader=DrawingStore(app);head=reader.drawings();assert head['content_sha256']==package['content_sha256']
        found=[];cursor=None
        while True:
            page=reader.features(limit=17,cursor=cursor);found.extend(f['feature_id'] for f in page['features'])
            cursor=page['next_cursor']
            if not cursor:break
        assert len(found)==len(set(found))==len(package['features'])
        evidence=[];cursor=None
        while True:
            page=reader.annotations(limit=137,cursor=cursor);evidence.extend(a['annotation_id'] for a in page['items'])
            cursor=page['next_cursor']
            if not cursor:break
        assert len(evidence)==len(set(evidence))==len(package['annotations'])
        for feature in package['features']:
            assert reader.feature(feature['entity_id'])['feature_id']==feature['feature_id']
        with app.connect() as c:
            privileges={name:c.execute(text('SELECT has_table_privilege(current_user,:table,:privilege)'),
                {'table':'gis_drawing_features','privilege':name}).scalar_one() for name in ('SELECT','INSERT','UPDATE','DELETE')}
        assert privileges=={'SELECT':True,'INSERT':False,'UPDATE':False,'DELETE':False}
        report={'database':'PostgreSQL + PostGIS; isolated owned loopback runtime','data_nature':'actual drawing-derived imported_unverified',
                'package_sha256':package['content_sha256'],'import':imported,'replay':replay,'geometry':counts,
                'invalid_source_geometry_preserved':invalid,'app_role_privileges':privileges,'pagination_distinct_features':len(found),
                'pagination_distinct_annotations':len(evidence),'uuid_lookup_verified':len(found),
                'georeferencing':'not available','field_acceptance':'not performed','governed_core_registration':'not performed'}
        target=ROOT/'docs/gis/postgis-import.json';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
        print(json.dumps({'status':'verified','features':len(found),'valid':counts['valid'],'invalid':len(invalid),'sha256':package['content_sha256']}))
    finally:owner.dispose();app.dispose()


if __name__=='__main__':main()

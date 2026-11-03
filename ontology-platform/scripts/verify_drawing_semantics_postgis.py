"""Read back all typed drawing data using the real least-privilege GIS app role."""
import json
import os
from collections import Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from sqlalchemy import create_engine,text
from lzo.gis.drawing_semantics_store import DrawingSemanticsStore,validate_bundle


def main():
    bundle=validate_bundle(json.loads((ROOT/'datasets/drawings/semantic-bundle.json').read_text('utf8')))
    owner=create_engine(os.environ['LZO_GIS_MIGRATION_DATABASE_URL'])
    app=create_engine(os.environ['LZO_GIS_DATABASE_URL'])
    if owner.dialect.name!='postgresql' or app.dialect.name!='postgresql':raise ValueError('Actual PostgreSQL required')
    try:
        replay=DrawingSemanticsStore(owner).import_bundle(bundle)
        reader=DrawingSemanticsStore(app)
        found=[];cursor=None
        while True:
            page=reader.measurements(limit=113,cursor=cursor)
            assert page['content_sha256']==bundle['content_sha256']
            found.extend(page['items']);cursor=page['next_cursor']
            if not cursor:break
        assert {m['id'] for m in found}=={m['id'] for m in bundle['measurements']}
        assert len(found)==len(bundle['measurements'])
        kinds=Counter(m['kind'] for m in found)
        for kind,count in kinds.items():
            page=reader.measurements(kind=kind,limit=1000)
            assert len(page['items'])==count
            assert all(m['kind']==kind for m in page['items'])
        relationships=0
        for profile in bundle['profiles']:
            assert reader.profile(profile['entity_id'])['item']==profile
            assert reader.profile(profile['feature_id'])['item']==profile
            assert reader.entity(profile['entity_id'])['item']['id']==profile['entity_id']
            page=reader.measurements(subject_id=profile['entity_id'],limit=1000)
            assert {m['id'] for m in page['items']}==set(profile['measurement_ids'])
            page=reader.relationships(subject_id=profile['entity_id'],limit=1000)
            assert len(page['items'])==len(profile['relations'])
            relationships+=len(page['items'])
        with app.connect() as c:
            assert c.execute(text('SELECT version FROM store_schema_version')).scalar_one()==6
            tables=['gis_drawing_semantics_'+suffix for suffix in ('datasets','heads','nodes','edges','profiles','measurements')]
            privileges={table:{p:c.execute(text('SELECT has_table_privilege(current_user,:table,:privilege)'),
                {'table':table,'privilege':p}).scalar_one() for p in ('SELECT','INSERT','UPDATE','DELETE')} for table in tables}
            assert all(v=={'SELECT':True,'INSERT':False,'UPDATE':False,'DELETE':False} for v in privileges.values())
            counts={suffix:c.execute(text('SELECT count(*) FROM gis_drawing_semantics_'+suffix+' WHERE dataset_id=:dataset AND version=:version'),
                {'dataset':bundle['dataset_id'],'version':bundle['version']}).scalar_one() for suffix in ('nodes','edges','profiles','measurements')}
        report=dict(status='passed',database='actual PostgreSQL + PostGIS, owned local runtime',
            semantic_bundle_sha256=bundle['content_sha256'],source_package_sha256=bundle['source_package_sha256'],
            counts=counts,measurements_by_kind=kinds,pagination_distinct_measurements=len(found),
            profile_lookup_by_uuid_and_representation=len(bundle['profiles']),profile_relationships_verified=relationships,
            replay=replay,app_role_privileges=privileges,data_nature='imported_unverified',
            formal_core_ontology='not_imported; verified operator and schema approval required',
            field_acceptance='not_performed',georeferencing='not_performed')
        (ROOT/'docs/gis/semantics-postgis-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
        print(json.dumps({'status':'passed',**counts,'measurement_kind_filters':len(kinds)}))
    finally:
        owner.dispose();app.dispose()


if __name__=='__main__':main()

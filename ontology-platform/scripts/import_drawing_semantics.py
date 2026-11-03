"""Validate by default; --apply imports the independent GIS semantics read model.

Import the matching drawing package first. --offline uses an existing SQLite
drawing mirror and is never PostgreSQL or field acceptance evidence.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from lzo.gis.drawing_semantics_store import DrawingSemanticsStore, validate_bundle


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=ROOT/'datasets/drawings/semantic-bundle.json')
    parser.add_argument('--offline',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    bundle=validate_bundle(json.loads(args.bundle.read_text(encoding='utf-8')))
    if not args.apply:
        print(json.dumps({'status':'validated_not_imported','content_sha256':bundle['content_sha256'],
            'source_package_sha256':bundle['source_package_sha256'],'source_binding_checked':False,
            'profiles':len(bundle['profiles']),'measurements':len(bundle['measurements'])}))
        return 0
    from sqlalchemy import create_engine, text
    if args.offline:
        if not args.offline.is_file():
            raise ValueError('Import source drawing package into the SQLite mirror first')
        engine=create_engine('sqlite:///'+str(args.offline.resolve()))
    else:
        url=os.environ.get('LZO_GIS_MIGRATION_DATABASE_URL')
        if not url:raise RuntimeError('Explicit GIS owner URL required in environment')
        engine=create_engine(url)
        if engine.dialect.name!='postgresql':
            engine.dispose()
            raise ValueError('Production GIS requires PostgreSQL')
    try:
        store=DrawingSemanticsStore(engine,bundle['dataset_id'])
        if args.offline:
            store.initialize_offline()
        else:
            with engine.connect() as connection:
                if connection.execute(text('SELECT current_user')).scalar_one()!='lzo_gis_owner':
                    raise RuntimeError('Drawing semantics import requires the GIS owner account')
        print(json.dumps(store.import_bundle(bundle),ensure_ascii=False))
    finally:
        engine.dispose()
    return 0


if __name__=='__main__':
    raise SystemExit(main())

"""Validate by default; --apply atomically imports the reviewed drawing package."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from lzo.gis.drawing_package import validate_package
from lzo.gis.drawing_store import DrawingStore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,default=ROOT/'datasets/drawings/package.json')
    parser.add_argument('--offline',type=Path,help='Explicit SQLite mirror, never a PostGIS acceptance substitute')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    package=validate_package(json.loads(args.package.read_text('utf8')))
    if not args.apply:
        print(json.dumps({'status':'validated_not_imported','sha256':package['content_sha256'],'features':len(package['features']),'annotations':len(package['annotations'])}));return
    from sqlalchemy import create_engine
    if args.offline:
        args.offline.parent.mkdir(parents=True,exist_ok=True)
        engine=create_engine('sqlite:///'+str(args.offline.resolve()))
    else:
        url=os.environ.get('LZO_GIS_MIGRATION_DATABASE_URL')
        if not url:raise RuntimeError('Explicit GIS owner URL required in environment')
        engine=create_engine(url)
        if engine.dialect.name!='postgresql':raise ValueError('Production GIS requires PostgreSQL')
    try:
        store=DrawingStore(engine,package['dataset_id'])
        if args.offline:store.initialize_offline()
        print(json.dumps(store.import_package(package),ensure_ascii=False))
    finally:engine.dispose()


if __name__=='__main__':main()

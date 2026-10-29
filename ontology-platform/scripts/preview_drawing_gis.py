"""Explicit loopback-only viewer for a reviewed offline SQLite mirror, not production auth."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--offline',required=True,type=Path);p.add_argument('--port',type=int,default=8791);a=p.parse_args()
    if not a.offline.is_file():raise ValueError('Import the reviewed package into an offline mirror first')
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from sqlalchemy import create_engine
    from lzo.gis.drawing_store import DrawingStore
    from lzo.gis.drawing_router import router,authorized_store
    import uvicorn
    import sqlite3
    engine=create_engine('sqlite://',creator=lambda:sqlite3.connect(a.offline.resolve().as_uri()+'?mode=ro',uri=True,check_same_thread=False))
    store=DrawingStore(engine);store.drawings()
    app=FastAPI(title='Reviewed drawing evidence - LOCAL OFFLINE PREVIEW')
    app.include_router(router)
    # Only this explicit offline app serves the user-reviewed public evidence.
    # Production lzo.main always retains real current-session authorization.
    app.dependency_overrides[authorized_store]=lambda:store
    app.mount('/',StaticFiles(directory=ROOT/'examples/drawing-map',html=True),name='viewer')
    try:uvicorn.run(app,host='127.0.0.1',port=a.port)
    finally:engine.dispose()


if __name__=='__main__':main()

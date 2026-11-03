import copy
import importlib
import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_drawing_semantics_store import bundle, store


def router_module():
    assert importlib.util.find_spec('lzo.gis.drawing_semantics_router'), 'semantics router missing'
    return importlib.import_module('lzo.gis.drawing_semantics_router')


def test_profile_measurements_relationships_and_source_conflict(store):
    semantics,source,spatial=store;semantics.import_bundle(bundle(source))
    module=router_module()
    from lzo.gis.drawing_router import authorized_store
    app=FastAPI();app.include_router(module.router)
    app.dependency_overrides[authorized_store]=lambda:spatial
    client=TestClient(app)
    profile=client.get('/api/v1/drawing-gis/profiles/F1')
    assert profile.status_code==200
    assert profile.json()['item']['paper_metrics']['perimeter_pt']==32
    assert profile.headers['cache-control']=='private, no-store'
    assert len(client.get('/api/v1/drawing-gis/measurements?kind=depth&subject_id=N1&drawing_id=pdf-01').json()['items'])==1
    assert client.get('/api/v1/drawing-gis/relationships?subject_id=N1').json()['items'][0]['object_id']=='N2'
    assert client.get('/api/v1/drawing-gis/entities/N2').json()['item']['label']=='N2'
    assert client.get('/api/v1/drawing-gis/entities/missing').status_code==404
    assert client.get('/api/v1/drawing-gis/profiles/missing').status_code==404
    assert client.get('/api/v1/drawing-gis/measurements?limit=1001').status_code==422
    assert client.get('/api/v1/drawing-gis/relationships').status_code==422
    from lzo.gis.drawing_package import seal_package
    changed=copy.deepcopy(source);changed['version']=2;spatial.import_package(seal_package(changed))
    assert client.get('/api/v1/drawing-gis/profiles/F1').status_code==409


def test_routes_require_existing_authorization_before_storage():
    module=router_module()
    from fastapi import HTTPException
    from lzo.gis.drawing_router import authorized_store
    def denied():raise HTTPException(403,'denied')
    app=FastAPI();app.include_router(module.router);app.dependency_overrides[authorized_store]=denied
    client=TestClient(app)
    for path in ['profiles/F1','entities/N2','measurements','relationships?subject_id=N1']:
        assert client.get('/api/v1/drawing-gis/'+path).status_code==403

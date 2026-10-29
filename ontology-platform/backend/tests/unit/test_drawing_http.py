from types import SimpleNamespace
import importlib.util
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from test_drawing_package import package


def test_router_module_exists():
    assert importlib.util.find_spec('lzo.gis.drawing_router') is not None


def client(tmp_path):
    from lzo.gis.drawing_router import router, authorized_store
    from lzo.gis.drawing_store import DrawingStore
    from lzo.gis.drawing_package import seal_package
    store=DrawingStore(create_engine('sqlite:///'+str(tmp_path/'http.db')));store.initialize_offline();store.import_package(seal_package(package()))
    app=FastAPI();app.include_router(router);app.dependency_overrides[authorized_store]=lambda:store
    return TestClient(app)


def test_http_errors_and_coordinate_contract(tmp_path):
    c=client(tmp_path)
    result=c.get('/api/v1/drawing-gis/features').json()
    assert result['type']=='DrawingFeaturePage' and result['georeferenced'] is False
    assert c.get('/api/v1/drawing-gis/drawings').json()['items'][0]['drawing_id']=='pdf-01'
    assert c.get('/api/v1/drawing-gis/features/F1').json()['entity_id']=='9f450d79-3c82-45cb-bd6b-1721b7924db1'
    assert c.get('/api/v1/drawing-gis/features',params={'bbox':'nan,0,1,1'}).status_code==422
    assert c.get('/api/v1/drawing-gis/features',params={'limit':1001}).status_code==422
    assert c.get('/api/v1/drawing-gis/features/missing').status_code==404
    assert c.get('/api/v1/drawing-gis/coverage').headers['cache-control']=='private, no-store'


def test_permission_denied_before_store_access(monkeypatch):
    from lzo.gis.drawing_router import authorized_store
    from lzo.errors import Forbidden
    from lzo.auth import permissions
    monkeypatch.setattr(permissions,'require_permission',lambda *a,**k:(_ for _ in ()).throw(Forbidden('FORBIDDEN','denied')))
    auth=SimpleNamespace(actor=object(),uow=object())
    with pytest.raises(Forbidden):authorized_store(SimpleNamespace(app=None),auth)

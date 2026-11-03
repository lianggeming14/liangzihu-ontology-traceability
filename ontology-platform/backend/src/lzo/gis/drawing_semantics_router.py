"""Authorized drawing read-model queries; no writes to formal semantic core."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from .drawing_router import authorized_store
from .drawing_store import DrawingStore
from .drawing_semantics_store import DrawingSemanticsStore, SourcePackageMismatch

router = APIRouter(prefix='/api/v1/drawing-gis', tags=['Drawing semantics'])


def authorized_semantics_store(store: DrawingStore = Depends(authorized_store)):
    return DrawingSemanticsStore(store.engine, store.dataset_id)


def read(response, call):
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return call()
    except SourcePackageMismatch as exc:
        raise HTTPException(409, str(exc), headers={'Cache-Control':'private, no-store'}) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(503, 'Drawing semantics storage unavailable or migration required') from None


@router.get('/profiles/{identifier}', operation_id='getDrawingSemanticProfile')
def profile(identifier: str, response: Response, store: DrawingSemanticsStore = Depends(authorized_semantics_store)):
    return read(response, lambda: store.profile(identifier))


@router.get('/entities/{identifier}', operation_id='getDrawingSemanticEntity')
def entity(identifier: str, response: Response, store: DrawingSemanticsStore = Depends(authorized_semantics_store)):
    return read(response, lambda: store.entity(identifier))


@router.get('/measurements', operation_id='listDrawingMeasurements')
def measurements(response: Response, kind: str | None = None, subject_id: str | None = None,
                 drawing_id: str | None = None, limit: int = Query(100, ge=1, le=1000),
                 cursor: str | None = None, store: DrawingSemanticsStore = Depends(authorized_semantics_store)):
    return read(response, lambda: store.measurements(kind=kind, subject_id=subject_id,
                drawing_id=drawing_id, limit=limit, cursor=cursor))


@router.get('/relationships', operation_id='listDrawingRelationships')
def relationships(response: Response, subject_id: str, limit: int = Query(100, ge=1, le=1000),
                  cursor: str | None = None, store: DrawingSemanticsStore = Depends(authorized_semantics_store)):
    return read(response, lambda: store.relationships(subject_id=subject_id, limit=limit, cursor=cursor))

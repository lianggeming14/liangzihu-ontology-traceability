"""Paper GIS endpoints. Whole drawings require explicit global internal visibility."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from lzo.auth.router import AuthRequest, authenticated
from lzo.contracts import ResourceScope
from .drawing_store import DrawingStore
from .drawing_schemas import DrawingFeature, DrawingFeaturePage, DrawingDirectory, DrawingAnnotationPage

router=APIRouter(prefix='/api/v1/drawing-gis',tags=['Drawing GIS'])


def authorized_store(request:Request,auth:AuthRequest=Depends(authenticated)):
    from lzo.auth.permissions import require_permission
    # Complete plans contain several entities and unbound labels. A per-object
    # grant must not accidentally disclose its neighbours or project totals.
    require_permission(auth.actor,'view',ResourceScope(None,None,(),'internal'),uow=auth.uow)
    if request.app.state.settings.storage_mode!='split':
        raise HTTPException(409,'Drawing GIS requires split storage')
    return DrawingStore(request.app.state.storage_registry.engine('gis'))


def read(response,call):
    response.headers['Cache-Control']='private, no-store'
    try:return call()
    except LookupError as e:raise HTTPException(404,str(e)) from None
    except ValueError as e:raise HTTPException(422,str(e)) from None
    except SQLAlchemyError:raise HTTPException(503,'Drawing GIS storage unavailable or migration required') from None


@router.get('/drawings',operation_id='listDrawingSheets',response_model=DrawingDirectory)
def list_drawings(response:Response,store:DrawingStore=Depends(authorized_store)):
    return read(response,store.drawings)


@router.get('/coverage',operation_id='getDrawingCoverage')
def coverage(response:Response,store:DrawingStore=Depends(authorized_store)):
    return read(response,store.coverage)


@router.get('/features',operation_id='listDrawingFeatures',response_model=DrawingFeaturePage)
def features(response:Response,drawing_id:str|None=None,kind:str|None=None,bbox:str|None=None,
             limit:int=Query(100,ge=1,le=1000),cursor:str|None=None,store:DrawingStore=Depends(authorized_store)):
    return read(response,lambda:store.features(drawing_id=drawing_id,kind=kind,bbox=bbox,limit=limit,cursor=cursor))


@router.get('/features/{identifier}',operation_id='getDrawingFeature',response_model=DrawingFeature)
def feature(identifier:str,response:Response,store:DrawingStore=Depends(authorized_store)):
    return read(response,lambda:store.feature(identifier))


@router.get('/annotations',operation_id='listDrawingAnnotations',response_model=DrawingAnnotationPage)
def annotations(response:Response,drawing_id:str|None=None,limit:int=Query(100,ge=1,le=1000),
                cursor:str|None=None,store:DrawingStore=Depends(authorized_store)):
    return read(response,lambda:store.annotations(drawing_id=drawing_id,limit=limit,cursor=cursor))

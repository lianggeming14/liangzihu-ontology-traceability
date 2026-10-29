"""Map client contracts explicitly exclude surveyed coordinate claims."""
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class DrawingFeature(BaseModel):
    model_config=ConfigDict(extra='allow')
    feature_id:str
    entity_id:UUID|None
    drawing_id:str
    kind:str
    label:str
    geometry:dict[str,Any]
    data_nature:Literal['imported_unverified']
    area_m2:None=None
    length_m:None=None


class DrawingFeaturePage(BaseModel):
    type:Literal['DrawingFeaturePage']='DrawingFeaturePage'
    dataset_id:str
    version:int
    content_sha256:str
    coordinate_system:Literal['PDF_LANDSCAPE_LOCAL']='PDF_LANDSCAPE_LOCAL'
    coordinate_units:Literal['pt']='pt'
    georeferenced:Literal[False]=False
    bbox_filter:str
    features:list[DrawingFeature]
    next_cursor:str|None


class DrawingDirectory(BaseModel):
    dataset_id:str
    version:int
    content_sha256:str
    items:list[dict[str,Any]]


class DrawingAnnotationPage(DrawingDirectory):
    next_cursor:str|None

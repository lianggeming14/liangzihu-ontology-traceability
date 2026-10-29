"""Validated immutable drawing evidence. Paper coordinates never imply WGS84."""
import copy
import hashlib
import json
import math
import re
from uuid import UUID


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(package):
    return hashlib.sha256(canonical({k:v for k,v in package.items() if k!='content_sha256'}).encode()).hexdigest()


def validate_package(package, *, verify_digest=True):
    if package.get('schema_version')!='drawing-gis/1':raise ValueError('Unsupported drawing package')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,99}',package.get('dataset_id','')):raise ValueError('Invalid dataset id')
    if type(package.get('version')) is not int or package['version']<1:raise ValueError('Invalid version')
    canonical(package) # Reject nonfinite values anywhere, including nested evidence.
    drawings={}
    for d in package['drawings']:
        key=d['drawing_id']
        if key in drawings or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',key):raise ValueError('Duplicate/invalid drawing')
        if not re.fullmatch('[0-9a-f]{64}',d['source_sha256']):raise ValueError('Missing source digest')
        if d.get('coordinate_system')!='PDF_LANDSCAPE_LOCAL' or d.get('coordinate_units')!='pt' or d.get('georeferenced') is not False:
            raise ValueError('Paper coordinate policy required')
        size=d['page_size_pt']
        if len(size)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in size):raise ValueError('Invalid page size')
        drawings[key]=d
    if not drawings:raise ValueError('No drawings')
    seen=set()
    for feature in package['features']:
        fid=feature['feature_id']
        if not isinstance(fid,str) or not fid or len(fid)>200 or fid in seen:raise ValueError('Duplicate/invalid feature')
        seen.add(fid)
        if not isinstance(feature.get('label'),str) or not isinstance(feature.get('kind'),str) or not feature['kind']:
            raise ValueError('Feature label and kind are required strings')
        if 'entity_id' not in feature or (feature['entity_id'] is not None and not isinstance(feature['entity_id'],str)):
            raise ValueError('Explicit entity_id UUID or null required')
        if feature.get('data_nature')!='imported_unverified':raise ValueError('Drawing evidence must not mix synthetic/verified facts')
        if feature.get('area_m2') is not None or feature.get('length_m') is not None:raise ValueError('Paper geometry cannot claim ground metrics')
        if feature['entity_id'] is not None and feature['entity_id']!=str(UUID(feature['entity_id'])):
            raise ValueError('Canonical lowercase hyphenated UUID required')
        drawing=drawings.get(feature['drawing_id'])
        if drawing is None:raise ValueError('Unknown drawing')
        geometry=feature['geometry'];kind=geometry.get('type');coords=geometry.get('coordinates')
        if kind=='Point':points=[coords]
        elif kind=='LineString':
            points=coords
            if not isinstance(points,list) or len(points)<2:raise ValueError('Invalid line')
        elif kind=='Polygon':
            if not isinstance(coords,list) or not coords:raise ValueError('Invalid polygon')
            points=[]
            for ring in coords:
                if len(ring)<4 or ring[0]!=ring[-1]:raise ValueError('Unclosed polygon')
                points.extend(ring)
        else:raise ValueError('Unsupported paper geometry')
        if len(points)>100000:raise ValueError('Geometry too large')
        for point in points:
            if not isinstance(point,list) or len(point)!=2:raise ValueError('Two dimensional geometry required')
            if any(type(x) not in (int,float) or not math.isfinite(x) for x in point):raise ValueError('Nonfinite coordinate')
            if any(x<0 or x>maximum for x,maximum in zip(point,drawing['page_size_pt'])):raise ValueError('Coordinate outside page')
    seen=set()
    for a in package['annotations']:
        aid=a['annotation_id']
        if not isinstance(aid,str) or not aid or len(aid)>200 or aid in seen:raise ValueError('Duplicate/invalid annotation')
        seen.add(aid)
        if a['drawing_id'] not in drawings:raise ValueError('Unknown annotation drawing')
    if not isinstance(package.get('coverage'),dict):raise ValueError('Coverage required')
    if verify_digest and package.get('content_sha256')!=digest(package):raise ValueError('Package digest mismatch')
    return package


def seal_package(package):
    value=copy.deepcopy(package)
    validate_package(value,verify_digest=False)
    value['content_sha256']=digest(value)
    return value


def bounds(geometry):
    coords=geometry['coordinates']
    points=[coords] if geometry['type']=='Point' else coords if geometry['type']=='LineString' else [p for ring in coords for p in ring]
    return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]

"""Version-pinned drawing evidence repository; import is one transaction."""
import base64
import json
import math
from sqlalchemy import Column, Float, Integer, JSON, MetaData, String, Table, and_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from .drawing_package import bounds, canonical, validate_package

metadata=MetaData()
json_type=JSON().with_variant(JSONB(),'postgresql')


def keys():
    return [Column('dataset_id',String(100),primary_key=True),Column('version',Integer,primary_key=True)]


datasets=Table('gis_drawing_datasets',metadata,*keys(),Column('content_sha256',String(64),nullable=False),Column('payload',json_type,nullable=False))
drawings=Table('gis_drawings',metadata,*keys(),Column('drawing_id',String(100),primary_key=True),Column('payload',json_type,nullable=False))
features=Table('gis_drawing_features',metadata,*keys(),Column('feature_id',String(200),primary_key=True),
    Column('drawing_id',String(100),nullable=False,index=True),Column('entity_id',String(36),index=True),
    Column('kind',String(100),nullable=False,index=True),*[Column(k,Float,nullable=False) for k in ('min_x','min_y','max_x','max_y')],Column('payload',json_type,nullable=False))
annotations=Table('gis_drawing_annotations',metadata,*keys(),Column('annotation_id',String(200),primary_key=True),
    Column('drawing_id',String(100),nullable=False,index=True),Column('payload',json_type,nullable=False))


class DrawingStore:
    def __init__(self,engine,dataset_id='liangzihu-asbuilt-2026'):
        self.engine=engine;self.dataset_id=dataset_id

    def initialize_offline(self):
        if self.engine.dialect.name!='sqlite':raise ValueError('Use reviewed GIS migration for PostgreSQL')
        metadata.create_all(self.engine)

    def import_package(self,package):
        validate_package(package)
        if package['dataset_id']!=self.dataset_id:raise ValueError('Dataset mismatch')
        key={'dataset_id':self.dataset_id,'version':package['version']}
        with self.engine.begin() as c:
            if self.engine.dialect.name=='postgresql':
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{'key':'drawing-gis:'+self.dataset_id})
            previous=c.execute(select(datasets.c.content_sha256).where(self._where(datasets,key))).scalar_one_or_none()
            if previous:
                if previous!=package['content_sha256']:raise ValueError('Immutable dataset version conflict')
                return {'status':'unchanged','version':key['version'],'content_sha256':previous}
            c.execute(datasets.insert().values(**key,content_sha256=package['content_sha256'],payload={k:v for k,v in package.items() if k not in ('features','annotations','drawings')}))
            c.execute(drawings.insert(),[dict(**key,drawing_id=d['drawing_id'],payload=d) for d in package['drawings']])
            for f in package['features']:
                c.execute(features.insert().values(**key,feature_id=f['feature_id'],drawing_id=f['drawing_id'],entity_id=f.get('entity_id'),kind=f['kind'],payload=f,**dict(zip(('min_x','min_y','max_x','max_y'),bounds(f['geometry'])))))
                if self.engine.dialect.name=='postgresql':
                    c.execute(text('''UPDATE gis_drawing_features SET paper_geom=public.ST_SetSRID(public.ST_GeomFromGeoJSON(:geo),0)
                        WHERE dataset_id=:dataset_id AND version=:version AND feature_id=:id'''),dict(**key,id=f['feature_id'],geo=json.dumps(f['geometry'])))
            for start in range(0,len(package['annotations']),500):
                c.execute(annotations.insert(),[dict(**key,annotation_id=a['annotation_id'],drawing_id=a['drawing_id'],payload=a) for a in package['annotations'][start:start+500]])
        return {'status':'imported','version':key['version'],'content_sha256':package['content_sha256'],'features':len(package['features']),'annotations':len(package['annotations'])}

    @staticmethod
    def _where(table,key):return and_(*(table.c[k]==v for k,v in key.items()))

    def _head(self,c):
        head=c.execute(select(datasets).where(datasets.c.dataset_id==self.dataset_id).order_by(datasets.c.version.desc()).limit(1)).mappings().first()
        if head is None:raise LookupError('Drawing dataset not installed')
        return head

    def drawings(self):
        with self.engine.connect() as c:
            head=self._head(c);key={'dataset_id':self.dataset_id,'version':head['version']}
            items=c.execute(select(drawings.c.payload).where(self._where(drawings,key)).order_by(drawings.c.drawing_id)).scalars().all()
            return {'dataset_id':self.dataset_id,'version':head['version'],'content_sha256':head['content_sha256'],'items':items}

    def coverage(self):
        with self.engine.connect() as c:
            head=self._head(c)
            return {**head['payload']['coverage'],'dataset_id':self.dataset_id,'version':head['version'],'content_sha256':head['content_sha256']}

    def feature(self,identifier):
        with self.engine.connect() as c:
            head=self._head(c);key={'dataset_id':self.dataset_id,'version':head['version']}
            rows=c.execute(select(features.c.payload).where(self._where(features,key),
                (features.c.feature_id==identifier)|(features.c.entity_id==identifier))).scalars().all()
            if not rows:raise LookupError('Feature not found')
            if len(rows)!=1:raise ValueError('Multiple representations; query by representation_id')
            return rows[0]

    def features(self,*,drawing_id=None,kind=None,bbox=None,limit=100,cursor=None):
        return self._page(features,'feature_id',drawing_id,kind,bbox,limit,cursor)

    def annotations(self,*,drawing_id=None,limit=100,cursor=None):
        return self._page(annotations,'annotation_id',drawing_id,None,None,limit,cursor)

    def _page(self,table,id_column,drawing_id,kind,bbox,limit,cursor):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid limit')
        boundary=None
        if bbox is not None:
            try:
                boundary=[float(x) for x in bbox.split(',')]
                if len(boundary)!=4 or not all(math.isfinite(v) for v in boundary) or boundary[0]>boundary[2] or boundary[1]>boundary[3]:raise ValueError()
            except (ValueError,AttributeError):raise ValueError('Invalid bbox') from None
        filters=[table.name,drawing_id,kind,boundary]
        with self.engine.connect() as c:
            head=self._head(c);key={'dataset_id':self.dataset_id,'version':head['version']}
            if drawing_id is not None and c.execute(select(drawings.c.drawing_id).where(self._where(drawings,key),drawings.c.drawing_id==drawing_id)).first() is None:
                raise LookupError('Drawing not found')
            q=select(table).where(self._where(table,key)).order_by(table.c[id_column]).limit(limit+1)
            if drawing_id:q=q.where(table.c.drawing_id==drawing_id)
            if kind:q=q.where(table.c.kind==kind)
            if boundary:
                q=q.where(table.c.max_x>=boundary[0],table.c.max_y>=boundary[1],table.c.min_x<=boundary[2],table.c.min_y<=boundary[3])
            if cursor:
                try:
                    if len(cursor)>4096:raise ValueError()
                    parsed=json.loads(base64.b64decode(cursor+'='*(-len(cursor)%4),altchars=b'-_',validate=True))
                    if not isinstance(parsed,dict) or set(parsed)!={'sha','filters','after'} or parsed['filters']!=filters or not isinstance(parsed['after'],str):raise ValueError()
                except Exception:raise ValueError('Invalid cursor') from None
                if parsed['sha']!=head['content_sha256']:raise ValueError('Dataset cursor stale; restart pagination')
                q=q.where(table.c[id_column]>parsed['after'])
            rows=c.execute(q).mappings().all();next_cursor=None
            if len(rows)>limit:
                data={'sha':head['content_sha256'],'filters':filters,'after':rows[limit-1][id_column]}
                next_cursor=base64.urlsafe_b64encode(canonical(data).encode()).decode().rstrip('=')
            result={'dataset_id':self.dataset_id,'version':head['version'],'content_sha256':head['content_sha256'],'next_cursor':next_cursor}
            if table is features:result.update(type='DrawingFeaturePage',coordinate_system='PDF_LANDSCAPE_LOCAL',coordinate_units='pt',georeferenced=False,
                bbox_filter='paper_bbox_intersection_not_exact_geometry',features=[r['payload'] for r in rows[:limit]])
            else:result['items']=[r['payload'] for r in rows[:limit]]
            return result

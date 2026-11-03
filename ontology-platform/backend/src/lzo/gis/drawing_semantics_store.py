"""Immutable drawing semantics read model in GIS, separate from formal core."""
import base64
import hashlib
import json
import re

from sqlalchemy import Column, Index, JSON, MetaData, String, Table, and_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from .drawing_package import canonical
from .drawing_store import datasets as source_datasets

metadata = MetaData()
json_type = JSON().with_variant(JSONB(), 'postgresql')


def keys():
    return [Column('dataset_id', String(100), primary_key=True),
            Column('version', String(100), primary_key=True)]


datasets = Table('gis_drawing_semantics_datasets', metadata, *keys(),
    Column('content_sha256', String(64), nullable=False),
    Column('source_package_sha256', String(64), nullable=False), Column('payload', json_type, nullable=False))
heads = Table('gis_drawing_semantics_heads', metadata,
    Column('dataset_id', String(100), primary_key=True), Column('version', String(100), nullable=False))
nodes = Table('gis_drawing_semantics_nodes', metadata, *keys(),
    Column('node_id', String(200), primary_key=True), Column('payload', json_type, nullable=False))
edges = Table('gis_drawing_semantics_edges', metadata, *keys(),
    Column('edge_id', String(100), primary_key=True), Column('subject_id', String(200), nullable=False),
    Column('object_id', String(200), nullable=False), Column('payload', json_type, nullable=False))
profiles = Table('gis_drawing_semantics_profiles', metadata, *keys(),
    Column('feature_id', String(200), primary_key=True), Column('entity_id', String(200), nullable=False),
    Column('drawing_id', String(100), nullable=False), Column('payload', json_type, nullable=False))
measurements = Table('gis_drawing_semantics_measurements', metadata, *keys(),
    Column('measurement_id', String(200), primary_key=True), Column('subject_id', String(200), nullable=False),
    Column('drawing_id', String(100), nullable=False), Column('kind', String(200), nullable=False),
    Column('payload', json_type, nullable=False))
for name in ('kind', 'subject_id', 'drawing_id'):
    Index('gis_drawing_measurement_' + name, measurements.c.dataset_id, measurements.c.version,
          measurements.c[name], measurements.c.measurement_id)
Index('gis_drawing_semantics_edges_subject', edges.c.dataset_id, edges.c.version, edges.c.subject_id, edges.c.edge_id)
Index('gis_drawing_semantics_profiles_entity', profiles.c.dataset_id, profiles.c.version, profiles.c.entity_id)


class SourcePackageMismatch(ValueError):
    """The installed read model does not describe the current drawing package."""


def _string(value, name, maximum=200):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError('Invalid ' + name)
    return value


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('schema_version') != 'drawing-semantics/1':
        raise ValueError('Unsupported drawing semantics bundle')
    canonical(bundle)
    _string(bundle.get('dataset_id'), 'dataset_id', 100)
    _string(bundle.get('version'), 'version', 100)
    for name in ('content_sha256', 'source_package_sha256'):
        if not isinstance(bundle.get(name), str) or not re.fullmatch('[0-9a-f]{64}', bundle[name]):
            raise ValueError('Invalid ' + name)
    digest = hashlib.sha256(canonical({k:v for k,v in bundle.items() if k != 'content_sha256'}).encode()).hexdigest()
    if digest != bundle['content_sha256']:
        raise ValueError('Bundle digest mismatch')
    for name in ('drawings','nodes','edges','profiles','measurements'):
        if not isinstance(bundle.get(name), list):
            raise ValueError('Missing list ' + name)

    def identifiers(items, key, name):
        values = [_string(item.get(key), name) for item in items]
        if len(set(values)) != len(values):
            raise ValueError('Duplicate ' + name)
        return set(values)

    drawing_ids = identifiers(bundle['drawings'], 'id', 'drawing')
    node_ids = identifiers(bundle['nodes'], 'id', 'node')
    measurement_ids = identifiers(bundle['measurements'], 'id', 'measurement')
    identifiers(bundle['profiles'], 'feature_id', 'profile')
    for node in bundle['nodes']:
        _string(node.get('class_iri'), 'class_iri', 2048)
        if not isinstance(node.get('label'), str) or not isinstance(node.get('data_nature'), str):
            raise ValueError('Node label/data_nature required')
        if not isinstance(node.get('source_drawing_ids'), list) or not set(node['source_drawing_ids']) <= drawing_ids:
            raise ValueError('Unknown node drawing')
        if not isinstance(node.get('properties'), list):
            raise ValueError('Node properties required')
        for prop in node['properties']:
            _string(prop.get('predicate_iri'), 'predicate_iri', 2048)
            term = prop.get('term', {})
            if term.get('kind') not in ('iri','literal') or 'value' not in term:
                raise ValueError('Invalid property term')
            if not isinstance(prop.get('evidence_ids'), list):
                raise ValueError('Property evidence_ids required')
    for edge in bundle['edges']:
        if edge.get('subject_id') not in node_ids or edge.get('object_id') not in node_ids:
            raise ValueError('Unknown edge node')
        _string(edge.get('predicate_iri'), 'predicate_iri', 2048)
        if not isinstance(edge.get('evidence_ids'), list) or 'derivation' not in edge:
            raise ValueError('Edge evidence/derivation required')
    for row in bundle['measurements']:
        if row.get('subject_id') not in node_ids or row.get('drawing_id') not in drawing_ids:
            raise ValueError('Unknown measurement subject/drawing')
        _string(row.get('kind'), 'measurement kind')
        for key in ('value','unit','si_value','si_unit','status','source_record','evidence_ids','aggregation_policy'):
            if key not in row:
                raise ValueError('Missing measurement ' + key)
        if row['si_value'] is not None and not isinstance(row['si_value'], str):
            raise ValueError('si_value must be canonical decimal string or null')
    for profile in bundle['profiles']:
        if profile.get('entity_id') not in node_ids or profile.get('drawing_id') not in drawing_ids:
            raise ValueError('Unknown profile entity/drawing')
        if not isinstance(profile.get('measurement_ids'), list) or not set(profile['measurement_ids']) <= measurement_ids:
            raise ValueError('Unknown profile measurement')
    return bundle


class DrawingSemanticsStore:
    def __init__(self, engine, dataset_id='liangzihu-asbuilt-2026'):
        self.engine, self.dataset_id = engine, dataset_id

    def initialize_offline(self):
        if self.engine.dialect.name != 'sqlite':
            raise ValueError('Use reviewed GIS migration for PostgreSQL')
        metadata.create_all(self.engine)

    @staticmethod
    def _where(table, key):
        return and_(*(table.c[k] == v for k,v in key.items()))

    def _source(self, connection, digest):
        current = connection.execute(select(source_datasets.c.content_sha256)
            .where(source_datasets.c.dataset_id == self.dataset_id)
            .order_by(source_datasets.c.version.desc()).limit(1)).scalar_one_or_none()
        if current != digest:
            raise SourcePackageMismatch('Drawing semantics source package mismatch; import matching current source')

    def import_bundle(self, bundle):
        validate_bundle(bundle)
        if bundle['dataset_id'] != self.dataset_id:
            raise ValueError('Dataset mismatch')
        key = {'dataset_id': self.dataset_id, 'version': bundle['version']}
        with self.engine.begin() as connection:
            if self.engine.dialect.name == 'postgresql':
                # Same lock as source import: binding is checked and committed
                # while the current source package cannot change underneath us.
                connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                                   {'key':'drawing-gis:' + self.dataset_id})
            self._source(connection, bundle['source_package_sha256'])
            old = connection.execute(select(datasets.c.content_sha256).where(self._where(datasets,key))).scalar_one_or_none()
            if old:
                if old != bundle['content_sha256']:
                    raise ValueError('Immutable semantics version conflict')
                return {'status':'unchanged', **key, 'content_sha256':old}
            connection.execute(datasets.insert().values(**key, content_sha256=bundle['content_sha256'],
                source_package_sha256=bundle['source_package_sha256'],
                payload={k:v for k,v in bundle.items() if k not in ('nodes','edges','profiles','measurements')}))
            collections = [
                (nodes, [dict(**key,node_id=n['id'],payload=n) for n in bundle['nodes']]),
                (edges, [dict(**key,edge_id=f'{i:012d}',subject_id=e['subject_id'],object_id=e['object_id'],payload=e)
                         for i,e in enumerate(bundle['edges'])]),
                (profiles, [dict(**key,feature_id=p['feature_id'],entity_id=p['entity_id'],drawing_id=p['drawing_id'],payload=p)
                            for p in bundle['profiles']]),
                (measurements, [dict(**key,measurement_id=m['id'],subject_id=m['subject_id'],drawing_id=m['drawing_id'],kind=m['kind'],payload=m)
                                for m in bundle['measurements']])]
            for table, rows in collections:
                for start in range(0,len(rows),500):
                    connection.execute(table.insert(), rows[start:start+500])
            existing = connection.execute(select(heads.c.version).where(heads.c.dataset_id==self.dataset_id)).scalar_one_or_none()
            if existing is None:
                connection.execute(heads.insert().values(**key))
            else:
                connection.execute(heads.update().where(heads.c.dataset_id==self.dataset_id).values(version=key['version']))
        return {'status':'imported',**key,'content_sha256':bundle['content_sha256'],
                'source_package_sha256':bundle['source_package_sha256'],
                'nodes':len(bundle['nodes']),'measurements':len(bundle['measurements']),
                'profiles':len(bundle['profiles']),'formal_core_imported':None,
                'formal_core_import_status':'not_checked_by_gis_read_model'}

    def _head(self, connection):
        if self.engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock_shared(hashtextextended(:key,0))'),
                               {'key':'drawing-gis:' + self.dataset_id})
        row = connection.execute(select(datasets).join(heads,
            (datasets.c.dataset_id==heads.c.dataset_id)&(datasets.c.version==heads.c.version))
            .where(heads.c.dataset_id==self.dataset_id)).mappings().first()
        if row is None:
            raise LookupError('Drawing semantics not installed')
        self._source(connection,row['source_package_sha256'])
        return row

    def _envelope(self, head):
        return {'dataset_id':self.dataset_id,'version':head['version'],
                'content_sha256':head['content_sha256'],'source_package_sha256':head['source_package_sha256'],
                'storage_role':'gis_read_model','formal_core_imported':None,
                'formal_core_import_status':'not_checked_by_gis_read_model'}

    def entity(self, identifier):
        with self.engine.connect() as connection:
            head=self._head(connection);key={'dataset_id':self.dataset_id,'version':head['version']}
            row=connection.execute(select(nodes.c.payload).where(self._where(nodes,key),
                nodes.c.node_id==identifier)).scalar_one_or_none()
            if row is None:raise LookupError('Entity not found')
            return {**self._envelope(head),'item':row}

    def profile(self, identifier):
        with self.engine.connect() as connection:
            head=self._head(connection);key={'dataset_id':self.dataset_id,'version':head['version']}
            rows=connection.execute(select(profiles.c.payload).where(self._where(profiles,key),
                (profiles.c.feature_id==identifier)|(profiles.c.entity_id==identifier))).scalars().all()
            if not rows:raise LookupError('Profile not found')
            if len(rows)>1:raise ValueError('Multiple representations; query by feature_id')
            return {**self._envelope(head),'item':rows[0]}

    def measurements(self, *, kind=None, subject_id=None, drawing_id=None, limit=100, cursor=None):
        return self._page(measurements,'measurement_id',kind=kind,subject_id=subject_id,drawing_id=drawing_id,limit=limit,cursor=cursor)

    def relationships(self, *, subject_id, limit=100, cursor=None):
        _string(subject_id,'subject_id')
        return self._page(edges,'edge_id',subject_id=subject_id,limit=limit,cursor=cursor)

    def _page(self, table, id_column, *, kind=None, subject_id=None, drawing_id=None, limit=100, cursor=None):
        if type(limit) is not int or not 1<=limit<=1000:
            raise ValueError('Invalid limit')
        filters={'table':table.name,'kind':kind,'subject_id':subject_id,'drawing_id':drawing_id}
        with self.engine.connect() as connection:
            head=self._head(connection);key={'dataset_id':self.dataset_id,'version':head['version']}
            query=select(table).where(self._where(table,key)).order_by(table.c[id_column]).limit(limit+1)
            for column,value in [('kind',kind),('subject_id',subject_id),('drawing_id',drawing_id)]:
                if value is not None:query=query.where(table.c[column]==value)
            if cursor:
                try:
                    if len(cursor)>4096:raise ValueError()
                    parsed=json.loads(base64.b64decode(cursor+'='*(-len(cursor)%4),altchars=b'-_',validate=True))
                    if set(parsed)!={'sha','filters','after'} or parsed['filters']!=filters or not isinstance(parsed['after'],str):
                        raise ValueError()
                except Exception:raise ValueError('Invalid cursor') from None
                if parsed['sha']!=head['content_sha256']:raise ValueError('Semantics cursor stale; restart pagination')
                query=query.where(table.c[id_column]>parsed['after'])
            rows=connection.execute(query).mappings().all();next_cursor=None
            if len(rows)>limit:
                data={'sha':head['content_sha256'],'filters':filters,'after':rows[limit-1][id_column]}
                next_cursor=base64.urlsafe_b64encode(canonical(data).encode()).decode().rstrip('=')
            return {**self._envelope(head),'items':[r['payload'] for r in rows[:limit]],'next_cursor':next_cursor}

"""Synthetic fish features over ordinary evidence, spatial assets and GIS delivery.

Canonical object UUIDs come from the governed identity registry. The deterministic
UUID below identifies a spatial asset, never a new or matched ontology object.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

CONTRACT = 'fish-gis-feature/1'
ASSET_NAMESPACE = UUID('06ce94dd-91d6-4aaa-a847-c6c7c7ba9563')
SOURCE_PREFIX = 'urn:lzo:fish-l1:gis:'


class FishGeometryMetrics(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    geometry_area_m2: float | None
    geometry_perimeter_m: float | None
    geometry_length_m: float | None
    value_kind: Literal['derived_simulation']
    horizontal_datum: Literal['EPSG:4326']
    method: str
    normalization_method: str
    field_measurement: Literal[False]


class FishSpatialMeasurements(BaseModel):
    """Source decimals stay strings; unknown field measurements stay null."""
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    value_kind: Literal['scenario_assumption']
    source_area_m2: str | int | float | None = None
    source_area_mu: str | int | float | None = None
    source_mean_depth_m: str | int | float | None = None
    source_maximum_depth_m: str | int | float | None = None
    source_effective_volume_m3: str | int | float | None = None
    source_row_number: int | None = None
    source_name: str | None = None
    measured_area_m2: None = None
    measured_perimeter_m: None = None
    measured_mean_depth_m: None = None
    measured_maximum_depth_m: None = None
    missing_reason: str


class FishSpatialEntityBinding(BaseModel):
    model_config = ConfigDict(extra='allow')
    table: str | None
    pk: str | None
    resource_id: UUID | None
    binding_status: Literal['bound', 'unresolved', 'layer_only']


class FishSpatialFeatureProperties(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    contract: Literal['fish-gis-feature/1']
    package_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    asset_id: UUID
    resource_id: UUID
    layer_id: str
    layer_name: str
    feature_id: str
    source_properties: dict[str, Any]
    entity: FishSpatialEntityBinding
    data_nature: Literal['synthetic']
    is_synthetic: Literal[True]
    not_for_navigation: Literal[True]
    source_crs: Literal['EPSG:4326']
    coordinate_order: Literal['longitude,latitude']
    captured_at: str
    accuracy_metres: None
    accuracy_status: Literal['not_surveyed_synthetic_layout']
    quality: Literal['display_only']
    measurements: FishSpatialMeasurements
    geometry_metrics: FishGeometryMetrics | None
    source_file: str
    source_file_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    layer_evidence_version_id: UUID


class FishSpatialFeature(BaseModel):
    model_config = ConfigDict(extra='allow')
    type: Literal['Feature']
    id: UUID
    geometry: dict[str, Any] = Field(description='Unmodified normalized GeoJSON geometry; longitude/latitude in EPSG:4326')
    properties: FishSpatialFeatureProperties


class FishFeatureCollection(BaseModel):
    model_config = ConfigDict(extra='allow')
    type: Literal['FeatureCollection']
    features: list[FishSpatialFeature]
    gis_status: Literal['current', 'pending', 'failed', 'unavailable']
    next_cursor: str | None
    data_nature: Literal['synthetic']
    not_for_navigation: Literal[True]


class FishObjectFeatureCollection(FishFeatureCollection):
    resource_id: UUID


class FishPondFeatureCollection(FishFeatureCollection):
    package_sha256: str = Field(pattern='^[0-9a-f]{64}$')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def canonical_binding_matches(key, package, table, pk):
    """FileParser serializes key_paths as an ordered JSON array, even for one key."""
    try:
        return json.loads(key) == [package + ':' + table + ':' + pk]
    except (ValueError, TypeError):
        return False


def validate_geometry(geometry):
    """Reject malformed coordinates before the authoritative PostGIS validity check."""
    kind = geometry.get('type')
    if kind not in {'Point', 'LineString', 'Polygon', 'MultiPoint', 'MultiLineString', 'MultiPolygon'}:
        raise ValueError('Unsupported fish geometry')
    count = 0
    def point(value):
        nonlocal count
        if (not isinstance(value, list) or len(value) != 2 or any(type(n) not in (int, float)
                or not math.isfinite(n) for n in value) or not -180 <= value[0] <= 180
                or not -90 <= value[1] <= 90):
            raise ValueError('Invalid EPSG:4326 coordinates')
        count += 1
        if count > 100000:
            raise ValueError('Fish geometry budget exceeded')
    def line(value, ring=False):
        if not isinstance(value, list) or len(value) < (4 if ring else 2):
            raise ValueError('Invalid fish line or polygon ring')
        for item in value:
            point(item)
        if ring and value[0] != value[-1]:
            raise ValueError('Unclosed fish polygon')
    def polygon(value):
        if not isinstance(value, list) or not value:
            raise ValueError('Empty fish polygon')
        for ring in value:
            line(ring, True)
    value = geometry.get('coordinates')
    if kind == 'Point':
        point(value)
    elif kind == 'LineString':
        line(value)
    elif kind == 'Polygon':
        polygon(value)
    else:
        if not isinstance(value, list) or not value:
            raise ValueError('Empty fish multi-geometry')
        for child in value:
            {'MultiPoint': point, 'MultiLineString': line, 'MultiPolygon': polygon}[kind](child)
    return geometry


def _asset_bytes(root, relative, expected, members):
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe fish spatial asset path')
    root = Path(root).resolve()
    local = root.joinpath(*path.parts).resolve()
    entry = members.get('output/' + path.as_posix())
    if not local.is_relative_to(root) or not entry or not local.is_file():
        raise ValueError('Fish spatial asset is outside verified inventory')
    data = local.read_bytes()
    if (hashlib.sha256(data).hexdigest() != expected or expected != entry['sha256']
            or len(data) != entry['bytes']):
        raise ValueError('Fish spatial asset hash mismatch')
    return data


def build_gis_plan(root, audit, identities=()):
    """Use an already verified PackageAudit; reread every asset against its manifest."""
    package = audit.manifest['archive_sha256']
    if not re.fullmatch('[0-9a-f]{64}', package):
        raise ValueError('Invalid package digest')
    identity = {}
    for row in identities:
        key = (row['table'], row['pk'])
        if key in identity:
            raise ValueError('duplicate canonical fish identity')
        identity[key] = str(UUID(row['resource_id']))
    members = {m['path']: m for m in audit.manifest['members']}
    if len(members) != len(audit.manifest['members']):
        raise ValueError('duplicate source inventory path')
    ponds = {r.pk: r for r in audit.rows.get('ponds', []) if r.status == 'accepted'}
    features, layers = [], []
    for item in audit.rows.get('spatial_layer_registry', []):
        if item.status != 'accepted':
            raise ValueError('Spatial registry row requires review: ' + item.pk)
        layer = item.normalized
        if layer['is_synthetic'] is not True or item.nature != 'synthetic':
            raise ValueError('Fish spatial layers must remain synthetic')
        if layer['crs'] != 'EPSG:4326' or layer['coordinate_order'] != 'longitude,latitude':
            raise ValueError('Fish spatial CRS or axis order differs')
        captured = datetime.fromisoformat(layer['captured_at'].replace('Z', '+00:00'))
        if captured.utcoffset() is None:
            raise ValueError('Spatial capture time requires a timezone')
        data = _asset_bytes(root, layer['relative_path'], layer['sha256'], members)
        layer_copy = {**layer, 'resource_id': identity.get(('spatial_layer_registry', item.pk)),
                      'row_number': item.row_number}
        layers.append(layer_copy)
        if layer['geometry_kind'] == 'raster':
            bounds = [float(v) for v in layer['bbox'].split(',')]
            if len(bounds) != 4 or not bounds[0] < bounds[2] or not bounds[1] < bounds[3]:
                raise ValueError('Invalid raster footprint')
            x1, y1, x2, y2 = bounds
            values = [{'type': 'Feature', 'id': 'raster:' + item.pk, 'geometry': {'type': 'Polygon',
                'coordinates': [[[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]]]}, 'properties': {
                'is_synthetic': True, 'origin_kind': 'synthetic_raster_coverage',
                'not_for_navigation': True, 'geometry_role': 'raster_coverage_not_pond_boundary'}}]
        else:
            document = json.loads(data)
            metadata = document.get('metadata', {})
            if (document.get('type') != 'FeatureCollection' or metadata.get('crs') != 'EPSG:4326'
                    or metadata.get('coordinate_order') != 'longitude,latitude'):
                raise ValueError('Fish GeoJSON metadata mismatch')
            values = document['features']
            if len(values) != layer['feature_count']:
                raise ValueError('Fish feature count mismatch')
        ids = set()
        for feature in values:
            fid = feature.get('id')
            props = feature.get('properties', {})
            if feature.get('type') != 'Feature' or not isinstance(fid, str) or not fid or fid in ids:
                raise ValueError('Invalid or duplicate fish feature identity')
            ids.add(fid)
            if props.get('is_synthetic') is not True or props.get('not_for_navigation') is not True:
                raise ValueError('Fish feature must remain synthetic and not for navigation')
            geometry = validate_geometry(feature['geometry'])
            table, pk = props.get('entity_table'), props.get('entity_id')
            if bool(table) != bool(pk):
                raise ValueError('Incomplete fish feature entity reference')
            entity_id = identity.get((table, pk)) if table else None
            resource_id = entity_id or layer_copy['resource_id']
            measurement = {'value_kind': 'scenario_assumption', 'measured_area_m2': None,
                'measured_perimeter_m': None, 'measured_mean_depth_m': None,
                'measured_maximum_depth_m': None, 'missing_reason': 'no_field_survey_in_synthetic_package'}
            if table == 'ponds':
                pond = ponds.get(pk)
                if pond is None or pond.nature != 'synthetic':
                    raise ValueError('Pond master row missing or not accepted synthetic data')
                if layer['layer_name'] == 'ponds' and pond.normalized['geometry_id'] != fid:
                    raise ValueError('Pond geometry ID does not match its explicit master reference')
                for name in ('area_m2', 'area_mu', 'mean_depth_m', 'maximum_depth_m', 'effective_volume_m3'):
                    value = pond.normalized.get(name)
                    if value is not None:
                        try:
                            if type(value) not in (str, int, float):
                                raise ValueError()
                            number = Decimal(str(value))
                            if not number.is_finite() or number < 0:
                                raise ValueError()
                        except (ValueError, InvalidOperation):
                            raise ValueError('Invalid source pond measurement: ' + name) from None
                    measurement['source_' + name] = value
                measurement['source_row_number'] = pond.row_number
                measurement['source_name'] = pond.normalized.get('name')
            asset_id = str(uuid5(ASSET_NAMESPACE, canonical([package, item.pk, fid])))
            features.append({'contract': CONTRACT, 'package_sha256': package, 'asset_id': asset_id,
                'resource_id': resource_id, 'layer_id': item.pk, 'layer_name': layer['layer_name'],
                'feature_id': fid, 'geometry': geometry, 'source_properties': props,
                'entity': {'table': table, 'pk': pk, 'resource_id': entity_id,
                    'binding_status': 'bound' if entity_id else 'unresolved' if table else 'layer_only'},
                'data_nature': 'synthetic', 'is_synthetic': True, 'not_for_navigation': True,
                'source_crs': 'EPSG:4326', 'coordinate_order': 'longitude,latitude',
                'captured_at': layer['captured_at'], 'accuracy_metres': None,
                'accuracy_status': 'not_surveyed_synthetic_layout', 'quality': 'display_only',
                'measurements': measurement, 'geometry_metrics': None,
                'source_file': layer['relative_path'], 'source_file_sha256': layer['sha256']})
    return {'contract': 'fish-gis-plan/1', 'package_sha256': package, 'data_nature': 'synthetic',
            'layers': layers, 'features': features, 'feature_count': len(features)}


def require_bound_ponds(plan):
    for feature in plan['features']:
        if feature['entity']['table'] == 'ponds' and feature['entity']['binding_status'] != 'bound':
            raise ValueError('Every pond feature requires its governed pond UUID')
        if feature['resource_id'] is None:
            raise ValueError('Fish feature has neither a canonical entity nor a layer container')


def required_identity_manifest(plan):
    """Public source metadata only; derive the exact feature-owner requirements."""
    from collections import Counter
    grouped = {}
    for feature in plan['features']:
        entity = feature['entity']
        key = ((entity['table'], entity['pk']) if entity['table']
               else ('spatial_layer_registry', feature['layer_id']))
        grouped.setdefault(key, []).append({'layer_id':feature['layer_id'],
            'feature_id':feature['feature_id'], 'source_file':feature['source_file'],
            'source_file_sha256':feature['source_file_sha256'],
            'field_provenance':['properties.entity_table','properties.entity_id'] if entity['table']
                else ['spatial_layer_registry.id', 'spatial_layer_registry.relative_path'],
            'binding_kind':'entity' if entity['table'] else 'layer_container'})
    identities = [{'table':table, 'pk':pk} for table,pk in sorted(grouped)]
    requirements = [{**identity, 'feature_refs':sorted(grouped[identity['table'],identity['pk']],
        key=lambda value:(value['layer_id'],value['feature_id']))} for identity in identities]
    return {'contract':'fish-l1-identity-selection-v1', 'package_sha256':plan['package_sha256'],
        'data_nature':'synthetic', 'purpose':'GIS feature owners only; not completion of all entity ingestion',
        'identity_count':len(identities), 'feature_count':len(plan['features']),
        'table_counts':dict(sorted(Counter(value['table'] for value in identities).items())),
        'identities':identities, 'requirements':requirements,
        'identities_sha256':hashlib.sha256(canonical(identities).encode('utf-8')).hexdigest(),
        'requirements_sha256':hashlib.sha256(canonical(requirements).encode('utf-8')).hexdigest()}


def required_identity_bindings(plan):
    """All explicit feature entities must bind; a layer is not their substitute."""
    result = {}
    for feature in plan['features']:
        entity = feature['entity']
        if entity['table']:
            key = (entity['table'], entity['pk'])
            if (entity['binding_status'] != 'bound' or not entity['resource_id']
                    or feature['resource_id'] != entity['resource_id']):
                raise ValueError('Every ' + entity['table'] + ' feature requires its governed UUID')
        else:
            key = ('spatial_layer_registry', feature['layer_id'])
        if not feature['resource_id']:
            raise ValueError('Fish feature requires its governed layer UUID')
        identifier = str(UUID(feature['resource_id']))
        if key in result and result[key] != identifier:
            raise ValueError('Conflicting GIS identity binding')
        result[key] = identifier
    return result


def verify_required_identities(uow, actor, plan):
    """Current PG identity/object/source proof for this finite GIS stage only."""
    from sqlalchemy import select
    from lzo.semantic import facts
    from lzo.ingestion.models import identity_bindings, sources
    from lzo.ingestion.sources import SourceService
    from lzo.ontology.drafts import authorize_many
    required = required_identity_bindings(plan)
    package = plan['package_sha256']
    rows = uow.session.execute(select(identity_bindings.c.id, identity_bindings.c.resource_id,
        identity_bindings.c.source_id, identity_bindings.c.canonical_key,
        sources.c.configuration).join(sources, sources.c.id == identity_bindings.c.source_id).where(
            identity_bindings.c.resource_id.in_([UUID(value) for value in required.values()]),
            sources.c.configuration['source_system'].astext == 'fish-l1-package',
            sources.c.configuration['source_instance'].astext == package)).mappings().all()
    verified, source_ids, binding_ids = [], set(), set()
    for (table, pk), value in sorted(required.items()):
        identifier = UUID(value)
        matching = [row for row in rows if row['resource_id'] == identifier
            and row['configuration'].get('collection') == table + '|synthetic'
            and canonical_binding_matches(row['canonical_key'], package, table, pk)]
        if not matching:
            raise ValueError('Required GIS identity is not a current governed binding: ' + table + '/' + pk)
        obj = facts.get_object_row(uow, actor, identifier, 'edit')
        if (obj['payload']['data_nature'] != 'synthetic' or obj['payload']['state'] != 'active'
                or 'urn:lzo:fish-l1:class:' + table not in obj['payload']['class_iris']):
            raise ValueError('Required GIS identity has no matching active synthetic object: ' + table + '/' + pk)
        if 'urn:lzo:fish-l1:class:' + table not in facts.current_classes(uow, actor, identifier):
            raise ValueError('Required GIS identity has no currently eligible type: ' + table + '/' + pk)
        source_ids.update(row['source_id'] for row in matching)
        binding_ids.update(row['id'] for row in matching)
        verified.append({'table':table, 'pk':pk, 'resource_id':value, 'revision':obj['revision']})
    authorize_many(uow, actor, binding_ids)
    for source_id in sorted(source_ids, key=str):
        SourceService(uow).read(actor, source_id)
    return {'status':'required_gis_identities_verified', 'required_count':len(required),
        'verified_count':len(verified), 'identities':verified, 'package_sha256':package}


def geometry_metrics(uow, geometry):
    """Ellipsoidal metres from 4326 geography, never planar degree measurements."""
    from sqlalchemy import text
    from types import SimpleNamespace
    from lzo.semantic.geometry import normalize
    value = normalize(uow, SimpleNamespace(source_crs='EPSG:4326', geojson=validate_geometry(geometry)))
    polygon = geometry['type'] in ('Polygon', 'MultiPolygon')
    row = uow.session.execute(text('WITH g AS (SELECT public.ST_SetSRID('
        'public.ST_GeomFromGeoJSON(:geo),4326)::public.geography AS geog) '
        'SELECT public.ST_Area(geog,true) AS area, public.ST_Perimeter(geog,true) AS perimeter, '
        'public.ST_Length(geog,true) AS length FROM g'), {'geo': canonical(geometry)}).mappings().one()
    return {'geometry_area_m2': float(row['area']) if polygon else None,
        'geometry_perimeter_m': float(row['perimeter']) if polygon else None,
        'geometry_length_m': float(row['length']) if geometry['type'] in ('LineString', 'MultiLineString') else None,
        'value_kind': 'derived_simulation', 'horizontal_datum': 'EPSG:4326',
        'method': 'PostGIS ST_Area/ST_Perimeter/ST_Length(geography,true); WGS84 spheroid; metres/m2',
        'normalization_method': value['coordinate_method'], 'field_measurement': False}


def register_feature(uow, actor, feature, bundle, scope, source_id, layer_evidence):
    """One caller-owned transaction/idempotent step through the ordinary services."""
    from lzo.semantic import facts
    from lzo.ingestion.evidence import EvidenceService
    from lzo.ingestion.schemas import EvidenceCreate
    from lzo.storage.blobs import get_blob_store
    from lzo.gis.schemas import SpatialAssetInput
    from lzo.gis.service import register_spatial_asset
    identifier = UUID(feature['resource_id'])
    obj = facts.get_object_row(uow, actor, identifier, 'edit')
    if obj['payload']['data_nature'] != 'synthetic' or feature['data_nature'] != 'synthetic':
        raise ValueError('Fish GIS cannot attach to a non-synthetic object')
    from sqlalchemy import select
    from lzo.ingestion.models import identity_bindings, sources
    from lzo.ingestion.sources import SourceService
    entity = feature['entity']
    table, pk = ((entity['table'], entity['pk']) if entity['binding_status'] == 'bound'
                 else ('spatial_layer_registry', feature['layer_id']))
    matches = uow.session.execute(select(identity_bindings.c.source_id, identity_bindings.c.canonical_key)
        .join(sources, sources.c.id == identity_bindings.c.source_id)
        .where(identity_bindings.c.resource_id == identifier,
               sources.c.configuration['source_system'].astext == 'fish-l1-package',
               sources.c.configuration['source_instance'].astext == feature['package_sha256'],
               sources.c.configuration['collection'].astext == table + '|synthetic')).all()
    binding = next((row for row in matches if canonical_binding_matches(
        row.canonical_key, feature['package_sha256'], table, pk)), None)
    if binding is None:
        raise ValueError('Fish GIS UUID is not the governed source identity')
    SourceService(uow).read(actor, binding.source_id)
    enriched = {**feature, 'geometry_metrics': geometry_metrics(uow, feature['geometry']),
        'layer_evidence_version_id': str(layer_evidence.id)}
    settings = facts.settings_for(uow)
    store = get_blob_store(settings)
    evidence = EvidenceService(uow, store, settings).create(uow, actor,
        io.BytesIO(canonical(enriched).encode('utf-8')), 'application/json', EvidenceCreate(
            source_id=source_id, scope=scope, target_refs=(layer_evidence.revision,),
            title='fish-gis-' + feature['asset_id'] + '.json',
            locator=feature['source_file'] + '#feature=' + feature['feature_id'],
            data_nature='synthetic', replaces_id=None))
    command = SpatialAssetInput(resource_id=identifier, expected_revision=obj['revision'],
        asset_id=UUID(feature['asset_id']), artifact_version_id=evidence.id, sha256=evidence.blob.sha256,
        footprint=feature['geometry'], horizontal_datum='EPSG:4326',
        captured_at=datetime.fromisoformat(feature['captured_at'].replace('Z', '+00:00')),
        accuracy_metres=None, source=SOURCE_PREFIX + feature['package_sha256'], quality='display_only')
    result = register_spatial_asset(uow, actor, command, bundle)
    return {'asset_id': feature['asset_id'], 'resource_id': str(identifier),
        'evidence_version_id': str(evidence.id), 'revision': result.revision,
        'geometry_metrics': enriched['geometry_metrics']}


def object_features(uow, actor, identifier, *, package_sha256=None, layer=None, limit=100, cursor=None):
    """Read current authorized GIS assets and controlled evidence, never local files."""
    from lzo.gis.service import list_spatial_assets
    from lzo.ingestion.evidence import EvidenceService
    from lzo.ingestion.sources import SourceService
    from lzo.semantic import facts
    from lzo.storage.blobs import get_blob_store
    from lzo.errors import ApiError
    page = list_spatial_assets(uow, actor, identifier, limit=limit, cursor=cursor)
    settings = facts.settings_for(uow)
    store = get_blob_store(settings)
    service = EvidenceService(uow, store, settings)
    output = []
    for asset in page['assets']:
        if not asset['source'].startswith(SOURCE_PREFIX):
            continue
        if package_sha256 and asset['source'] != SOURCE_PREFIX + package_sha256:
            continue
        try:
            evidence = service.read(actor, UUID(asset['artifact_version_id']))
            if evidence.data_nature != 'synthetic' or evidence.blob.size_bytes > 2_000_000:
                raise ApiError('FISH_GIS_EVIDENCE_INVALID', 409, 'Fish feature evidence differs')
            if evidence.source_id is None:
                raise ApiError('FISH_GIS_EVIDENCE_INVALID', 409, 'Fish spatial evidence has no source')
            SourceService(uow).read(actor, evidence.source_id)
            with store.open(evidence.blob) as stream:
                value = json.load(stream)
            if (not isinstance(value, dict) or value.get('contract') != CONTRACT
                    or not isinstance(value.get('layer_evidence_version_id'), str)):
                raise ApiError('FISH_GIS_EVIDENCE_INVALID', 409, 'Invalid fish feature evidence')
            # Recheck the original-layer evidence permission on every read.
            original = service.read(actor, UUID(value['layer_evidence_version_id']))
            if (original.source_id is None or original.data_nature != 'synthetic'
                    or original.blob.sha256 != value.get('source_file_sha256')):
                raise ApiError('FISH_GIS_EVIDENCE_INVALID', 409, 'Original spatial source differs')
            SourceService(uow).read(actor, original.source_id)
        except ApiError as error:
            if error.status in (403, 404):
                continue
            raise
        if (value.get('contract') != CONTRACT or value.get('resource_id') != str(identifier)
                or value.get('asset_id') != asset['asset_id'] or value.get('data_nature') != 'synthetic'
                or SOURCE_PREFIX + str(value.get('package_sha256')) != asset['source']
                or asset['quality'] != 'display_only'):
            raise ApiError('FISH_GIS_EVIDENCE_INVALID', 409, 'Spatial identity differs from evidence')
        if layer and value['layer_name'] != layer:
            continue
        output.append({'type': 'Feature', 'id': value['asset_id'], 'geometry': asset['normalized'],
            'properties': {key: item for key, item in value.items() if key != 'geometry'}})
    return {'type': 'FeatureCollection', 'features': output, 'gis_status': page['status'],
        'next_cursor': page['next_cursor'], 'resource_id': str(identifier), 'data_nature': 'synthetic',
        'not_for_navigation': True}


def pond_features(uow, actor, package_sha256, *, after=None, limit=100):
    """Dataset discovery is filtered by live object AND source/evidence authority."""
    from sqlalchemy import select
    from lzo.ingestion.models import sources, identity_bindings
    from lzo.semantic import facts
    from lzo.auth.permissions import validate_actor
    from lzo.errors import ApiError
    validate_actor(uow, actor)
    if not re.fullmatch('[0-9a-f]{64}', package_sha256) or not 1 <= limit <= 1000:
        raise ApiError('INVALID_FISH_QUERY', 422, 'Invalid fish dataset query')
    visible = facts.visible_objects(actor).with_only_columns(facts.objects.c.id)
    statement = select(identity_bindings.c.resource_id).join(sources,
        sources.c.id == identity_bindings.c.source_id).where(
            sources.c.configuration['source_system'].astext == 'fish-l1-package',
            sources.c.configuration['source_instance'].astext == package_sha256,
            sources.c.configuration['collection'].astext == 'ponds|synthetic',
            identity_bindings.c.resource_id.in_(visible)).distinct().order_by(identity_bindings.c.resource_id)
    if after:
        statement = statement.where(identity_bindings.c.resource_id > UUID(after))
    output, status, last = [], 'current', None
    asset_limit = min(facts.settings_for(uow).list_max_page_size, 1000)
    for identifier in uow.session.execute(statement).scalars():
        asset_cursor, found = None, []
        while True:
            page = object_features(uow, actor, identifier, package_sha256=package_sha256,
                                   layer='ponds', limit=asset_limit, cursor=asset_cursor)
            if page['gis_status'] != 'current':
                status = page['gis_status']
            found.extend(page['features'])
            asset_cursor = page['next_cursor']
            if not asset_cursor:
                break
        if not found:
            continue
        if len(output) >= limit:
            break
        output.extend(found)
        last = str(identifier)
    else:
        last = None
    return {'type': 'FeatureCollection', 'features': output, 'package_sha256': package_sha256,
        'gis_status': status, 'next_cursor': last, 'data_nature': 'synthetic', 'not_for_navigation': True}


from fastapi import APIRouter, Depends, Query, Response
from lzo.auth.router import AuthRequest, authenticated

router = APIRouter(prefix='/api/v1/fish/gis', tags=['Fish synthetic GIS'])


@router.get('/objects/{identifier}', operation_id='getFishObjectSpatialFeatures',
            response_model=FishObjectFeatureCollection)
def get_object_features(identifier: UUID, response: Response, package_sha256: str | None = Query(None, pattern='^[0-9a-f]{64}$'),
                        layer: str | None = None, limit: int = Query(100, ge=1, le=1000),
                        cursor: str | None = None, auth: AuthRequest = Depends(authenticated)):
    response.headers['Cache-Control'] = 'private, no-store'
    return object_features(auth.uow, auth.actor, identifier, package_sha256=package_sha256,
                           layer=layer, limit=limit, cursor=cursor)


@router.get('/datasets/{package_sha256}/ponds', operation_id='listFishPondSpatialFeatures',
            response_model=FishPondFeatureCollection)
def get_pond_features(package_sha256: str, response: Response, limit: int = Query(100, ge=1, le=1000),
                      cursor: UUID | None = None, auth: AuthRequest = Depends(authenticated)):
    response.headers['Cache-Control'] = 'private, no-store'
    return pond_features(auth.uow, auth.actor, package_sha256, after=str(cursor) if cursor else None, limit=limit)

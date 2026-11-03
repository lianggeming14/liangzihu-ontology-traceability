"""Drawing claims in the existing governed semantic store, never a parallel ontology.

The pure plan is safe to inspect without a database. Application requires an
existing authorized operator and an active, normally approved schema release.
All supplied claims remain candidate; only generated import bookkeeping is
accepted. Even those records retain imported_unverified data nature.
"""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from uuid import UUID, uuid5

N = 'urn:lzo:drawing-ontology:'
NS = UUID('7d497ac4-c4bd-45f5-9007-fb1540ae5464')
CONTRACT = 'governed-drawing-import/1'
NATURE = 'imported_unverified'
XSD = 'http://www.w3.org/2001/XMLSchema#'
META = ('importDataset', 'importVersion', 'importBundleSha256')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Canonical UUID required')
    return value


def _strings(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError('Invalid ' + name)
    return value


def validate_bundle(value):
    from lzo.semantic.rdf import RdfTerm, iri
    if not isinstance(value, dict) or value.get('schema_version') != 'drawing-semantics/1':
        raise ValueError('Unsupported drawing semantics contract')
    for name in ('dataset_id', 'version'):
        if not isinstance(value.get(name), str) or not value[name] or len(value[name]) > 128:
            raise ValueError('Invalid ' + name)
    if value.get('content_sha256') != digest({k: v for k, v in value.items() if k != 'content_sha256'}):
        raise ValueError('Semantic bundle digest mismatch')
    drawings = set()
    for drawing in value['drawings']:
        name = drawing['id']
        if not isinstance(name, str) or not name or name in drawings:
            raise ValueError('Duplicate or invalid drawing ID')
        drawings.add(name)
        if not re.fullmatch('[0-9a-f]{64}', drawing['source_sha256']):
            raise ValueError('Invalid source hash')
        path = drawing['source_path']
        if (not isinstance(path, str) or not path or '\\' in path or ':' in path
                or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts):
            raise ValueError('Source path must be confined beneath the explicit source root')
    identifiers = set()
    for node in value['nodes']:
        identifier = _uuid(node['id'])
        if identifier in identifiers:
            raise ValueError('Duplicate semantic entity ID')
        identifiers.add(identifier)
        iri(node['class_iri'])
        if (node.get('data_nature') != NATURE or not isinstance(node['label'], str)
                or not 1 <= len(node['label']) <= 512):
            raise ValueError('Drawing entities must retain imported_unverified nature and a label')
        if not set(_strings(node['source_drawing_ids'], 'source drawings')) <= drawings:
            raise ValueError('Missing drawing reference')
        for prop in node['properties']:
            iri(prop['predicate_iri'])
            if prop['predicate_iri'] in {N + p for p in META}:
                raise ValueError('Import bookkeeping cannot be supplied as source facts')
            RdfTerm(**prop['term'])
            _strings(prop['evidence_ids'], 'property evidence locators')
    for node in value['nodes']:
        for prop in node['properties']:
            term = prop['term']
            if term['kind'] == 'iri' and term['value'].startswith('urn:lzo:object:'):
                if _uuid(term['value'][len('urn:lzo:object:'):]) not in identifiers:
                    raise ValueError('Dangling property relationship endpoint')
    for edge in value['edges']:
        if _uuid(edge['subject_id']) not in identifiers or _uuid(edge['object_id']) not in identifiers:
            raise ValueError('Dangling relationship endpoint')
        iri(edge['predicate_iri'])
        _strings(edge['evidence_ids'], 'relationship evidence locators')
        if not isinstance(edge.get('derivation'), str) or not edge['derivation']:
            raise ValueError('Relationship derivation is required')
    return value


def build_plan(value):
    from lzo.semantic.rdf import RdfTerm
    value = validate_bundle(value)
    objects, assertions = [], {}
    nodes = {n['id']: n for n in value['nodes']}

    def add(identifier, predicate, term, evidence, drawings, state, derivation, primary=None):
        term = asdict(RdfTerm(**term))
        identity = {'dataset_id': value['dataset_id'], 'version': value['version'],
                    'resource_id': identifier, 'predicate_iri': predicate, 'object': term, 'state': state}
        assertion_id = str(uuid5(NS, canonical(identity)))
        support_id = str(uuid5(NS, assertion_id + ':drawing-support'))
        fact = {'assertion_id': assertion_id, 'support_id': support_id,
            'resource_id': identifier, 'predicate_iri': predicate, 'object': term,
            'state': state, 'data_nature': NATURE, 'evidence_ids': sorted(set(evidence)),
            'source_drawing_ids': sorted(set(drawings)), 'derivation': derivation,
            'primary_source': primary or (next(iter(drawings)) if len(set(drawings)) == 1 else 'bundle')}
        old = assertions.get(assertion_id)
        if old:
            fact['evidence_ids'] = sorted(set(old['evidence_ids']) | set(fact['evidence_ids']))
            fact['source_drawing_ids'] = sorted(set(old['source_drawing_ids']) | set(fact['source_drawing_ids']))
            if old['primary_source'] != fact['primary_source']:
                fact['primary_source'] = 'bundle'
            if old['derivation'] != derivation:
                raise ValueError('Duplicate conclusion with inconsistent derivation')
        assertions[assertion_id] = fact

    for node in value['nodes']:
        objects.append({'resource_id': node['id'], 'class_iris': [node['class_iri']],
            'display_name': node['label'], 'data_nature': NATURE, 'state': 'draft'})
        for prop in node['properties']:
            add(node['id'], prop['predicate_iri'], prop['term'], prop['evidence_ids'],
                node['source_drawing_ids'], 'candidate', 'drawing_statement_not_field_verification')
        for local, text in zip(META, (value['dataset_id'], value['version'], value['content_sha256'])):
            add(node['id'], N + local, {'kind': 'literal', 'value': text}, [], [],
                'accepted', 'platform_import_bookkeeping_not_source_acceptance')
    for edge in value['edges']:
        exact = {d['id'] for d in value['drawings'] for locator in edge['evidence_ids']
                 if locator == d['id'] or locator.startswith(d['id'] + ':')}
        context = set(nodes[edge['subject_id']]['source_drawing_ids']) | set(nodes[edge['object_id']]['source_drawing_ids'])
        add(edge['subject_id'], edge['predicate_iri'], {'kind': 'iri', 'value': 'urn:lzo:object:' + edge['object_id']},
            edge['evidence_ids'], sorted(exact | context), 'candidate', edge['derivation'],
            primary=next(iter(exact)) if len(exact) == 1 else 'bundle')
    return {'contract': CONTRACT, 'dataset_id': value['dataset_id'], 'version': value['version'],
        'content_sha256': value['content_sha256'], 'objects': objects,
        'assertions': list(assertions.values()), 'drawings': value['drawings']}


def command_identity(value, actor_id, scope_id):
    """The same dataset/version cannot silently adopt changed content or scope."""
    return {'key': 'drawing-ontology:' + digest([value['dataset_id'], value['version']]),
        'digest': digest({'contract': CONTRACT, 'content_sha256': value['content_sha256'],
                         'actor_id': str(actor_id), 'owner_scope_id': str(scope_id)})}


def pending_assertions(planned, persisted):
    result = []
    for fact in planned:
        previous = persisted.get(fact['assertion_id'])
        if previous is None:
            result.append(fact)
        elif previous['assertion'] != fact:
            raise ValueError('Persisted drawing assertion conflict')
        elif not previous['active']:
            raise ValueError('A drawing support was withdrawn; explicit governed revision required')
    return result


def extend_document(document, plan):
    """Append only absent definitions; never weaken existing constraints or policy."""
    from lzo.ontology.schemas import ClassDef, PropertyDef, RelationDef
    from lzo.semantic.rdf import RdfTerm
    classes = {c.iri: c for c in document.classes}
    props = {p.iri: p for p in document.properties}
    relations = {r.iri: r for r in document.relations}
    for obj in plan['objects']:
        for cls in obj['class_iris']:
            if cls not in classes:
                classes[cls] = ClassDef(iri=cls, label=cls.rsplit(':', 1)[-1].rsplit('/', 1)[-1],
                    description='Drawing-derived record classification; imported_unverified. No survey, construction or unique real-asset verification is implied.')
    for fact in plan['assertions']:
        predicate, term = fact['predicate_iri'], RdfTerm(**fact['object'])
        relation = term.kind == 'iri' and term.value.startswith('urn:lzo:object:')
        if relation:
            if predicate in props:
                raise ValueError('Existing property conflicts with drawing relationship')
            if predicate not in relations:
                relations[predicate] = RelationDef(iri=predicate, label=predicate.rsplit(':', 1)[-1])
        else:
            if predicate in relations:
                raise ValueError('Existing relationship conflicts with drawing property')
            datatype = ('http://www.w3.org/1999/02/22-rdf-syntax-ns#langString' if term.language
                else XSD + 'anyURI' if term.kind == 'iri' else term.datatype_iri)
            if predicate not in props:
                props[predicate] = PropertyDef(iri=predicate, label=predicate.rsplit(':', 1)[-1],
                    datatype_iri=datatype, owner_policy_iri='urn:lzo:authority:ontology_owned',
                    enum_values=(term,) if term.kind == 'iri' else ())
            elif props[predicate].datatype_iri != datatype:
                raise ValueError('Drawing property datatype conflicts with schema')
            elif term.kind == 'iri' and term not in props[predicate].enum_values:
                if predicate in {p.iri for p in document.properties}:
                    raise ValueError('Drawing IRI is outside existing published vocabulary')
                props[predicate] = props[predicate].model_copy(update={'enum_values': (*props[predicate].enum_values, term)})
    return document.model_copy(update={'classes': tuple(classes.values()), 'properties': tuple(props.values()),
                                      'relations': tuple(relations.values())})


def verify_originals(plan, source_root):
    root = Path(source_root).resolve(strict=True)
    result = {}
    for drawing in plan['drawings']:
        path = (root / drawing['source_path']).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError('Original drawing escapes source root')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != drawing['source_sha256']:
            raise ValueError('Original drawing hash mismatch: ' + drawing['id'])
        result[drawing['id']] = path
    return result


class GovernedDrawingImport:
    """Reentrant orchestrator. Every mutation uses existing audited services."""

    def __init__(self, settings, actor_id, owner_scope_id):
        from lzo.main import create_app
        self.settings, self.actor_id, self.scope_id = settings, UUID(str(actor_id)), UUID(str(owner_scope_id))
        self.app = create_app(settings)
        self.engine = self.app.state.engine
        if self.engine.dialect.name != 'postgresql':
            raise ValueError('Actual PostgreSQL is required')

    def close(self):
        self.app.state.storage_registry.close()

    def _transaction(self, command):
        from lzo.db import PgUnitOfWork
        from lzo.auth.permissions import permission_context, current_version, validate_actor
        from lzo.contracts import ActorContext
        with PgUnitOfWork(self.engine) as uow, permission_context(uow):
            uow.ontology_settings = self.settings
            actor = ActorContext(self.actor_id, 'drawing-ontology-import', current_version(uow))
            validate_actor(uow, actor)
            result = command(uow, actor)
            uow.commit()
            return result

    def _step(self, identity, suffix, command):
        from lzo.governance.idempotency import execute_idempotent
        return self._transaction(lambda uow, actor: execute_idempotent(uow, actor,
            identity['key'] + ':' + suffix, identity['digest'], lambda: command(uow, actor)))

    def prepare_schema(self, identity, plan):
        from sqlalchemy import select
        from lzo.ontology.models import catalog, releases
        from lzo.ontology.schemas import SchemaDocument, CreateDraftRequest
        from lzo.ontology.drafts import create_draft
        from lzo.ontology.releases import descriptor, submit_draft, current_execution_bundle, publish_release
        from lzo.governance.approvals import ApprovalService

        def current(uow, actor):
            active = uow.session.execute(select(catalog.c.active_release_id)).scalar_one_or_none()
            document = SchemaDocument.model_validate(uow.session.execute(select(releases.c.document).where(
                releases.c.id == active)).scalar_one()) if active else SchemaDocument()
            desired = extend_document(document, plan)
            if active and document == desired:
                return {'status': 'ready', 'bundle_id': str(current_execution_bundle(uow, actor).id)}
            return {'status': 'schema_required'}
        status = self._transaction(current)
        if status['status'] == 'ready':
            return status

        def prepare(uow, actor):
            active = uow.session.execute(select(catalog.c.active_release_id)).scalar_one_or_none()
            document = SchemaDocument.model_validate(uow.session.execute(select(releases.c.document).where(
                releases.c.id == active)).scalar_one()) if active else SchemaDocument()
            draft = create_draft(uow, actor, CreateDraftRequest(base_release_id=active, document=extend_document(document, plan)))
            impact = descriptor(uow, actor, draft.id)
            approval = submit_draft(uow, actor, draft.id, impact.change_digest, draft.revision)
            return {'draft_id': str(draft.id), 'draft_revision': draft.revision,
                'approval_id': str(approval.id), 'change_digest': impact.change_digest,
                'baseline': impact.baseline, 'impact': impact.impact, 'risk': approval.risk}
        prepared = self._step(identity, 'schema', prepare)

        def publish(uow, actor):
            approval = ApprovalService(uow).get(actor, UUID(prepared['approval_id']))
            if approval.risk == 'high' and approval.status != 'approved':
                return {**prepared, 'status': 'awaiting_schema_approval', 'approval_status': approval.status,
                    'reason': 'Existing schema.publish policy requires an independent authorized reviewer. No approval was fabricated.'}
            job = publish_release(uow, actor, UUID(prepared['draft_id']), UUID(prepared['approval_id']), prepared['draft_revision'])
            return {**prepared, 'status': 'schema_installing', 'job_id': str(job.id)}
        return self._transaction(publish)

    def _evidence(self, identity, plan, files, bundle_bytes):
        from lzo.contracts import ResourceScope
        from lzo.ingestion.schemas import SourceCreate, EvidenceCreate
        from lzo.ingestion.sources import SourceService
        from lzo.ingestion.evidence import EvidenceService
        from lzo.storage.blobs import get_blob_store
        def register(uow, actor, name, stream, media_type):
            scope = ResourceScope(None, self.scope_id, (), 'data')
            source = SourceService(uow).create(uow, actor, SourceCreate(source_system='reviewed-drawings',
                source_instance=plan['dataset_id'], collection=name, kind='file', scope=scope, data_nature=NATURE))
            evidence = EvidenceService(uow, get_blob_store(self.settings), self.settings).create(uow, actor, stream, media_type,
                EvidenceCreate(source_id=source.id, scope=scope, target_refs=(), title=name + ('.pdf' if media_type == 'application/pdf' else '.json'),
                    locator='drawing-import:' + name, data_nature=NATURE, replaces_id=None))
            return {'source_id': str(source.id), 'evidence': evidence.model_dump(mode='json')}
        result = {'bundle': self._step(identity, 'evidence-bundle', lambda uow, actor:
            register(uow, actor, 'semantic-bundle', io.BytesIO(bundle_bytes), 'application/json'))}
        for name, path in files.items():
            def original(uow, actor, name=name, path=path):
                with path.open('rb') as stream:
                    return register(uow, actor, name, stream, 'application/pdf')
            result[name] = self._step(identity, 'evidence-' + digest(name), original)
        return result

    def _input(self, fact, evidence, recorded_at):
        from lzo.contracts import RevisionRef, BlobRef
        from lzo.semantic.schemas import AssertionInput, SourceSupport
        from lzo.semantic.rdf import RdfTerm
        refs = [evidence['bundle']['evidence']['revision']]
        refs.extend(evidence[name]['evidence']['revision'] for name in fact['source_drawing_ids'])
        source = evidence[fact['primary_source']]
        blob = evidence['bundle']['evidence']['blob']
        return AssertionInput(assertion_id=UUID(fact['assertion_id']), resource_id=UUID(fact['resource_id']),
            predicate_iri=fact['predicate_iri'], object=RdfTerm(**fact['object']), state=fact['state'],
            data_nature=NATURE, valid_from=recorded_at,
            support=SourceSupport(support_id=UUID(fact['support_id']),
                source_id=UUID(source['source_id']) if fact['state'] == 'candidate' else None,
                record_key=fact['resource_id'], source_version=source['evidence']['blob']['sha256'],
                snapshot=BlobRef(blob['sha256'], blob['size_bytes'], blob['media_type'], UUID(blob['version_id'])),
                evidence_refs=tuple(RevisionRef(UUID(r['resource_id']), r['revision'], UUID(r['event_id'])) for r in refs),
                raw_value={'drawing_import': fact, 'bundle_sha256': blob['sha256'],
                    'source_sha256': source['evidence']['blob']['sha256'],
                    'validity_basis': 'import_record_time_not_observation_or_construction_time'}))

    def import_objects(self, identity, plan, evidence, *, drain_jobs=0):
        from sqlalchemy import select
        from lzo.semantic import facts
        from lzo.semantic.schemas import CreateObjectInput, FactPatch
        from lzo.ontology.releases import current_execution_bundle
        from lzo.semantic.models import assertions, supports
        grouped = defaultdict(list)
        for fact in plan['assertions']:
            grouped[fact['resource_id']].append(fact)
        stamp = self._step(identity, 'clock', lambda uow, actor: {'recorded_at': datetime.now(timezone.utc).isoformat()})
        at = datetime.fromisoformat(stamp['recorded_at'])
        remaining_ticks = drain_jobs
        def checkpoint(index):
            nonlocal remaining_ticks
            if remaining_ticks and (index + 1) % 100 == 0:
                remaining_ticks -= self.drain(min(remaining_ticks, 300))
        # Every endpoint exists before relationship validation; no dangling IRI bypass.
        for index, obj in enumerate(plan['objects']):
            def create(uow, actor, obj=obj):
                bundle = current_execution_bundle(uow, actor)
                existing = uow.session.execute(select(facts.objects.c.id).where(facts.objects.c.id == UUID(obj['resource_id']))).first()
                if existing:
                    row = facts.get_object_row(uow, actor, UUID(obj['resource_id']), 'edit')
                    if any(row['payload'][key] != obj[key] for key in ('class_iris', 'display_name', 'data_nature', 'state')) or str(row['payload']['owner_scope_id']) != str(self.scope_id):
                        raise ValueError('Stable farm UUID already belongs to a different semantic object')
                    # Adopting an arbitrary pre-existing UUID needs an explicit identity decision.
                    raise ValueError('Stable farm UUID already registered outside this import; governed identity alignment required')
                receipt = facts.register_object(uow, actor, CreateObjectInput(**obj, owner_scope_id=self.scope_id,
                    assertions=tuple(self._input(a, evidence, at) for a in grouped[obj['resource_id']] if a['state'] == 'accepted')), bundle)
                return receipt.model_dump(mode='json')
            self._step(identity, 'object-' + obj['resource_id'], create)
            checkpoint(index)
        for index, obj in enumerate(plan['objects']):
            def patch(uow, actor, obj=obj):
                row = facts.get_object_row(uow, actor, UUID(obj['resource_id']), 'edit')
                wanted = grouped[obj['resource_id']]
                existing = {}
                for entry in uow.session.execute(select(assertions.c.id, assertions.c.payload, supports.c.payload.label('support'), supports.c.active)
                        .join(supports, supports.c.assertion_id == assertions.c.id).where(assertions.c.id.in_([UUID(a['assertion_id']) for a in wanted]))).mappings():
                    stored = entry['support'].get('raw_value', {}).get('drawing_import')
                    if stored is None:
                        raise ValueError('Drawing assertion identity conflict')
                    for key in ('resource_id', 'predicate_iri', 'object', 'state', 'data_nature'):
                        if entry['payload'][key] != stored[key]:
                            raise ValueError('Drawing assertion payload conflict')
                    existing[str(entry['id'])] = {'assertion': stored, 'active': entry['active']}
                pending = pending_assertions(wanted, existing)
                if not pending:
                    return {'resource_id': obj['resource_id'], 'status': 'unchanged'}
                receipt = facts.apply_fact_patch(uow, actor, FactPatch(resource_id=UUID(obj['resource_id']),
                    expected_revision=row['revision'], additions=tuple(self._input(a, evidence, at) for a in pending)), current_execution_bundle(uow, actor))
                return receipt.model_dump(mode='json')
            # Recheck live supports on every resume; do not resurrect withdrawn evidence.
            self._transaction(patch)
            checkpoint(index)
        return remaining_ticks

    def drain(self, limit):
        from lzo.worker.runner import Runner
        from lzo.synchronization.delivery import poll_deliveries
        runner = Runner(self.engine, self.settings)
        spent = 0
        for _ in range(limit):
            spent += 1
            if self.settings.storage_mode == 'split':
                poll_deliveries(self.app.state.storage_registry)
            if not runner.run_once():
                break
        return spent

    def inspect(self, plan):
        from sqlalchemy import select
        from lzo.semantic import facts
        from lzo.semantic.models import projection_heads, projection_events
        from lzo.semantic.fuseki import FusekiRepository, graph_iri
        from lzo.semantic.rdf import Triple, RdfTerm, triple_key
        repo = FusekiRepository(self.settings.fuseki_url)
        def inspect(uow, actor):
            records = []
            for obj in plan['objects']:
                identifier = UUID(obj['resource_id'])
                row = facts.get_object_row(uow, actor, identifier)
                head = uow.session.execute(select(projection_heads).where(projection_heads.c.resource_id == identifier)).mappings().first()
                event = uow.session.execute(select(projection_events).where(projection_events.c.resource_id == identifier,
                    projection_events.c.revision == row['revision'])).mappings().first()
                record = {'id': str(identifier), 'revision': row['revision'], 'projection_state': event['state'] if event else 'missing',
                          'rdf_candidate_count': None, 'rdf_accepted_count': None}
                if head and head['revision'] == row['revision'] and record['projection_state'] == 'synced':
                    for role in ('candidate', 'accepted'):
                        triples = repo.read_graph(graph_iri(identifier, role))
                        expected = {triple_key(Triple(facts.object_iri(identifier), a['predicate_iri'], RdfTerm(**a['object'])))
                            for a in plan['assertions'] if a['resource_id'] == str(identifier) and a['state'] == role}
                        actual = {triple_key(t) for t in triples}
                        if not expected <= actual:
                            raise ValueError('Persisted RDF is missing expected drawing statements')
                        record['rdf_' + role + '_count'] = len(triples)
                records.append(record)
            return records
        records = self._transaction(inspect)
        synced = all(r['projection_state'] == 'synced' and r['rdf_candidate_count'] is not None for r in records)
        return {'status': 'synced' if synced else 'projection_pending', 'entities': records,
            'candidate_assertions': sum(a['state'] == 'candidate' for a in plan['assertions']),
            'accepted_bookkeeping_assertions': sum(a['state'] == 'accepted' for a in plan['assertions']),
            'data_nature': NATURE, 'field_verification': 'not_performed'}

    def apply(self, value, source_root, *, drain_jobs=0):
        plan = build_plan(value)
        files = verify_originals(plan, source_root)
        identity = command_identity(value, self.actor_id, self.scope_id)
        self._step(identity, 'input', lambda uow, actor: {'contract': CONTRACT,
            'content_sha256': value['content_sha256'], 'operator_authorization': 'explicit CLI --apply under current platform permissions'})
        schema = self.prepare_schema(identity, plan)
        if schema['status'] == 'schema_installing' and drain_jobs:
            drain_jobs -= self.drain(drain_jobs)
            schema = self.prepare_schema(identity, plan)
        if schema['status'] != 'ready':
            return {**schema, 'semantic_entities_written': 0, 'input_sha256': value['content_sha256']}
        evidence = self._evidence(identity, plan, files, canonical(value).encode('utf8'))
        drain_jobs = self.import_objects(identity, plan, evidence, drain_jobs=drain_jobs)
        if drain_jobs:
            self.drain(drain_jobs)
        return {**self.inspect(plan), 'input_sha256': value['content_sha256'], 'bundle_id': schema['bundle_id'],
                'sources': {key: item['source_id'] for key, item in evidence.items()}}

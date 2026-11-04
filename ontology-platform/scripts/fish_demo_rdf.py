"""Explicitly authorized demo links; never source facts or identity equivalence."""
from collections import defaultdict
import hashlib

from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD
from fish_rdf_sample import NS, V, C, PROV, TABLE_DOMAINS

D = Namespace('urn:lzo:fish-review:demo:v1:')
POLICY = 'balanced_demo_only'
REASON = '用户授权的均分演示分配，不是现场归属'
PROFILE_REASON = '演示水深/体积模板，不是实测或现场归属'


def assignment(kind, source, target, original_pond_id):
    digest = hashlib.sha256((kind + '\n' + source['iri'] + '\n' + target['iri']).encode()).hexdigest()
    return {'iri': str(D['assignment:' + digest]), 'kind': kind, 'source': source['iri'],
        'target': target['iri'], 'original_pond_id': original_pond_id,
        'predicate': str(D.demoProfileFrom if kind == 'pond_profile' else D.demoAssignedTo),
        'reason': PROFILE_REASON if kind == 'pond_profile' else REASON}


def assignments(tables, map_payload):
    """Only canonical RDF-derived instances with an explicit original pond FK."""
    all_instances = {item['iri']: item for table in tables.values() for item in table['instances']}
    targets = sorted((all_instances[obj['object_iri']] for obj in map_payload['objects']
        if obj['asset_id'] != 'full' and obj['kind'] == 'pond'), key=lambda item: item['iri'])
    if len(targets) != 20: raise ValueError('Demo assignment requires the 20 independently sourced drawing pond boundaries')
    result, allocation_counts = [], {}
    for table, payload in sorted(tables.items()):
        if table.startswith('map_') or TABLE_DOMAINS.get(table, 'ProductionEvent') not in ('ProductionEvent', 'Observation'):
            continue
        eligible = []
        for item in payload['instances']:
            pond = next((prop['value'] for prop in item['properties'] if prop['field'] == 'pond_id'), None)
            if pond is not None and str(pond) and item['nature'] == 'synthetic': eligible.append((item, str(pond)))
        eligible.sort(key=lambda pair: (pair[0]['id'], pair[0]['iri']))
        counts = dict.fromkeys([target['iri'] for target in targets], 0)
        for index, (item, pond) in enumerate(eligible):
            target = targets[index % len(targets)]
            result.append(assignment('activity', item, target, pond))
            counts[target['iri']] += 1
        if eligible:
            if max(counts.values()) - min(counts.values()) > 1: raise ValueError('Unbalanced demo allocation')
            allocation_counts[table] = counts
    profiles = sorted(tables['ponds']['instances'], key=lambda item: (item['id'], item['iri']))
    if len(profiles) != 6: raise ValueError('Demo profile links require the six source synthetic pond profiles')
    for index, target in enumerate(targets):
        source = profiles[index % len(profiles)]
        result.append(assignment('pond_profile', target, source, source['id']))
    return result, allocation_counts


def project_demo(items):
    yield D.DemoAssignment, RDF.type, OWL.Class
    yield D.DemoAssignment, RDFS.label, Literal('显式演示分配', lang='zh')
    for predicate, label, inverse in [(D.demoAssignedTo, '均分演示记录分配到', D.hasDemoRecord),
        (D.demoProfileFrom, '演示水深体积模板来自', D.isDemoProfileFor)]:
        yield predicate, RDF.type, OWL.ObjectProperty
        yield predicate, RDFS.label, Literal(label, lang='zh')
        yield predicate, OWL.inverseOf, inverse
        yield inverse, RDF.type, OWL.ObjectProperty
        yield predicate, D.assignmentPolicy, Literal(POLICY)
        yield predicate, D.synthetic, Literal(True)
    for item in items:
        subject, source, target, predicate = [URIRef(item[key]) for key in ('iri', 'source', 'target', 'predicate')]
        inverse = D.isDemoProfileFor if item['kind'] == 'pond_profile' else D.hasDemoRecord
        yield subject, RDF.type, D.DemoAssignment
        yield subject, RDF.subject, source
        yield subject, RDF.predicate, predicate
        yield subject, RDF.object, target
        yield subject, D.kind, Literal(item['kind'])
        yield subject, D.assignmentPolicy, Literal(POLICY)
        yield subject, D.originalPondID, Literal(item['original_pond_id'])
        yield subject, D.synthetic, Literal(True)
        yield subject, RDFS.comment, Literal(item['reason'], lang='zh')
        yield subject, PROV.wasDerivedFrom, source
        yield source, predicate, target
        yield target, inverse, source


class DemoNavigation:
    def __init__(self): self.items = defaultdict(dict)
    def add(self, s, p, o):
        if str(s).startswith(str(D) + 'assignment:'): self.items[str(s)][str(p)] = o
    def apply(self, tables):
        instances = {item['iri']: item for table in tables.values() for item in table['instances']}
        for item in instances.values(): item['demo_assignments'] = []
        counts = defaultdict(int)
        for iri, props in sorted(self.items.items()):
            source, target = str(props[str(RDF.subject)]), str(props[str(RDF.object)])
            if source not in instances or target not in instances: raise ValueError('Demo link has an unknown source or target')
            if str(props[str(D.assignmentPolicy)]) != POLICY or str(props[str(D.synthetic)]) != 'true':
                raise ValueError('Demo link lost its explicit non-factual nature')
            a, b = instances[source], instances[target]
            kind = str(props[str(D.kind)])
            edge = {'kind': kind, 'assignment_iri': iri, 'relation_iri': str(props[str(RDF.predicate)]),
                'assignment_policy': POLICY, 'synthetic': True, 'original_pond_id': str(props[str(D.originalPondID)]),
                'reason': str(props[str(RDFS.comment)])}
            a['demo_assignments'].append({**edge, 'direction': 'outgoing', 'target_iri': target,
                'target_id': b['id'], 'target_label': b['label'], 'target_class_iri': b['class_iri']})
            b['demo_assignments'].append({**edge, 'direction': 'incoming', 'source_iri': source,
                'source_id': a['id'], 'source_label': a['label'], 'source_class_iri': a['class_iri']})
            counts[kind] += 1
        return dict(counts)

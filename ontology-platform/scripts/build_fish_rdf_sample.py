"""Rebuild an isolated RDF review graph from the existing read-only SQL sample."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import gzip
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import httpx
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser
from rdflib.plugins.serializers.nt import _quoteLiteral
from sqlalchemy import create_engine, text

from fish_review_config import ROOT, SCHEMA, database_url, load_config
from fish_rdf_sample import NS, V, C, Navigation, project, triple_digest, uri, datatype, expanded_schema

# Exact archive pin; retain the full value separately from graph/content digests.
PACKAGE = '04891aab2039607015d41575e292a0add57065af3a2037270893cc0f3cd7c4b7'
DEFAULT_ENDPOINT = 'http://127.0.0.1:23049/fish_l1'
DEFAULT_OUTPUT = ROOT / 'docs/fish/ontology-review'
RUNTIME = ROOT / '.runtime/fish-rdf-review'
SH = Namespace('http://www.w3.org/ns/shacl#')


def check_target(endpoint, graph):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port != 23049
        or parsed.path != '/fish_l1' or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Only the existing isolated loopback Fuseki dataset is allowed')
    patterns = [re.escape(NS) + 'graph:[0-9a-f]{64}:[0-9a-f]{64}',
        r'urn:lzo:fish-review:(map|demo|drawing):v1:graph:[0-9a-f]{64}']
    if not any(re.fullmatch(pattern, graph) for pattern in patterns):
        raise ValueError('Only the independent content-addressed sample graph is allowed')


def extract(config):
    engine = create_engine(database_url(config), hide_parameters=True,
        connect_args={'hostaddr': '127.0.0.1', 'connect_timeout': 10})
    try:
        with engine.connect() as connection:
            connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            if connection.execute(text('SHOW transaction_read_only')).scalar_one() != 'on':
                raise ValueError('Source transaction is not read-only')
            schema = json.loads((ROOT / 'datasets/fish/source-schema.json').read_text(encoding='utf-8'))
            raw = [dict(row) for row in connection.execute(text(
                f'SELECT * FROM {SCHEMA}.raw_records ORDER BY table_name,row_number')).mappings()]
            nodes = [dict(row) for row in connection.execute(text(
                f'SELECT * FROM {SCHEMA}.ontology_nodes ORDER BY table_name,source_pk')).mappings()]
            edges = [dict(row) for row in connection.execute(text(
                f'SELECT * FROM {SCHEMA}.ontology_relations ORDER BY edge_id')).mappings()]
            if {row['package_sha256'] for row in raw} != {PACKAGE}:
                raise ValueError('Source archive identity differs from pinned review dataset')
            definitions = {(row['table_name'], row['field_name']): row['definition'] for row in
                connection.execute(text(f'SELECT * FROM {SCHEMA}.field_dictionary')).mappings()}
            expected = {(table, field): definition for table, spec in schema['tables'].items()
                for field, definition in spec['columns'].items()}
            if definitions != expected: raise ValueError('SQL field dictionary differs from pinned source schema')
            if (len(raw), len(nodes), len(edges)) != (20606, 20548, 68343):
                raise ValueError('SQL sample is incomplete or has changed; rebuild review selection first')
            return {'package_sha256': PACKAGE, 'schema': schema, 'raw': raw, 'nodes': nodes, 'relations': edges}
    finally:
        engine.dispose()


def write_rdf(snapshot, path, *, source_triples=None):
    inventory, vocabulary, vocabulary_subjects = set(), Graph(), set()
    for prefix, namespace in [('review', NS), ('lzo', str(C)), ('owl', str(OWL)), ('rdfs', str(RDFS)), ('xsd', str(XSD))]:
        vocabulary.bind(prefix, Namespace(namespace))
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for s, p, o in project(snapshot) if source_triples is None else source_triples:
            digest = triple_digest(s, p, o)
            if digest in inventory: continue
            inventory.add(digest)
            stream.write(s.n3() + ' ' + p.n3() + ' ' + (_quoteLiteral(o) if isinstance(o, Literal) else o.n3()) + ' .\n')
            if p == RDF.type and o in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology):
                vocabulary_subjects.add(s)
            if (s in vocabulary_subjects or str(s).startswith(str(C)) or any(str(s).startswith(NS + kind + ':')
                for kind in ('class', 'property', 'relation', 'raw', 'dataset')) or s in (V.SourceRecord, V.RelationRecord)):
                vocabulary.add((s, p, o))
    return inventory, vocabulary


def shacl(schema):
    graph = Graph()
    graph.bind('sh', SH)
    graph.bind('review', V)
    for table, spec in schema['tables'].items():
        shape = uri('shape', table)
        graph.add((shape, RDF.type, SH.NodeShape))
        graph.add((shape, SH.targetClass, uri('class', table)))
        for field, definition in spec['columns'].items():
            prop = uri('shape-property', table, field)
            graph.add((shape, SH.property, prop))
            graph.add((prop, SH.path, uri('property', table, field)))
            graph.add((prop, SH.datatype, datatype(definition)))
            graph.add((prop, SH.maxCount, Literal(1)))
    return graph


def select(client, endpoint, query):
    response = client.post(endpoint + '/query', data={'query': query, 'timeout': '60000'},
        headers={'Accept': 'application/sparql-results+json'})
    response.raise_for_status()
    return response.json()


def other_graphs(client, endpoint):
    query = 'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g {?s ?p ?o} FILTER(!STRSTARTS(STR(?g), "urn:lzo:fish-review:")) } GROUP BY ?g'
    return {row['g']['value']: int(row['n']['value']) for row in select(client, endpoint, query)['results']['bindings']}


class Readback:
    def __init__(self, expected, navigation):
        self.remaining = expected.copy()
        self.navigation = navigation
        self.count = 0
    def triple(self, s, p, o):
        digest = triple_digest(s, p, o)
        if digest not in self.remaining:
            raise ValueError('Jena returned an unexpected, altered or duplicated RDF triple: ' + str(s) + ' ' + str(p))
        self.remaining.remove(digest)
        self.navigation.add(s, p, o)
        self.count += 1
        if self.count % 500000 == 0:
            print(json.dumps({'stage': 'rdf_term_readback', 'verified_triples': self.count}), flush=True)


def load_and_read(endpoint, graph, path, inventory, runtime, *, navigation=None, expected_counts=None, query_patterns=None):
    check_target(endpoint, graph)
    navigation = Navigation() if navigation is None else navigation
    expected_counts = expected_counts or {'instances': 20548, 'source_records': 20606, 'relation_records': 68343}
    with httpx.Client(timeout=httpx.Timeout(180, connect=10), trust_env=False) as client:
        before = other_graphs(client, endpoint)
        existing = select(client, endpoint, 'ASK { GRAPH <' + graph + '> { ?s ?p ?o } }')['boolean']
        if not existing:
            with path.open('rb') as data:
                response = client.put(endpoint + '/data', params={'graph': graph},
                    content=iter(lambda: data.read(1024 * 1024), b''),
                    headers={'Content-Type': 'application/n-triples', 'Content-Length': str(path.stat().st_size)})
                response.raise_for_status()
        returned = runtime / (path.stem + '-jena-readback.nt')
        with client.stream('GET', endpoint + '/data', params={'graph': graph},
                headers={'Accept': 'application/n-triples', 'Accept-Encoding': 'identity'}) as response:
            response.raise_for_status()
            with returned.open('wb') as stream:
                for chunk in response.iter_bytes(): stream.write(chunk)
        sink = Readback(inventory, navigation)
        with returned.open('r', encoding='utf-8') as stream:
            W3CNTriplesParser(sink=sink).parse(stream)
        if sink.remaining: raise ValueError('Jena omitted ' + str(len(sink.remaining)) + ' expected RDF triples')
        queries = {
            'instances': f'?s <{RDF.type}> ?c . ?c <{V.sourceTable}> ?table ; <{RDF.type}> <{OWL.Class}> .',
            'source_records': f'?s <{RDF.type}> <{V.SourceRecord}> .',
            'relation_records': f'?s <{RDF.type}> <{V.RelationRecord}> .',
            'resolved_relations': f'?s <{RDF.type}> <{V.RelationRecord}> ; <{V.resolution}> "resolved" .',
            'missing_inverse': f'?e <{RDF.type}> <{V.RelationRecord}> ; <{RDF.subject}> ?s ; <{RDF.predicate}> ?p ; <{RDF.object}> ?o . ?p <{OWL.inverseOf}> ?inv . FILTER NOT EXISTS {{ ?o ?inv ?s }}',
            'orphan_targets': f'?e <{RDF.type}> <{V.RelationRecord}> ; <{RDF.object}> ?s . FILTER NOT EXISTS {{ ?s <{V.sourcePK}> ?id }}',
        }
        if query_patterns is not None: queries = query_patterns
        checks = {}
        for name, pattern in queries.items():
            result = select(client, endpoint, 'SELECT (COUNT(*) AS ?n) WHERE { GRAPH <' + graph + '> {' + pattern + '} }')
            checks[name] = int(result['results']['bindings'][0]['n']['value'])
            print(json.dumps({'stage': 'sparql_readback', 'check': name, 'value': checks[name]}), flush=True)
        after = other_graphs(client, endpoint)
        if after != before: raise ValueError('Pre-existing non-review graph inventory changed during RDF load')
        if any(checks[name] != value for name, value in expected_counts.items()):
            raise ValueError('SPARQL count verification failed')
        if checks.get('missing_inverse') or checks.get('orphan_targets'): raise ValueError('SPARQL integrity verification failed')
        return navigation, {'triple_count': sink.count, 'all_triples_readback': 'passed',
            'unexpected_or_missing_triples': 0, 'sparql': checks, 'preexisting_graphs_unchanged': True,
            'preexisting_graph_count': len(before), 'existing_graph_reused': existing}


def merge_concepts(manifest, extra, tables):
    concepts = {item['iri']: dict(item) for item in manifest['concepts']}
    for item in extra:
        if item['iri'] in concepts:
            old = concepts[item['iri']]
            if old['parent_iri'] != item['parent_iri'] or old['table'] != item['table']:
                raise ValueError('Conflicting domain identity across sample and map graphs')
        else: concepts[item['iri']] = dict(item)
    for item in concepts.values():
        item['children'] = []
        item['instance_count'] = len(tables[item['table']]['instances']) if item['table'] else 0
        if item['table']: item['instances_path'] = 'classes/' + item['table'] + '.json.gz'
    for item in concepts.values():
        if item['parent_iri'] in concepts: concepts[item['parent_iri']]['children'].append(item['iri'])
    def count(iri, visited):
        if iri in visited: raise ValueError('Merged ontology hierarchy cycle')
        item = concepts[iri]
        item['children'].sort()
        item['total_instance_count'] = item['instance_count'] + sum(count(child, visited | {iri}) for child in item['children'])
        return item['total_instance_count']
    for iri, item in concepts.items():
        if item['parent_iri'] not in concepts: count(iri, set())
    manifest['concepts'] = sorted(concepts.values(), key=lambda item: item['iri'])
    manifest['counts'].update(classes=len(concepts), source_classes=len(tables),
        instances=sum(len(table['instances']) for table in tables.values()))


def add_map_and_demo(endpoint, manifest, tables, runtime, vocabulary=None):
    from fish_map_rdf import project_map, MapNavigation
    from fish_demo_rdf import assignments, project_demo, DemoNavigation, D
    map_payload = json.loads((ROOT / 'datasets/farm-map/map-objects.json').read_text(encoding='utf-8'))
    map_path = runtime / 'map.nt'
    inventory, map_vocabulary = write_rdf(None, map_path, source_triples=project_map(map_payload))
    sha = hashlib.sha256(map_path.read_bytes()).hexdigest()
    map_graph = 'urn:lzo:fish-review:map:v1:graph:' + sha
    map_navigation, map_check = load_and_read(endpoint, map_graph, map_path, inventory, runtime,
        navigation=MapNavigation(), expected_counts={'instances': 290, 'source_records': 0, 'relation_records': 284})
    map_concepts, map_tables = map_navigation.finish()
    if set(tables) & set(map_tables): raise ValueError('Map source tables collide with synthetic data')
    for payload in map_tables.values(): payload.update(graph_iri=map_graph, jena_verified=True)
    tables.update(map_tables)
    merge_concepts(manifest, map_concepts, tables)
    manifest['rdf_graphs'].append(map_graph)
    manifest['counts']['map_objects'] = 284
    manifest['counts']['map_layers'] = 6
    manifest['counts']['relations'] += 284
    manifest['counts']['resolved_relations'] += 284
    items, allocation_counts = assignments(tables, map_payload)
    demo_path = runtime / 'demo.nt'
    demo_inventory, demo_vocabulary = write_rdf(None, demo_path, source_triples=project_demo(items))
    demo_sha = hashlib.sha256(demo_path.read_bytes()).hexdigest()
    demo_graph = str(D) + 'graph:' + demo_sha
    patterns = {'demo_assignments': f'?s <{RDF.type}> <{D.DemoAssignment}> .',
        'missing_inverse': f'?e <{RDF.type}> <{D.DemoAssignment}> ; <{RDF.subject}> ?s ; <{RDF.predicate}> ?p ; <{RDF.object}> ?o . ?p <{OWL.inverseOf}> ?inv . FILTER NOT EXISTS {{ ?o ?inv ?s }}'}
    demo_navigation, demo_check = load_and_read(endpoint, demo_graph, demo_path, demo_inventory, runtime,
        navigation=DemoNavigation(), expected_counts={'demo_assignments': len(items)}, query_patterns=patterns)
    demo_counts = demo_navigation.apply(tables)
    manifest['rdf_graphs'].append(demo_graph)
    manifest['counts'].update(demo_assignments=len(items), demo_activity_links=demo_counts.get('activity', 0),
        demo_profile_links=demo_counts.get('pond_profile', 0))
    manifest['counts']['triples'] += map_check['triple_count'] + demo_check['triple_count']
    if vocabulary is not None:
        for triple in map_vocabulary: vocabulary.add(triple)
        for triple in demo_vocabulary: vocabulary.add(triple)
    return {'map': {'graph_iri': map_graph, **map_check}, 'demo': {'graph_iri': demo_graph,
        **demo_check, 'counts': demo_counts, 'assignment_policy': 'balanced_demo_only',
        'per_source_table_pond_allocations': allocation_counts}}


def build(args):
    started = time.monotonic()
    config = load_config(args.config)
    runtime = RUNTIME
    runtime.mkdir(parents=True, exist_ok=True)
    output = Path(args.output)
    snapshot = extract(config)
    print(json.dumps({'stage': 'source_read', 'raw': len(snapshot['raw']), 'instances': len(snapshot['nodes']),
        'relations': len(snapshot['relations']), 'transaction': 'repeatable_read_read_only'}), flush=True)
    path = runtime / 'sample.nt'
    inventory, vocabulary = write_rdf(snapshot, path)
    sha = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    termset_sha = hashlib.sha256(b''.join(sorted(inventory))).hexdigest()
    graph = NS + 'graph:' + PACKAGE + ':' + termset_sha
    print(json.dumps({'stage': 'rdf_generated', 'triples': len(inventory), 'bytes': path.stat().st_size,
        'graph_iri': graph, 'seconds': round(time.monotonic() - started, 2)}), flush=True)
    if args.generate_only:
        print('Generation only; no Jena verification or public snapshot generated.', flush=True)
        return
    navigation, verified = load_and_read(args.fuseki, graph, path, inventory, runtime)
    from fish_rdf_validation import shapes, validate_canonical
    shape_graph = shapes(expanded_schema(snapshot), vocabulary)
    shacl_report = validate_canonical(navigation, shape_graph,
        progress=lambda value: print(json.dumps(value), flush=True))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'shacl-readback.json').write_text(json.dumps(shacl_report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if shacl_report['status'] != 'passed': raise ValueError('Canonical RDF failed actual SHACL validation')
    manifest, tables = navigation.finish()
    manifest.update(graph_iri=graph, rdf_graphs=[graph], jena_verified=True, fuseki_readback=True,
        source_schema=SCHEMA, checked_at=datetime.now(timezone.utc).isoformat())
    manifest['counts']['triples'] = verified['triple_count']
    extra_checks = add_map_and_demo(args.fuseki, manifest, tables, runtime, vocabulary)
    data_dir = output / 'data'
    (data_dir / 'classes').mkdir(parents=True, exist_ok=True)
    shard_sizes = {}
    for table, payload in tables.items():
        payload.setdefault('graph_iri', graph)
        payload.update(jena_verified=True)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        compressed = gzip.compress(encoded, mtime=0)
        if len(compressed) >= 20 * 1024 * 1024: raise ValueError('Compressed public class shard exceeds publication limit')
        (data_dir / 'classes' / (table + '.json.gz')).write_bytes(compressed)
        shard_sizes[table] = {'uncompressed': len(encoded), 'compressed': len(compressed)}
    (data_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'vocabulary.ttl').write_bytes((vocabulary.serialize(format='turtle').rstrip() + '\n').encode('utf-8'))
    (output / 'shapes.ttl').write_bytes((shape_graph.serialize(format='turtle').rstrip() + '\n').encode('utf-8'))
    report = {'contract': 'fish-rdf-readback/1', 'status': 'passed', 'formal_adoption': False,
        'package_sha256': PACKAGE, 'source_read_only': True, 'graph_iri': graph, 'rdf_graphs': [graph],
        'rdf_sha256': sha, 'rdf_termset_sha256': termset_sha, 'rdf_bytes': path.stat().st_size, **verified,
        'rdf_graphs': manifest['rdf_graphs'], 'map_and_demo': extra_checks,
        'shacl': {'status': shacl_report['status'], 'instances_validated': shacl_report['instances_validated'],
            'datatype_constraints': shacl_report['datatype_constraints'], 'violations': shacl_report['violations']},
        'public_shards': {'files': len(shard_sizes), 'maximum_compressed_bytes': max(v['compressed'] for v in shard_sizes.values()),
            'total_compressed_bytes': sum(v['compressed'] for v in shard_sizes.values()), 'by_table': shard_sizes},
        'navigation': manifest['counts'], 'data_nature': 'synthetic; weather imported_unverified',
        'raw_payload_public': False, 'raw_retained_in_local_rdf': True,
        'seconds': round(time.monotonic() - started, 2), 'checked_at': manifest['checked_at']}
    (output / 'rdf-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'stage': 'sample_map_demo_verified', 'graphs': len(manifest['rdf_graphs']),
        'counts': manifest['counts'], 'shacl': report['shacl'], 'seconds': report['seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/fish-review.example.json')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--fuseki', default=DEFAULT_ENDPOINT)
    parser.add_argument('--generate-only', action='store_true')
    arguments = parser.parse_args()
    build(arguments)
    if not arguments.generate_only:
        from extend_fish_rdf_drawings import extend
        extend(arguments.output, arguments.fuseki)

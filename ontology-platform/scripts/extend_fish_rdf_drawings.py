"""Append independently verified drawing evidence to the three review graphs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

from rdflib import Graph, Namespace
from rdflib.namespace import RDF, OWL

from build_fish_rdf_sample import (ROOT, RUNTIME, DEFAULT_OUTPUT, DEFAULT_ENDPOINT,
    write_rdf, load_and_read, merge_concepts)
from fish_drawing_rdf import NS, project_drawing, DrawingNavigation

D = Namespace(NS)


def extend(output=DEFAULT_OUTPUT, endpoint=DEFAULT_ENDPOINT):
    output = Path(output)
    data = output / 'data'
    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    report = json.loads((output / 'rdf-readback.json').read_text(encoding='utf-8'))
    if not manifest.get('fuseki_readback') or report.get('status') != 'passed':
        raise ValueError('Three source review graphs must be verified before drawing extension')
    tables = {}
    for concept in manifest['concepts']:
        if concept['table']:
            path = (data / concept['instances_path']).resolve()
            if not path.is_relative_to(data.resolve()) or not str(path).endswith('.json.gz'):
                raise ValueError('Invalid public class shard path')
            tables[concept['table']] = json.loads(gzip.decompress(path.read_bytes()))
    payload = json.loads((ROOT / 'datasets/drawings/semantic-bundle.json').read_text(encoding='utf-8'))
    map_objects = json.loads((ROOT / 'datasets/farm-map/map-objects.json').read_text(encoding='utf-8'))
    path = RUNTIME / 'drawing.nt'
    inventory, drawing_vocab = write_rdf(None, path, source_triples=project_drawing(payload, map_objects))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    graph = NS + 'graph:' + sha
    if any(iri.startswith(NS + 'graph:') and iri != graph for iri in manifest['rdf_graphs']):
        raise ValueError('An existing drawing graph has different content; rebuild the review manifest first')
    source_ids = {node['id'] for node in payload['nodes']}
    bridges = sum(obj.get('source_resource_id') in source_ids for obj in map_objects['objects'])
    measurements = sum(node['class_iri'].rsplit(':', 1)[-1].rsplit('/', 1)[-1] == 'Measurement' for node in payload['nodes'])
    expected = {'instances': len(source_ids), 'drawing_relations': len(payload['edges']),
        'measurements': measurements, 'evidence_bridges': bridges}
    if (expected['instances'], expected['drawing_relations'], measurements) != (6297, 10279, 3202):
        raise ValueError('Expected complete reviewed five-drawing evidence bundle')
    edge = f'?e <{RDF.type}> <{RDF.Statement}> . FILTER(STRSTARTS(STR(?e), "{NS}edge:"))'
    patterns = {
        'instances': f'?s <{D.sourceID}> ?id .',
        'drawing_relations': edge,
        'measurements': f'?s <{RDF.type}> <{NS}class:Measurement> .',
        'evidence_bridges': f'?s <{D.hasDrawingEvidence}> ?o .',
        'missing_inverse': edge + f' ?e <{RDF.subject}> ?s ; <{RDF.predicate}> ?p ; <{RDF.object}> ?o . ?p <{OWL.inverseOf}> ?inv . FILTER NOT EXISTS {{ ?o ?inv ?s }}',
        'orphan_targets': edge + f' ?e <{RDF.object}> ?s . FILTER NOT EXISTS {{ ?s <{D.sourceID}> ?id }}',
    }
    nav, checks = load_and_read(endpoint, graph, path, inventory, RUNTIME,
        navigation=DrawingNavigation(), expected_counts=expected, query_patterns=patterns)
    drawing_manifest, drawing_tables = nav.finish()
    if drawing_manifest['counts']['instances'] != 6297 or len(drawing_manifest['external_relations']) != bridges:
        raise ValueError('Drawing navigation lost source evidence or map bridges')
    old = report.get('drawing', {})
    old_relations = old.get('navigation_relations_with_bridges', 0)
    old_triples = old.get('triple_count', 0)
    for table, value in drawing_tables.items():
        value.update(graph_iri=graph, jena_verified=True)
        tables[table] = value
    by_iri = {item['iri']: item for value in tables.values() for item in value['instances']}
    touched = set(drawing_tables)
    for edge in drawing_manifest['external_relations']:
        source = by_iri.get(edge['source_iri'])
        if source is None or source['class_iri'] != edge['source_class_iri']:
            raise ValueError('Exact drawing bridge source not present in verified map graph')
        source['outgoing'] = [item for item in source['outgoing'] if item['edge_iri'] != edge['edge_iri']]
        source['outgoing'].append(edge)
        touched.add(source['table'])
    merge_concepts(manifest, drawing_manifest['concepts'], tables)
    if graph not in manifest['rdf_graphs']: manifest['rdf_graphs'].append(graph)
    relation_total = drawing_manifest['counts']['relations'] + bridges
    manifest['counts']['relations'] += relation_total - old_relations
    manifest['counts']['resolved_relations'] += relation_total - old_relations
    manifest['counts']['triples'] += checks['triple_count'] - old_triples
    manifest['counts'].update(drawing_instances=6297, drawing_measurements=3202,
        drawing_relations=10279, drawing_map_bridges=bridges)
    sizes = dict(report['public_shards']['by_table'])
    for table in touched:
        encoded = json.dumps(tables[table], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        compressed = gzip.compress(encoded, mtime=0)
        if len(compressed) >= 20 * 1024 * 1024: raise ValueError('Drawing class shard exceeds publication limit')
        (data / 'classes' / (table + '.json.gz')).write_bytes(compressed)
        sizes[table] = {'uncompressed': len(encoded), 'compressed': len(compressed)}
    # Include vocabulary from all already verified named graphs. No source-row
    # payload or instance values enter the public vocabulary document.
    vocabulary = Graph().parse(output / 'vocabulary.ttl', format='turtle')
    for stem in ('map', 'demo'):
        g = Graph().parse(RUNTIME / (stem + '-jena-readback.nt'), format='nt')
        subjects = {subject for kind in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology)
            for subject in g.subjects(RDF.type, kind)}
        for subject in subjects:
            for triple in g.triples((subject, None, None)): vocabulary.add(triple)
    for triple in drawing_vocab: vocabulary.add(triple)
    (output / 'vocabulary.ttl').write_bytes((vocabulary.serialize(format='turtle').rstrip() + '\n').encode('utf-8'))
    report['drawing'] = {'graph_iri': graph, 'bundle_sha256': payload['content_sha256'],
        **checks, 'navigation_relations_with_bridges': relation_total}
    report['rdf_graphs'] = manifest['rdf_graphs']
    report['navigation'] = manifest['counts']
    report['public_shards'] = {'files': len(sizes), 'maximum_compressed_bytes': max(v['compressed'] for v in sizes.values()),
        'total_compressed_bytes': sum(v['compressed'] for v in sizes.values()), 'by_table': sizes}
    manifest['checked_at'] = datetime.now(timezone.utc).isoformat()
    report['drawing_verified_at'] = manifest['checked_at']
    (output / 'rdf-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Publish the graph whitelist last, after all corresponding shards exist.
    (data / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result = {'status': 'passed', 'drawing': report['drawing'], 'counts': manifest['counts'],
        'public_gzip_bytes': report['public_shards']['total_compressed_bytes']}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--fuseki', default=DEFAULT_ENDPOINT)
    args = parser.parse_args()
    extend(args.output, args.fuseki)

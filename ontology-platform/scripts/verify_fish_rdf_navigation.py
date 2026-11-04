"""Read-only exhaustive navigation checks across all verified RDF snapshots."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(output):
    output = Path(output)
    data = output / 'data'
    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('jena_verified') or not manifest.get('fuseki_readback'):
        raise ValueError('Navigation source has not passed Jena readback')
    concepts = {item['iri']: item for item in manifest['concepts']}
    if len(concepts) != len(manifest['concepts']): raise ValueError('Duplicate concept')
    instances, hashes, counts, files = {}, {}, Counter(), []
    for concept in concepts.values():
        if not concept['table']: continue
        path = (data / concept['instances_path']).resolve()
        if not path.is_relative_to(data.resolve()) or not path.name.endswith('.json.gz'):
            raise ValueError('Invalid shard path')
        payload = path.read_bytes()
        hashes[concept['table']] = hashlib.sha256(payload).hexdigest()
        table = json.loads(gzip.decompress(payload))
        if table['class_iri'] != concept['iri'] or not table.get('jena_verified'):
            raise ValueError('Unverified or mistyped class shard')
        for item in table['instances']:
            if item['iri'] in instances or item['class_iri'] != concept['iri'] or item['table'] != concept['table']:
                raise ValueError('Duplicate or mistyped instance')
            instances[item['iri']] = item
            counts[item['class_iri']] += 1
            if 'payload' in item.get('provenance', {}): raise ValueError('Raw business payload leaked into public snapshot')
        if len(table['instances']) != concept['instance_count']: raise ValueError('Direct concept count differs')
        files.append({'path': concept['instances_path'], 'bytes': len(payload), 'instances': len(table['instances'])})
    roots = [item['iri'] for item in concepts.values() if item['parent_iri'] is None]
    if roots != [manifest['root_iri']]: raise ValueError('Expected one explicit domain root')
    visited = set()
    def walk(iri):
        if iri in visited: raise ValueError('Repeated or cyclic hierarchy node')
        visited.add(iri)
        item = concepts[iri]
        for child in item['children']:
            if child not in concepts or concepts[child]['parent_iri'] != iri: raise ValueError('Broken concept child/parent')
        total = counts[iri] + sum(walk(child) for child in item['children'])
        if total != item['total_instance_count']: raise ValueError('Transitive concept count differs')
        return total
    if walk(manifest['root_iri']) != len(instances) or visited != set(concepts):
        raise ValueError('Unreachable concepts or instances')
    outgoing, incoming, demo_out, demo_in = Counter(), Counter(), Counter(), Counter()
    unresolved = 0
    for iri, item in instances.items():
        unresolved += len(item.get('unresolved_relations', []))
        for name, field, class_field, counter in [('outgoing', 'target_iri', 'target_class_iri', outgoing),
                ('incoming', 'source_iri', 'source_class_iri', incoming)]:
            for edge in item.get(name, []):
                target = instances.get(edge[field])
                if target is None or target['class_iri'] != edge[class_field]: raise ValueError('Dangling or mistyped relation target')
                key = (edge['edge_iri'], iri, target['iri']) if name == 'outgoing' else (edge['edge_iri'], target['iri'], iri)
                counter[key] += 1
        for edge in item.get('demo_assignments', []):
            if edge['assignment_policy'] != 'balanced_demo_only' or edge['synthetic'] is not True:
                raise ValueError('Demo relation lost its data nature')
            is_out = edge['direction'] == 'outgoing'
            other = edge['target_iri'] if is_out else edge['source_iri']
            target = instances.get(other)
            if target is None: raise ValueError('Dangling demo target')
            expected = edge['target_class_iri'] if is_out else edge['source_class_iri']
            if target['class_iri'] != expected: raise ValueError('Mistyped demo target')
            key = (edge['assignment_iri'], iri, other) if is_out else (edge['assignment_iri'], other, iri)
            (demo_out if is_out else demo_in)[key] += 1
    if outgoing != incoming or any(value != 1 for value in outgoing.values()):
        raise ValueError('Source relationship outward/inward navigation differs')
    if demo_out != demo_in or any(value != 1 for value in demo_out.values()):
        raise ValueError('Demo outward/inward navigation differs')
    expected = manifest['counts']
    if len(instances) != expected['instances'] or sum(outgoing.values()) != expected['resolved_relations']:
        raise ValueError('Manifest navigation totals differ')
    if sum(outgoing.values()) + unresolved != expected['relations'] or len(demo_out) != expected['demo_assignments']:
        raise ValueError('Source/demo relationship totals differ')
    report = {'contract': 'fish-rdf-navigation-readback/1', 'status': 'passed',
        'rdf_graphs': manifest['rdf_graphs'], 'instances_checked': len(instances),
        'concepts_checked': len(concepts), 'resolved_links_checked_both_directions': len(outgoing),
        'unresolved_records_preserved': unresolved, 'demo_links_checked_both_directions': len(demo_out),
        'dangling_links': 0, 'type_mismatches': 0, 'raw_payload_public': False,
        'shard_count': len(files), 'maximum_compressed_bytes': max(item['bytes'] for item in files),
        'total_compressed_bytes': sum(item['bytes'] for item in files), 'shard_sha256': hashes,
        'checked_at': datetime.now(timezone.utc).isoformat()}
    (output / 'navigation-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('rdf_graphs', 'shard_sha256')}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/fish/ontology-review')
    verify(parser.parse_args().output)

"""Read-only exhaustive checks of inline and bounded RDF navigation snapshots.

Recorded Jena markers are prerequisites, not a fresh Jena verification.
Only navigation-readback.json is written; source snapshots are never modified.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_FIELDS = {prefix + '_' + field for prefix in ('source', 'target')
                   for field in ('iri', 'id', 'label', 'class_iri')}


def _safe_path(data, relative, folder):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or PurePosixPath(relative).is_absolute() or any(part in ('', '.', '..') for part in relative.split('/'))
            or not relative.startswith(folder + '/') or not relative.endswith('.json.gz')):
        raise ValueError('Invalid ' + folder + ' path')
    path = (data / relative).resolve()
    if not path.is_relative_to(data.resolve()):
        raise ValueError('Snapshot path escapes data directory')
    return path


def _read(data, relative, folder):
    path = _safe_path(data, relative, folder)
    try:
        payload = path.read_bytes()
        value = json.loads(gzip.decompress(payload))
    except (OSError, EOFError, ValueError) as error:
        raise ValueError('Missing or invalid snapshot: ' + relative) from error
    if not isinstance(value, dict):
        raise ValueError('Snapshot envelope is not an object')
    return value, len(payload), hashlib.sha256(payload).hexdigest()


def _no_raw_payload(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower().replace('_', '').replace('-', '') in {'payload', 'rawpayload', 'rawrecord'}:
                raise ValueError('Raw business payload leaked into public snapshot')
            _no_raw_payload(child)
    elif isinstance(value, list):
        for child in value:
            _no_raw_payload(child)


def _envelope(value, concept, graphs):
    _no_raw_payload({key:child for key, child in value.items() if key != 'instances'})
    if (value.get('contract') != 'fish-rdf-review/1' or value.get('class_iri') != concept['iri']
            or value.get('jena_verified') is not True or value.get('graph_iri') not in graphs
            or not isinstance(value.get('instances'), list)):
        raise ValueError('Unverified or mistyped class/detail shard')


def _identity(item, concept):
    if (not isinstance(item, dict) or not isinstance(item.get('iri'), str) or not item['iri']
            or item.get('class_iri') != concept['iri'] or item.get('table') != concept['table']
            or not isinstance(item.get('id'), str) or not item['id']):
        raise ValueError('Duplicate or mistyped instance')


def _edge_key(edge, item, direction, index, demo=False):
    if not isinstance(edge, dict):
        raise ValueError('Relation edge is not an object')
    other_prefix = 'target' if direction == 'outgoing' else 'source'
    other_iri = edge.get(other_prefix + '_iri')
    other_class = edge.get(other_prefix + '_class_iri')
    if other_iri not in index or index[other_iri] != other_class:
        raise ValueError('Dangling or mistyped relation target')
    key_field = 'assignment_iri' if demo else 'edge_iri'
    if not isinstance(edge.get(key_field), str) or not edge[key_field]:
        raise ValueError('Missing relation identity')
    own = [item['iri'], item['id'], item.get('label'), item['class_iri']]
    other = [other_iri, edge.get(other_prefix + '_id'), edge.get(other_prefix + '_label'), other_class]
    for endpoint in (own, other):
        # Four existing map/drawing bridge IDs use URL-escaped Chinese on the
        # inverse side. Preserve that legacy representation equivalence only;
        # CSV business IDs and all labels remain exact, case-sensitive strings.
        if ':fish-review:map:' in endpoint[3] and isinstance(endpoint[1], str):
            endpoint[1] = unquote(endpoint[1], errors='strict')
    source, target = (own, other) if direction == 'outgoing' else (other, own)
    # Preserve predicate and every common metadata field, including source_row.
    canonical = {key:value for key, value in edge.items() if key not in ENDPOINT_FIELDS and key != 'direction'}
    canonical.update(source_endpoint=source, target_endpoint=target)
    identity = hashlib.sha256(json.dumps([edge[key_field], source[0], target[0]],
                              separators=(',', ':')).encode('utf-8')).digest()
    signature = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode('utf-8')).digest()
    return identity, signature


def verify(output):
    output = Path(output)
    data = output / 'data'
    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('jena_verified') is not True or manifest.get('fuseki_readback') is not True:
        raise ValueError('Navigation source has not passed recorded Jena readback')
    concepts = {item['iri']:item for item in manifest['concepts']}
    if len(concepts) != len(manifest['concepts']):
        raise ValueError('Duplicate concept')
    graphs = set(manifest['rdf_graphs'])
    # Pass one keeps only the IRI -> class index, never every full instance DTO.
    index, hashes, counts, files = {}, {}, Counter(), []
    class_paths = set()
    for concept in concepts.values():
        if not concept['table']:
            continue
        relative = concept['instances_path']
        if relative in class_paths or concept['table'] in hashes:
            raise ValueError('Duplicate class shard path or table')
        class_paths.add(relative)
        table, size, sha = _read(data, relative, 'classes')
        _envelope(table, concept, graphs)
        hashes[concept['table']] = sha
        for item in table['instances']:
            _identity(item, concept)
            if item['iri'] in index:
                raise ValueError('Duplicate or mistyped instance')
            index[item['iri']] = concept['iri']
            counts[concept['iri']] += 1
        if len(table['instances']) != concept['instance_count']:
            raise ValueError('Direct concept count differs')
        files.append(dict(path=relative, bytes=size, instances=len(table['instances'])))
    roots = [item['iri'] for item in concepts.values() if item['parent_iri'] is None]
    if roots != [manifest['root_iri']]:
        raise ValueError('Expected one explicit domain root')
    visited = set()

    def walk(iri):
        if iri in visited:
            raise ValueError('Repeated or cyclic hierarchy node')
        visited.add(iri)
        item = concepts[iri]
        for child in item['children']:
            if child not in concepts or concepts[child]['parent_iri'] != iri:
                raise ValueError('Broken concept child/parent')
        total = counts[iri] + sum(walk(child) for child in item['children'])
        if total != item['total_instance_count']:
            raise ValueError('Transitive concept count differs')
        return total

    if walk(manifest['root_iri']) != len(index) or visited != set(concepts):
        raise ValueError('Unreachable concepts or instances')
    outgoing, incoming, demo_out, demo_in = {}, {}, {}, {}
    detail_hashes, relation_hashes = {}, {}
    detail_sizes, relation_sizes = {}, {}
    unresolved = detail_instances = relation_edges = checked_instances = 0

    def edges(item, direction):
        nonlocal relation_edges
        inline = item.get(direction)
        if not isinstance(inline, list):
            raise ValueError('Complete detail DTO is missing relation arrays')
        pages_field = direction + '_pages'
        count_field = direction + '_count'
        page_size_field = direction + '_page_size'
        if pages_field not in item:
            if page_size_field in item or (count_field in item and (type(item[count_field]) is not int or item[count_field] != len(inline))):
                raise ValueError('Inline relation count differs')
            yield from inline
            return
        pages, count, page_size = item[pages_field], item.get(count_field), item.get(page_size_field)
        if (not isinstance(pages, list) or not pages or len(set(pages)) != len(pages) or inline
                or type(count) is not int or count <= 0 or type(page_size) is not int or page_size != 4800
                or len(pages) != (count + page_size - 1) // page_size):
            raise ValueError('Invalid paged relation declaration')
        for position, relative in enumerate(pages):
            owner = re.escape(str(item.get('uuid') or item['id']))
            if not isinstance(relative, str) or not re.fullmatch(
                    r'relations/' + re.escape(item['table']) + '/' + owner + '/' + direction + '-' + f'{position + 1:05d}' + r'\.json\.gz', relative):
                raise ValueError('Invalid relation page path')
            if relative in relation_hashes:
                raise ValueError('Relation page is reused or duplicated')
            page, size, sha = _read(data, relative, 'relations')
            _no_raw_payload(page)
            if (page.get('contract') != 'fish-rdf-relations/1' or page.get('instance_iri') != item['iri']
                    or page.get('direction') != direction or not isinstance(page.get('edges'), list)
                    or len(page['edges']) != min(page_size, count - position * page_size)):
                raise ValueError('Relation page identity, direction or edge count differs')
            relation_hashes[relative], relation_sizes[relative] = sha, size
            relation_edges += len(page['edges'])
            yield from page['edges']

    def check_instance(item, concept, summary=None, relative=None):
        nonlocal unresolved, checked_instances
        _identity(item, concept)
        _no_raw_payload(item)
        if summary is not None and any(item.get(field) != value for field, value in summary.items()):
            raise ValueError('Detail does not match its unique summary')
        if relative is not None and item.get('detail_path') != relative:
            raise ValueError('Detail row points to a different chunk')
        if not isinstance(item.get('properties'), list) or not isinstance(item.get('provenance'), dict):
            raise ValueError('Incomplete instance detail DTO')
        missing = item.get('unresolved_relations')
        if not isinstance(missing, list) or any(not isinstance(edge, dict) or edge.get('resolution') == 'resolved' for edge in missing):
            raise ValueError('Unresolved source references were not preserved')
        unresolved += len(missing)
        checked_instances += 1
        for direction, counter in [('outgoing', outgoing), ('incoming', incoming)]:
            for edge in edges(item, direction):
                identity, signature = _edge_key(edge, item, direction, index)
                if identity in counter:
                    raise ValueError('Duplicate source relationship')
                counter[identity] = signature
        demo_edges = item.get('demo_assignments', [])
        if not isinstance(demo_edges, list):
            raise ValueError('Invalid demo relationship array')
        for edge in demo_edges:
            if (edge.get('assignment_policy') != 'balanced_demo_only' or edge.get('synthetic') is not True
                    or edge.get('direction') not in {'outgoing', 'incoming'}):
                raise ValueError('Demo relation lost its data nature or direction')
            counter = demo_out if edge['direction'] == 'outgoing' else demo_in
            identity, signature = _edge_key(edge, item, edge['direction'], index, demo=True)
            if identity in counter:
                raise ValueError('Duplicate demo relationship')
            counter[identity] = signature

    # Pass two holds one class summary plus one detail chunk/page at a time.
    for concept in concepts.values():
        if not concept['table']:
            continue
        table, _, sha = _read(data, concept['instances_path'], 'classes')
        if sha != hashes[concept['table']]:
            raise ValueError('Class snapshot changed during readback')
        grouped = defaultdict(dict)
        for summary in table['instances']:
            _no_raw_payload(summary)
            if 'detail_path' not in summary:
                check_instance(summary, concept)
                continue
            relative = summary['detail_path']
            if any(not isinstance(summary.get(field), str) for field in
                   ('iri', 'id', 'label', 'class_iri', 'table', 'nature', 'adoption_status', 'batch_id', 'detail_path')):
                raise ValueError('Incomplete lazy summary contract')
            _safe_path(data, relative, 'details')
            if not re.fullmatch(r'details/' + re.escape(concept['table']) + r'/[0-9]{5}\.json\.gz', relative):
                raise ValueError('Detail path does not belong to the class table')
            grouped[relative][summary['iri']] = summary
        for relative, summaries in grouped.items():
            if relative in detail_hashes:
                raise ValueError('Detail file reused across classes')
            detail, size, sha = _read(data, relative, 'details')
            _envelope(detail, concept, graphs)
            if detail['graph_iri'] != table['graph_iri'] or len(detail['instances']) > 500:
                raise ValueError('Detail graph or chunk size differs')
            seen = set()
            for item in detail['instances']:
                iri = item.get('iri') if isinstance(item, dict) else None
                if iri in seen or iri not in summaries:
                    raise ValueError('Duplicate or unindexed detail instance')
                seen.add(iri)
                check_instance(item, concept, summaries[iri], relative)
            if seen != set(summaries):
                raise ValueError('Detail rows do not completely cover summaries')
            detail_hashes[relative], detail_sizes[relative] = sha, size
            detail_instances += len(seen)
    for folder, loaded in [('details', detail_hashes), ('relations', relation_hashes)]:
        present = {path.relative_to(data).as_posix() for path in (data / folder).rglob('*.json.gz')}
        if present != set(loaded):
            raise ValueError('Unreferenced or missing ' + folder + ' snapshot files')
    if outgoing != incoming:
        raise ValueError('Source relationship outward/inward navigation differs')
    if demo_out != demo_in:
        raise ValueError('Demo outward/inward navigation differs')
    expected = manifest['counts']
    if checked_instances != len(index) or len(index) != expected['instances'] or len(outgoing) != expected['resolved_relations']:
        raise ValueError('Manifest navigation totals differ')
    if len(outgoing) + unresolved != expected['relations'] or len(demo_out) != expected['demo_assignments']:
        raise ValueError('Source/demo relationship totals differ')
    if 'classes' in expected and expected['classes'] != len(concepts):
        raise ValueError('Manifest class count differs')
    report = dict(contract='fish-rdf-navigation-readback/1', status='passed',
        rdf_graphs=manifest['rdf_graphs'], instances_checked=len(index), concepts_checked=len(concepts),
        resolved_links_checked_both_directions=len(outgoing), unresolved_records_preserved=unresolved,
        demo_links_checked_both_directions=len(demo_out), dangling_links=0, type_mismatches=0, raw_payload_public=False,
        shard_count=len(files), maximum_compressed_bytes=max((item['bytes'] for item in files), default=0),
        total_compressed_bytes=sum(item['bytes'] for item in files), shard_sha256=hashes,
        detail_file_count=len(detail_hashes), detail_instances_checked=detail_instances,
        detail_sha256=detail_hashes, detail_compressed_bytes=sum(detail_sizes.values()),
        relation_file_count=len(relation_hashes), relation_edges_checked=relation_edges,
        relation_sha256=relation_hashes, relation_compressed_bytes=sum(relation_sizes.values()),
        jena_readback_scope='Recorded manifest and shard markers only; this navigation check does not perform a fresh Jena query.',
        checked_at=datetime.now(timezone.utc).isoformat())
    (output / 'navigation-readback.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key:value for key, value in report.items() if key not in
                     ('rdf_graphs', 'shard_sha256', 'detail_sha256', 'relation_sha256')}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/fish/ontology-review')
    verify(parser.parse_args().output)

"""Read back the four pre-CSV RDF graphs and compare the captured baseline.

This command has no database connection and no RDF write operation. It uses
only SELECT and Graph Store GET against the fixed loopback fish_l1 dataset.
The reference, including its adjacent graph-inventory.json, must come from the
successful capture made before importing the CSV batch. A new manifest is never
consulted. Raw N-Triples remain beneath .runtime; the public report contains
graph identities, counts and digests only.

Example:
    python scripts/verify_csv_prior_graphs.py \
      --reference .runtime/csv-batch-20261109/baseline/report.json \
      --output .runtime/csv-batch-20261109/after \
      --report docs/csv-batch/prior-graphs-readback.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import httpx
import rdflib
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser

from fish_rdf_sample import triple_digest

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'http://127.0.0.1:23049/fish_l1'
PRIOR_PACKAGE_SHA256 = '04891aab2039607015d41575e292a0add57065af3a2037270893cc0f3cd7c4b7'
CSV_PACKAGE_SHA256 = 'a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524'
NEW_GRAPH_PREFIX = 'urn:lzo:csv-batch:v1:' + CSV_PACKAGE_SHA256 + ':graph:'
DIGEST_ALGORITHM = 'sha256(concat(sort(unique(sha256(json_rdf_term_triple)))))'
INVENTORY_QUERY = 'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g'


class VerificationError(ValueError):
    """Stable public error code; never include source triples or HTTP bodies."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise VerificationError(code)


def validate_paths(reference, output, report, *, root=ROOT):
    root = Path(root).resolve()
    runtime = root / '.runtime'
    reference, output, report = (Path(path).resolve() for path in (reference, output, report))
    require(reference.is_relative_to(runtime) and reference.suffix == '.json',
            'reference_must_be_json_beneath_this_checkout_runtime')
    require(output.is_relative_to(runtime) and output != runtime,
            'output_must_be_beneath_this_checkout_runtime')
    require(not output.is_relative_to(reference.parent) and not reference.parent.is_relative_to(output),
            'output_must_not_overlap_baseline_directory')
    require(report.is_relative_to(root / 'docs/csv-batch') and report.suffix == '.json',
            'report_must_be_json_beneath_docs_csv_batch')
    return reference, output, report


def _valid_inventory(inventory):
    return (isinstance(inventory, dict) and bool(inventory)
            and all(isinstance(graph, str) and bool(graph) and type(count) is int and count > 0
                    for graph, count in inventory.items()))


def compare_inventory(before, after):
    """All old graphs keep their counts; only this reviewed CSV package may add graphs."""
    require(_valid_inventory(before) and _valid_inventory(after), 'invalid_graph_inventory')
    require(all(after.get(graph) == count for graph, count in before.items()), 'old_graph_count_changed_or_missing')
    additional = sorted(set(after) - set(before))
    require(all(re.fullmatch(re.escape(NEW_GRAPH_PREFIX) + '[0-9a-f]{64}', graph) for graph in additional),
            'unapproved_additional_graph')
    return {'old_graph_count': len(before), 'old_graph_counts_unchanged': True,
            'additional_graph_count': len(additional),
            'additional_graphs': [{'graph_iri': graph, 'triple_count': after[graph]} for graph in additional]}


def _read_baseline(reference):
    raw = reference.read_bytes()
    data = json.loads(raw)
    require(isinstance(data, dict) and data.get('contract') == 'csv-prior-graphs-baseline/1'
            and data.get('status') == 'passed' and data.get('mode') == 'read_only'
            and data.get('jena_endpoint') == ENDPOINT
            and data.get('rdf_literal_normalization') is False
            and data.get('inventory_counts_unchanged_during_capture') is True,
            'baseline_not_successful_or_wrong_target')
    inventory_path = reference.parent / 'graph-inventory.json'
    require(inventory_path.resolve().parent == reference.parent, 'baseline_inventory_outside_reference_directory')
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    require(_valid_inventory(inventory) and len(inventory) == 977
            and data.get('jena_nonempty_graph_count') == len(inventory), 'baseline_inventory_incomplete')
    non_review = sum(not graph.startswith('urn:lzo:fish-review:') for graph in inventory)
    require(non_review == 971 and data.get('jena_non_review_graph_count') == non_review,
            'baseline_formal_graph_inventory_incomplete')
    graphs = data.get('graphs')
    require(isinstance(graphs, list) and len(graphs) == 4, 'baseline_requires_four_prior_graphs')
    roles, graph_iris = set(), set()
    for entry in graphs:
        require(isinstance(entry, dict), 'invalid_baseline_graph_entry')
        graph = entry.get('graph_iri')
        require(isinstance(graph, str), 'invalid_baseline_graph_iri')
        sample = re.fullmatch('urn:lzo:fish-review:sample:v1:graph:' + PRIOR_PACKAGE_SHA256 + ':([0-9a-f]{64})', graph)
        other = re.fullmatch(r'urn:lzo:fish-review:(map|demo|drawing):v1:graph:[0-9a-f]{64}', graph)
        require(sample is not None or other is not None, 'baseline_graph_outside_prior_review_package')
        role = 'sample' if sample else other.group(1)
        require(role not in roles and graph not in graph_iris, 'duplicate_baseline_graph')
        roles.add(role)
        graph_iris.add(graph)
        digest = entry.get('rdf_termset_sha256')
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'invalid_baseline_termset_digest')
        require(not sample or sample.group(1) == digest, 'baseline_sample_content_address_mismatch')
        count = entry.get('sparql_count')
        require(type(count) is int and count > 0 and inventory.get(graph) == count
                and entry.get('parsed_triples') == count and entry.get('unique_triples') == count
                and entry.get('termset_status') == 'passed', 'baseline_graph_count_or_readback_incomplete')
        require(isinstance(entry.get('download_sha256'), str)
                and re.fullmatch('[0-9a-f]{64}', entry['download_sha256'])
                and type(entry.get('download_bytes')) is int and entry['download_bytes'] > 0,
                'baseline_rdf_download_proof_missing')
    pg = data.get('postgres', {})
    require(isinstance(pg, dict) and pg.get('database') == 'lzo_gis' and pg.get('server_port') == 25449
            and pg.get('transaction_read_only') == 'on' and pg.get('review_raw_records') == 20606,
            'baseline_postgres_identity_incomplete')
    proof = {'source_archive_sha256': PRIOR_PACKAGE_SHA256,
             'reference_report_sha256': hashlib.sha256(raw).hexdigest(),
             'graph_inventory_sha256': hashlib.sha256(inventory_bytes).hexdigest(),
             'old_graph_count': len(inventory), 'old_non_review_graph_count': non_review,
             'postgres': {key: pg[key] for key in ('database', 'server_port', 'transaction_read_only', 'review_raw_records')}}
    return graphs, inventory, proof


class _Terms:
    def __init__(self):
        self.inventory = set()
        self.count = 0

    def triple(self, s, p, o):
        digest = triple_digest(s, p, o)
        require(digest not in self.inventory, 'duplicate_rdf_triple')
        self.inventory.add(digest)
        self.count += 1


def termset_file(path):
    """Parse actual RDF terms without normalizing decimal/date lexical values."""
    sink = _Terms()
    previous = rdflib.NORMALIZE_LITERALS
    try:
        rdflib.NORMALIZE_LITERALS = False
        with Path(path).open('r', encoding='utf-8') as stream:
            W3CNTriplesParser(sink=sink).parse(stream)
    except VerificationError:
        raise
    except Exception:
        # Parser exceptions can contain the raw RDF line. Keep them private.
        raise VerificationError('rdf_parse_or_term_identity_failed') from None
    finally:
        rdflib.NORMALIZE_LITERALS = previous
    return {'parsed_triples': sink.count, 'unique_triples': len(sink.inventory),
            'rdf_termset_sha256': hashlib.sha256(b''.join(sorted(sink.inventory))).hexdigest()}


def _select_inventory(client):
    response = client.post(ENDPOINT + '/query', data={'query': INVENTORY_QUERY, 'timeout': '600000'},
                           headers={'Accept': 'application/sparql-results+json'})
    response.raise_for_status()
    inventory = {}
    for row in response.json()['results']['bindings']:
        require(row['g'].get('type') == 'uri', 'inventory_graph_must_be_iri')
        graph, raw_count = row['g']['value'], row['n']['value']
        require(graph not in inventory and isinstance(raw_count, str) and re.fullmatch('[1-9][0-9]*', raw_count),
                'duplicate_graph_or_invalid_inventory_count')
        inventory[graph] = int(raw_count)
    require(_valid_inventory(inventory), 'invalid_graph_inventory')
    return inventory


def _download(client, graph, path, output):
    require(path.resolve().parent == output and not path.is_symlink(), 'rdf_output_file_outside_runtime_directory')
    size, digest = 0, hashlib.sha256()
    with client.stream('GET', ENDPOINT + '/data', params={'graph': graph},
                       headers={'Accept': 'application/n-triples', 'Accept-Encoding': 'identity'}) as response:
        response.raise_for_status()
        with path.open('wb') as stream:
            for chunk in response.iter_bytes():
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    return {'download_bytes': size, 'download_sha256': digest.hexdigest()}


def _write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _error_code(error):
    return error.code if isinstance(error, VerificationError) else type(error).__name__


def verify(reference, output, report, *, root=ROOT, transport=None):
    """Return evidence with passed/failed status. The transport hook is for offline checks."""
    reference, output, report = validate_paths(reference, output, report, root=root)
    result = {'contract': 'csv-prior-graphs-readback/1', 'status': 'running', 'mode': 'read_only',
              'started_at': datetime.now(timezone.utc).isoformat(), 'jena_endpoint': ENDPOINT,
              'csv_source_archive_sha256': CSV_PACKAGE_SHA256,
              'rdf_literal_normalization': False, 'digest_algorithm': DIGEST_ALGORITHM,
              'coverage': {'old_manifest_graphs': 'complete RDF termset and counts',
                           'all_other_old_graphs': 'inventory counts only'},
              'graphs': [], 'errors': []}
    _write_report(report, result)  # Invalidate a stale passed report before reading or contacting a service.
    try:
        graphs, prior_inventory, proof = _read_baseline(reference)
        result['baseline'] = proof
        output.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=httpx.Timeout(600, connect=10), trust_env=False,
                          follow_redirects=False, transport=transport) as client:
            before = _select_inventory(client)
            result['inventory_before'] = compare_inventory(prior_inventory, before)
            for index, expected in enumerate(graphs, start=1):
                entry = {'graph_iri': expected['graph_iri'], 'status': 'running',
                         'expected_triples': expected['sparql_count'],
                         'expected_rdf_termset_sha256': expected['rdf_termset_sha256'],
                         'baseline_download_sha256': expected['download_sha256'],
                         'baseline_download_bytes': expected['download_bytes'],
                         'sparql_count': before[expected['graph_iri']]}
                result['graphs'].append(entry)
                try:
                    path = output / ('graph-' + str(index) + '.nt')
                    entry.update(_download(client, entry['graph_iri'], path, output))
                    entry.update(termset_file(path))
                    equal = (entry['parsed_triples'] == entry['expected_triples'] == entry['unique_triples']
                             and entry['rdf_termset_sha256'] == entry['expected_rdf_termset_sha256'])
                    entry['status'] = 'passed' if equal else 'failed'
                    if not equal:
                        result['errors'].append({'code': 'prior_graph_termset_or_count_changed', 'graph_index': index})
                except Exception as error:
                    entry['status'] = 'failed'
                    result['errors'].append({'code': _error_code(error), 'graph_index': index})
                _write_report(report, result)
            after = _select_inventory(client)
            result['inventory_after'] = compare_inventory(prior_inventory, after)
            result['inventory_stable_during_readback'] = before == after
            require(before == after, 'inventory_changed_during_readback')
        result['status'] = 'failed' if result['errors'] else 'passed'
    except Exception as error:
        result['status'] = 'failed'
        result['errors'].append({'code': _error_code(error)})
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    _write_report(report, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.reference, args.output, args.report)
    except ValueError as error:
        parser.error(_error_code(error))
    print(json.dumps({'status': result['status'], 'graphs_checked': len(result['graphs']), 'errors': result['errors']}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

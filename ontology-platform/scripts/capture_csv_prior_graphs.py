"""Capture an environment-specific read-only baseline before receiving the CSV batch."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import httpx
import rdflib
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from fish_review_config import load_config, database_url
from fish_rdf_sample import triple_digest

# Term identity must retain decimal/date lexical values supplied by Jena.
ENDPOINT = 'http://127.0.0.1:23049/fish_l1'
OUT = ROOT / '.runtime/csv-batch-20261109/baseline'


def write_report(report):
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def select(client, query):
    response = client.post(ENDPOINT + '/query', data={'query': query, 'timeout': '600000'},
        headers={'Accept': 'application/sparql-results+json'})
    response.raise_for_status()
    return response.json()


class Terms:
    def __init__(self):
        self.inventory = set()
        self.count = 0

    def triple(self, s, p, o):
        self.inventory.add(triple_digest(s, p, o))
        self.count += 1
        if self.count % 500000 == 0:
            print(json.dumps({'stage': 'parsed', 'triples': self.count}), flush=True)


def capture_destination(path, *, root=ROOT):
    path=Path(path).resolve();runtime=(Path(root)/'.runtime').resolve()
    if not path.is_relative_to(runtime) or path==runtime or (path/'report.json').exists():
        raise ValueError('Use a new private runtime directory; existing baseline evidence is immutable')
    return path


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();OUT=capture_destination(args.output);OUT.mkdir(parents=True,exist_ok=True)
    start = time.monotonic()
    manifest = json.loads((ROOT / 'docs/fish/ontology-review/data/manifest.json').read_text(encoding='utf-8'))
    graphs = manifest.get('legacy_graphs', manifest['rdf_graphs'])
    if len(graphs)!=4 or any(not g.startswith('urn:lzo:fish-review:') for g in graphs):
        raise ValueError('The prior review must contain its four known graph families')
    report = {'contract': 'csv-prior-graphs-baseline/1', 'mode': 'read_only',
        'started_at': datetime.now(timezone.utc).isoformat(), 'jena_endpoint': ENDPOINT,
        'rdf_literal_normalization': False, 'digest_algorithm': 'sha256(concat(sort(unique(sha256(json_rdf_term_triple)))))',
        'graphs': []}
    config = load_config()
    url = database_url(config)
    if make_url(url).port != 25449:
        raise ValueError('Unexpected PostgreSQL port')
    engine = create_engine(url, hide_parameters=True,
        connect_args={'hostaddr': '127.0.0.1', 'connect_timeout': 10})
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            identity = conn.execute(text("SELECT current_database() AS database, current_user AS db_user, inet_server_addr()::text AS server_addr, inet_server_port() AS server_port, current_setting('transaction_read_only') AS transaction_read_only, version() AS version")).mappings().one()
            if identity['transaction_read_only'] != 'on':
                raise ValueError('PostgreSQL transaction must be read-only')
            report['postgres'] = dict(identity)
            report['postgres']['review_raw_records'] = conn.execute(text('SELECT COUNT(*) FROM fish_review_10pct_v1.raw_records')).scalar_one()
    finally:
        engine.dispose()
    with httpx.Client(timeout=httpx.Timeout(600, connect=10), trust_env=False) as client:
        grouped = select(client, 'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g')
        inventory = {r['g']['value']: int(r['n']['value']) for r in grouped['results']['bindings']}
        report['jena_nonempty_graph_count'] = len(inventory)
        report['jena_non_review_graph_count'] = sum(not g.startswith(('urn:lzo:fish-review:', 'urn:lzo:csv-batch:')) for g in inventory)
        report['jena_non_review_triples'] = sum(n for g, n in inventory.items() if not g.startswith(('urn:lzo:fish-review:', 'urn:lzo:csv-batch:')))
        (OUT / 'graph-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
        for index, graph in enumerate(graphs):
            report['graphs'].append({'graph_iri': graph, 'sparql_count': inventory.get(graph, 0), 'termset_status': 'pending'})
        write_report(report)
        print(json.dumps({'stage': 'identity_counts', **report}, ensure_ascii=False), flush=True)
        for index, entry in enumerate(report['graphs'], start=1):
            graph = entry['graph_iri']
            path = OUT / ('graph-' + str(index) + '.nt')
            file_sha = hashlib.sha256()
            size = 0
            with client.stream('GET', ENDPOINT + '/data', params={'graph': graph},
                    headers={'Accept': 'application/n-triples', 'Accept-Encoding': 'identity'}) as response:
                response.raise_for_status()
                with path.open('wb') as stream:
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
                        file_sha.update(chunk)
                        size += len(chunk)
            print(json.dumps({'stage': 'downloaded', 'graph': index, 'bytes': size}), flush=True)
            sink = Terms()
            prior_normalization=rdflib.NORMALIZE_LITERALS
            try:
                rdflib.NORMALIZE_LITERALS=False
                with path.open('r', encoding='utf-8') as stream:
                    W3CNTriplesParser(sink=sink).parse(stream)
            finally:
                rdflib.NORMALIZE_LITERALS=prior_normalization
            unique = len(sink.inventory)
            termset_sha = hashlib.sha256(b''.join(sorted(sink.inventory))).hexdigest()
            if sink.count != entry['sparql_count'] or unique != sink.count:
                raise ValueError('RDF stream/count/unique mismatch for graph ' + str(index))
            entry.update({'parsed_triples': sink.count, 'unique_triples': unique,
                'rdf_termset_sha256': termset_sha, 'download_file': path.name,
                'download_sha256': file_sha.hexdigest(), 'download_bytes': size, 'termset_status': 'passed'})
            write_report(report)
            print(json.dumps({'stage': 'graph_complete', **entry}), flush=True)
        after = select(client, 'SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g')
        after_inventory = {r['g']['value']: int(r['n']['value']) for r in after['results']['bindings']}
        report['inventory_counts_unchanged_during_capture'] = after_inventory == inventory
        if not report['inventory_counts_unchanged_during_capture']:
            raise ValueError('Graph inventory changed during baseline capture')
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    report['elapsed_seconds'] = round(time.monotonic() - start, 2)
    report['status'] = 'passed'
    write_report(report)
    print(json.dumps({'stage': 'baseline_complete', 'status': 'passed', 'elapsed_seconds': report['elapsed_seconds']}), flush=True)


if __name__ == '__main__':
    main()

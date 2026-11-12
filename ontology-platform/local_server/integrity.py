"""Bounded file and lexical RDF dataset verification (never RDFLib normalization).

The dataset hash externally sorts fixed-size quad hashes before SHA256. Blank node refinement uses a
temporary SQLite spool, shared across all named and default graphs. Ambiguous
labellings are exhaustively compared only within an explicit work limit; larger
cases fail closed rather than claiming that a label-sensitive hash is portable.
"""
from __future__ import annotations

from contextlib import ExitStack
import gzip
import hashlib
import heapq
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
from uuid import uuid4


class IntegrityError(ValueError):
    pass


def sha256_file(path, *, chunk_bytes=1024 * 1024):
    digest, size = hashlib.sha256(), 0
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(chunk_bytes), b''):
            digest.update(block)
            size += len(block)
    return {'sha256': digest.hexdigest(), 'size_bytes': size}


_IRI = r'<(?:[^<>"{}|^`\\\x00-\x20]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*>'
_BNODE = r'_:[A-Za-z0-9_\u0080-\uffff](?:[A-Za-z0-9_\-\.\u0080-\uffff]*[A-Za-z0-9_\-\u0080-\uffff])?'
_LITERAL = r'"(?:[^"\\\r\n]|\\[tbnrf"\x27\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*"(?:@[A-Za-z]+(?:-[A-Za-z0-9]+)*|\^\^' + _IRI + r')?'
_QUAD = re.compile(r'^\s*(' + _IRI + '|' + _BNODE + r')\s+(' + _IRI + r')\s+(' + _IRI + '|' + _BNODE + '|' + _LITERAL + r')(?:\s+(' + _IRI + '|' + _BNODE + r'))?\s*\.\s*(?:#.*)?$')
_MODULUS = 1 << 256
_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|.)')


def _unescape(value):
    escapes = {'t': '\t', 'b': '\b', 'n': '\n', 'r': '\r', 'f': '\f', '"': '"', "'": "'", '\\': '\\'}
    def replace(match):
        escaped = match.group()[1:]
        if escaped[0] in {'u', 'U'}:
            point = int(escaped[1:], 16)
            if point > 0x10ffff or 0xd800 <= point <= 0xdfff:
                raise IntegrityError('RDF_INVALID_UNICODE_ESCAPE')
            return chr(point)
        return escapes[escaped]
    return _ESCAPE.sub(replace, value)


def _normalize_term(term):
    if term is None or term.startswith('_:'):
        return term
    if term.startswith('<'):
        iri = _unescape(term[1:-1])
        if not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', iri):
            raise IntegrityError('RDF_RELATIVE_IRI_UNSUPPORTED')
        return '<' + iri + '>'
    literal = re.fullmatch(r'"((?:[^"\\]|\\.)*)"(.*)', term)
    value, suffix = literal.groups()
    suffix = suffix.lower() if suffix.startswith('@') else ('^^' + _normalize_term(suffix[2:]) if suffix.startswith('^^') else '')
    # Decode only N-Quads escape syntax, never coerce an RDF datatype value.
    return json.dumps(_unescape(value), ensure_ascii=False) + suffix


class _Multiset:
    def __init__(self):
        self.count = self.total = self.squares = 0

    def add(self, text):
        value = int.from_bytes(hashlib.sha256(text.encode('utf-8')).digest(), 'big')
        self.count += 1
        self.total = (self.total + value) % _MODULUS
        self.squares = (self.squares + value * value) % _MODULUS

    def digest(self):
        return hashlib.sha256(f'nq-multiset-sha256-v1:{self.count}:{self.total:064x}:{self.squares:064x}'.encode('ascii')).hexdigest()


class _SortedHashes:
    """SHA256 of externally sorted 32-byte quad hashes, with bounded fan-in."""
    def __init__(self, root, chunk_quads, open_chunks):
        if chunk_quads < 1 or open_chunks < 2:
            raise IntegrityError('RDF_INVALID_CHUNK_LIMIT')
        self.root, self.chunk_quads, self.open_chunks = Path(root), chunk_quads, open_chunks
        self.pending, self.chunks = [], []
        self.count = 0

    def add(self, text):
        self.pending.append(hashlib.sha256(text.encode('utf-8')).digest())
        self.count += 1
        if len(self.pending) >= self.chunk_quads:
            self._flush()

    def _flush(self):
        if not self.pending:
            return
        path = self.root / ('hashes-' + uuid4().hex)
        with path.open('wb') as output:
            for value in sorted(self.pending):
                output.write(value)
        self.chunks.append(path)
        self.pending.clear()

    @staticmethod
    def _records(stream):
        while True:
            value = stream.read(32)
            if not value:
                return
            if len(value) != 32:
                raise IntegrityError('RDF_HASH_CHUNK_TRUNCATED')
            yield value

    def _merge(self, paths):
        target = self.root / ('merge-' + uuid4().hex)
        with ExitStack() as stack, target.open('wb') as output:
            streams = [stack.enter_context(path.open('rb')) for path in paths]
            for value in heapq.merge(*(self._records(stream) for stream in streams)):
                output.write(value)
        for path in paths:
            path.unlink()
        return target

    def digest(self):
        self._flush()
        while len(self.chunks) > self.open_chunks:
            self.chunks = [self._merge(self.chunks[start:start + self.open_chunks]) for start in range(0, len(self.chunks), self.open_chunks)]
        digest = hashlib.sha256(b'nq-lexical-sorted-sha256-v1\x00' + self.count.to_bytes(8, 'big'))
        with ExitStack() as stack:
            streams = [stack.enter_context(path.open('rb')) for path in self.chunks]
            for value in heapq.merge(*(self._records(stream) for stream in streams)):
                digest.update(value)
        return digest.hexdigest()


def _line(terms, labels=None):
    return ' '.join((labels.get(t, t) if labels else t) for t in terms if t is not None) + ' .'


def _canonical_labels(db, max_permutations):
    count = db.execute('SELECT count(*) FROM nodes').fetchone()[0]
    if not count:
        return {}
    distinct = 1
    # Refinement never loads the graph or the complete bnode label map in RAM.
    for _ in range(64):
        db.execute('UPDATE nodes SET next_color=NULL')
        for (node, color) in db.execute('SELECT label,color FROM nodes ORDER BY label'):
            adjacency = _Multiset()
            for row in db.execute('SELECT q.a,q.b,q.c,q.d FROM quads q JOIN edges e ON e.qid=q.id WHERE e.node=?', (node,)):
                terms = []
                for term in row:
                    if term == node:
                        terms.append('_:SELF')
                    elif term and term.startswith('_:'):
                        terms.append('_:' + db.execute('SELECT color FROM nodes WHERE label=?', (term,)).fetchone()[0])
                    else:
                        terms.append(term)
                adjacency.add(_line(terms))
            next_color = hashlib.sha256((color + adjacency.digest()).encode('ascii')).hexdigest()
            db.execute('UPDATE nodes SET next_color=? WHERE label=?', (next_color, node))
        next_distinct = db.execute('SELECT count(DISTINCT next_color) FROM nodes').fetchone()[0]
        db.execute('UPDATE nodes SET color=next_color')
        if next_distinct == count or next_distinct == distinct:
            break
        distinct = next_distinct
    else:
        raise IntegrityError('RDF_BLANK_NODE_REFINEMENT_LIMIT')
    # Only ambiguous label classes require a small, bounded in-memory map.
    if db.execute('SELECT count(DISTINCT color) FROM nodes').fetchone()[0] == count:
        db.execute("UPDATE nodes SET canonical='_:c' || color")
        return None
    if count > 64:
        raise IntegrityError('RDF_BLANK_NODE_CANONICALIZATION_LIMIT')
    classes = db.execute('SELECT color,count(*) FROM nodes GROUP BY color ORDER BY color').fetchall()
    permutations = math.prod(math.factorial(size) for _, size in classes)
    if permutations > max_permutations:
        raise IntegrityError('RDF_BLANK_NODE_CANONICALIZATION_LIMIT')
    groups = [(color, [r[0] for r in db.execute('SELECT label FROM nodes WHERE color=? ORDER BY label', (color,))]) for color, _ in classes]
    best = best_labels = None
    for candidate in itertools.product(*(itertools.permutations(nodes) for _, nodes in groups)):
        labels = {node: f'_:c{color}_{index}' for (color, _), nodes in zip(groups, candidate) for index, node in enumerate(nodes)}
        digest = _Multiset()
        for row in db.execute('SELECT a,b,c,d FROM quads'):
            digest.add(_line(row, labels))
        value = digest.digest()
        if best is None or value < best:
            best, best_labels = value, labels
    return best_labels


def rdf_dataset_digest(path, *, work_dir=None, max_blank_permutations=10000, max_line_bytes=16 * 1024 * 1024, max_named_graphs=100000, max_chunk_quads=65536, max_open_chunks=32):
    """Read gzip/plain N-Quads in bounded space, preserving RDF lexical terms.

    Triple/quad order and bnode labels may change. RDF-star, malformed N-Quads,
    oversized statements and bnode symmetry beyond the configured bound refuse.
    """
    path = Path(path)
    graphs = {}
    default_count = 0
    with tempfile.TemporaryDirectory(prefix='rdf-integrity-', dir=work_dir) as scratch:
        accumulator = _SortedHashes(scratch, max_chunk_quads, max_open_chunks)
        db = sqlite3.connect(str(Path(scratch) / 'bnode.sqlite3'))
        try:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-4096; CREATE TABLE quads(id INTEGER PRIMARY KEY,a TEXT,b TEXT,c TEXT,d TEXT); CREATE TABLE nodes(label TEXT PRIMARY KEY,color TEXT NOT NULL,next_color TEXT,canonical TEXT); CREATE TABLE edges(node TEXT,qid INTEGER); CREATE INDEX edges_node ON edges(node);')
            opener = gzip.open if path.suffix == '.gz' else open
            try:
                with opener(path, 'rb') as stream:
                    number = 0
                    while True:
                        raw = stream.readline(max_line_bytes + 1)
                        if not raw:
                            break
                        number += 1
                        if len(raw) > max_line_bytes:
                            raise IntegrityError('RDF_STATEMENT_SIZE_LIMIT')
                        text = raw.decode('utf-8').strip()
                        if not text or text.startswith('#'):
                            continue
                        match = _QUAD.fullmatch(text)
                        if not match:
                            raise IntegrityError(f'RDF_UNSUPPORTED_OR_INVALID_NQUADS_LINE_{number}')
                        terms = tuple(_normalize_term(term) for term in match.groups())
                        nodes = {t for t in terms if t and t.startswith('_:')}
                        if nodes:
                            qid = db.execute('INSERT INTO quads(a,b,c,d) VALUES (?,?,?,?)', terms).lastrowid
                            db.executemany("INSERT OR IGNORE INTO nodes(label,color) VALUES (?,'b')", ((n,) for n in nodes))
                            db.executemany('INSERT INTO edges(node,qid) VALUES (?,?)', ((n, qid) for n in nodes))
                        else:
                            accumulator.add(_line(terms))
                            if terms[3] is None:
                                default_count += 1
                            else:
                                graphs[terms[3]] = graphs.get(terms[3], 0) + 1
                                if len(graphs) > max_named_graphs:
                                    raise IntegrityError('RDF_NAMED_GRAPH_METADATA_LIMIT')
            except (UnicodeError, OSError, EOFError) as error:
                raise IntegrityError('RDF_STREAM_INVALID_OR_TRUNCATED') from error
            labels = _canonical_labels(db, max_blank_permutations)
            for row in db.execute('SELECT a,b,c,d FROM quads'):
                canonical = {}
                for term in row:
                    if term and term.startswith('_:'):
                        canonical[term] = labels[term] if labels is not None else db.execute('SELECT canonical FROM nodes WHERE label=?', (term,)).fetchone()[0]
                accumulator.add(_line(row, canonical))
                if row[3] is None:
                    default_count += 1
                else:
                    graph = canonical.get(row[3], row[3])
                    graphs[graph] = graphs.get(graph, 0) + 1
                    if len(graphs) > max_named_graphs:
                        raise IntegrityError('RDF_NAMED_GRAPH_METADATA_LIMIT')
            return {'algorithm': 'nq-lexical-sorted-sha256-v1', 'dataset_sha256': accumulator.digest(), 'quad_count': accumulator.count, 'blank_node_count': db.execute('SELECT count(*) FROM nodes').fetchone()[0], 'default_graph_quad_count': default_count, 'named_graphs': [{'graph': graph, 'quad_count': graphs[graph]} for graph in sorted(graphs)]}
        finally:
            db.close()

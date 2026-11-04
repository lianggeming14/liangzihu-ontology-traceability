"""Actual SHACL validation of every canonical instance from Jena readback."""
from collections import defaultdict
import time

import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL

from fish_rdf_sample import NS, V, PROV, datatype, uri

SH = Namespace('http://www.w3.org/ns/shacl#')


def shapes(schema, vocabulary):
    graph = Graph()
    graph.bind('sh', SH)
    graph.bind('review', V)
    for table, spec in schema['tables'].items():
        shape = uri('shape', table)
        graph.add((shape, RDF.type, SH.NodeShape))
        graph.add((shape, SH.targetClass, uri('class', table)))
        graph.add((shape, SH.nodeKind, SH.IRI))
        for field, definition in spec['columns'].items():
            prop = uri('shape-property', table, field)
            graph.add((shape, SH.property, prop))
            graph.add((prop, SH.path, uri('property', table, field)))
            graph.add((prop, SH.datatype, datatype(definition)))
            graph.add((prop, SH.maxCount, Literal(1)))
    for predicate in vocabulary.subjects(RDF.type, OWL.ObjectProperty):
        owner = vocabulary.value(predicate, RDFS.domain)
        target = vocabulary.value(predicate, RDFS.range)
        if owner is None or target is None or not str(owner).startswith(NS + 'class:'): continue
        table = str(owner).removeprefix(NS + 'class:')
        if table not in schema['tables']: continue
        shape = uri('shape', table)
        prop = URIRef(str(predicate) + ':shape')
        graph.add((shape, SH.property, prop))
        graph.add((prop, SH.path, predicate))
        graph.add((prop, SH['class'], target))
        graph.add((prop, SH.nodeKind, SH.IRI))
    return graph


def validate_canonical(navigation, shape_graph, *, progress=None):
    """Partition by owner class, retaining all target types for SHACL class checks.

    The union of checked partitions is the complete canonical instance scope.
    Original source strings/issue records are deliberately not datatype targets.
    """
    from pyshacl import validate
    started = time.monotonic()
    by_class, types = defaultdict(list), []
    for subject, predicates in navigation.records.items():
        if not subject.startswith(NS + 'instance:'): continue
        for cls in predicates.get(str(RDF.type), []):
            types.append((URIRef(subject), RDF.type, cls))
            by_class[str(cls)].append(subject)
    report = {'engine': 'pyshacl', 'scope': 'all canonical instance datatypes/cardinalities and relation target classes; raw source strings excluded',
        'status': 'passed', 'classes': [], 'instances_validated': 0, 'violations': 0,
        'datatype_constraints': len(list(shape_graph.triples((None, SH.datatype, None)))),
        'relation_class_constraints': len(list(shape_graph.triples((None, SH['class'], None))))}
    prior = rdflib.NORMALIZE_LITERALS
    try:
        for shape in sorted(shape_graph.subjects(RDF.type, SH.NodeShape), key=str):
            cls = shape_graph.value(shape, SH.targetClass)
            subjects = by_class.get(str(cls), [])
            data, selected = Graph(), Graph()
            for triple in types: data.add(triple)
            for subject in subjects:
                for predicate, values in navigation.records[subject].items():
                    # Exact triples read back from Jena, not values reprojected from SQL.
                    if predicate.startswith(NS + 'property:') or predicate.startswith(NS + 'relation:') or predicate == str(PROV.wasDerivedFrom):
                        for value in values: data.add((URIRef(subject), URIRef(predicate), value))
            for triple in shape_graph.triples((shape, None, None)): selected.add(triple)
            for prop in shape_graph.objects(shape, SH.property):
                for triple in shape_graph.triples((prop, None, None)): selected.add(triple)
            conforms, result_graph, result_text = validate(data, shacl_graph=selected, inference='none',
                abort_on_first=False, allow_infos=False, allow_warnings=False, advanced=False)
            violations = len(list(result_graph.subjects(RDF.type, SH.ValidationResult)))
            report['classes'].append({'class_iri': str(cls), 'instances': len(subjects),
                'conforms': bool(conforms), 'violations': violations})
            report['instances_validated'] += len(subjects)
            report['violations'] += violations
            if progress: progress({'stage': 'shacl_class', 'class_iri': str(cls), 'instances': len(subjects), 'conforms': bool(conforms)})
            if not conforms:
                report['status'] = 'failed'
                report.setdefault('failures', []).append(result_text[:12000])
    finally:
        rdflib.NORMALIZE_LITERALS = prior
    report['seconds'] = round(time.monotonic() - started, 2)
    return report

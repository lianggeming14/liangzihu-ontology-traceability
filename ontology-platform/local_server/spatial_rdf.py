"""CAD candidate vocabulary, private provenance, SHACL and immutable RDF load.

Source payloads stay in the private SQL copy. This graph carries provenance
identifiers and evidence, never a claim that CAD candidates are installed assets.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import httpx
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SH, XSD
from rdflib.plugins.serializers.nt import _quoteLiteral

from .rdf import save_json, verify_readback
from .importer import canonical_hash, file_hash
from fish_rdf_sample import triple_digest

NS = 'urn:lzo:cad-gis:v1:'
V = Namespace(NS + 'property:')
C = Namespace(NS + 'class:')
PROV = Namespace('http://www.w3.org/ns/prov#')
GEO = Namespace('http://www.opengis.net/ont/geosparql#')
LABELS = {'candidate':'CAD 空间候选对象', 'field':'CAD 田块候选', 'pond':'CAD 塘池候选',
          'facility':'CAD 设施候选', 'camera':'CAD 摄像头符号候选', 'road':'CAD 道路候选',
          'canal':'CAD 沟渠候选', 'region':'来源图纸分组'}
RELATIONS = {'sourceDiagramRegion':'所属来源图纸分组', 'spatiallyWithinCandidate':'候选空间覆盖关系'}


def vocabulary():
    graph = Graph()
    graph.add((URIRef(NS), RDF.type, OWL.Ontology))
    for key,label in LABELS.items():
        graph.add((C[key], RDF.type, OWL.Class))
        graph.add((C[key], RDFS.label, Literal(label)))
        if key != 'candidate': graph.add((C[key], RDFS.subClassOf, C.candidate))
    for key,label in RELATIONS.items():
        graph.add((V[key], RDF.type, OWL.ObjectProperty))
        graph.add((V[key], RDFS.label, Literal(label)))
        graph.add((V[key], RDFS.domain, C.candidate))
        graph.add((V[key], RDFS.range, C.region if key=='sourceDiagramRegion' else C.candidate))
    for key in ('area_m2','perimeter_m','length_m','depth_m','measurementMethod','measurementUnits','measurementAssumptions',
                'sourceDeclaredMeasurements','dataNature','positionStatus','sourceEvidence','attributes','geometryEvidence','relationEvidence','quality'):
        graph.add((V[key], RDF.type, OWL.DatatypeProperty))
        graph.add((V[key], RDFS.label, Literal(key)))
        if key in ('area_m2','perimeter_m','length_m','depth_m'): graph.add((V[key],RDFS.range,XSD.decimal))
    return graph


def _literal(value):
    return Literal(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False),datatype=RDF.JSON)


def project_cad(bundle):
    yield from vocabulary()
    for obj in bundle['objects']:
        iri=URIRef(obj['iri'])
        yield iri,RDF.type,URIRef(obj['class_iri'])
        yield iri,RDFS.label,Literal(obj['label'])
        yield iri,V.dataNature,Literal(obj['nature'])
        yield iri,V.positionStatus,Literal(obj['position_status'])
        yield iri,V.sourceEvidence,_literal(obj.get('source_refs',[]))
        yield iri,V.attributes,_literal(obj.get('attributes',{}))
        for source in obj.get('source_record_ids',[]):
            yield iri,PROV.wasDerivedFrom,URIRef(source)
        if obj.get('geometry') is not None:
            yield iri,V.geometryEvidence,_literal({'display_srid':4326,'registration_status':'candidate_approximate',
                                                   'original_cad_crs_status':'UNKNOWN','geometry':obj['geometry']})
        attributes=obj.get('attributes',{})
        measured=attributes.get('computed_measurements',{})
        for key in ('area_m2','perimeter_m','length_m','depth_m'):
            value=measured.get(key,attributes.get(key))
            if value is not None:
                yield iri,V[key],Literal(str(value),datatype=XSD.decimal)
        if measured.get('method'): yield iri,V.measurementMethod,Literal(measured['method'])
        if measured.get('units'): yield iri,V.measurementUnits,_literal(measured['units'])
        if measured.get('assumptions'): yield iri,V.measurementAssumptions,Literal(measured['assumptions'])
        source_measurements=[{key:row[key] for key in ('measure_type','measure_value','measure_unit') if key in row}
                             for row in attributes.get('source_values',[]) if any(key in row for key in ('measure_type','measure_value','measure_unit'))]
        if source_measurements: yield iri,V.sourceDeclaredMeasurements,_literal(source_measurements)
    for row in bundle['source_records']:
        iri=URIRef(row['id'])
        yield iri,RDF.type,PROV.Entity
        yield iri,V.sourceEvidence,_literal({key:row[key] for key in ('file_id','table','row_number','status','issues') if key in row})
    for relation in bundle['relations']:
        subject,predicate,target=map(URIRef,(relation['subject'],relation['predicate'],relation['object']))
        yield subject,predicate,target
        statement=URIRef(NS+'statement:'+canonical_hash(relation))
        yield statement,RDF.type,RDF.Statement
        yield statement,RDF.subject,subject
        yield statement,RDF.predicate,predicate
        yield statement,RDF.object,target
        yield statement,V.relationEvidence,_literal(relation)
    yield URIRef(NS+'batch:'+bundle['batch_id']),V.quality,_literal(bundle['quality'])


def cad_shapes():
    graph=Graph()
    for key in LABELS:
        if key=='candidate': continue
        node=URIRef(NS+'shape:'+key)
        graph.add((node,RDF.type,SH.NodeShape)); graph.add((node,SH.targetClass,C[key]))
        for prop,datatype,required in [(RDFS.label,XSD.string,True),(V.dataNature,XSD.string,True),
            (V.positionStatus,XSD.string,True),(V.area_m2,XSD.decimal,False),
            (V.perimeter_m,XSD.decimal,False),(V.length_m,XSD.decimal,False),(V.depth_m,XSD.decimal,False)]:
            shape=URIRef(str(node)+':'+str(prop).rsplit(':',1)[-1].rsplit('#',1)[-1])
            graph.add((node,SH.property,shape)); graph.add((shape,SH.path,prop))
            graph.add((shape,SH.datatype,datatype)); graph.add((shape,SH.maxCount,Literal(1)))
            if required: graph.add((shape,SH.minCount,Literal(1)))
    return graph


def validate_cad_rdf(bundle, graph):
    from pyshacl import validate
    conforms,_,report=validate(graph,shacl_graph=cad_shapes(),inference='none',abort_on_first=False)
    if not conforms: raise ValueError('CAD SHACL validation failed: '+str(report)[:500])
    objects={row['iri']:row for row in bundle['objects']}
    for iri,row in objects.items():
        if (URIRef(iri),RDF.type,URIRef(row['class_iri'])) not in graph:
            raise ValueError('CAD SHACL target instance is missing')
    for row in bundle['relations']:
        if row['subject'] not in objects or row['object'] not in objects:
            raise ValueError('CAD relation endpoint missing')
    return {'status':'passed','instances_validated':len(objects),'engine':'pyshacl',
            'data_nature':'cad_candidate_unverified','raw_payload_public':False}


def generate_cad_rdf(bundle, directory, *, parent_class_iri=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    path=directory/'batch.nt'; inventory=directory/'term-inventory.sqlite3'
    graph=Graph()
    for triple in project_cad(bundle): graph.add(triple)
    if parent_class_iri:
        from .query import checked_iri
        graph.add((C.candidate,RDFS.subClassOf,URIRef(checked_iri(parent_class_iri))))
    shacl=validate_cad_rdf(bundle,graph)
    with sqlite3.connect(inventory) as db, path.open('w',encoding='utf-8',newline='\n') as stream:
        db.execute('CREATE TABLE IF NOT EXISTS terms(digest BLOB PRIMARY KEY,seen INTEGER NOT NULL DEFAULT 0) WITHOUT ROWID')
        db.execute('DELETE FROM terms')
        # Stable serialization makes retry identity independent of hash/random ordering.
        for s,p,o in sorted(graph,key=lambda triple:tuple(term.n3() for term in triple)):
            db.execute('INSERT INTO terms(digest) VALUES(?)',(triple_digest(s,p,o),))
            stream.write(s.n3()+' '+p.n3()+' '+(_quoteLiteral(o) if isinstance(o,Literal) else o.n3())+' .\n')
        digest=hashlib.sha256()
        for (value,) in db.execute('SELECT digest FROM terms ORDER BY digest'): digest.update(value)
    vocabulary().serialize(directory/'vocabulary.ttl',format='turtle')
    cad_shapes().serialize(directory/'shapes.ttl',format='turtle')
    result={'nt_path':str(path),'inventory_path':str(inventory),'nt_sha256':file_hash(path),'nt_bytes':path.stat().st_size,
            'triple_count':len(graph),'termset_sha256':digest.hexdigest(),'graph_iri':NS+'graph:'+bundle['batch_id'],
            'namespace':NS,'package_sha256':canonical_hash(bundle),'shacl':shacl}
    save_json(directory/'generation.json',result)
    return result


def verify_cad_readback(generated,path):
    return verify_readback(generated,path)


def load_cad_rdf(config,generated,*,progress=None):
    """An existing graph must already be exact; never patch a partial retry."""
    if urlsplit(config.fuseki_url).port!=23059 or not generated['graph_iri'].startswith(NS+'graph:'):
        raise ValueError('CAD RDF target is not the new deployment')
    if file_hash(generated['nt_path'])!=generated['nt_sha256']: raise ValueError('CAD RDF checksum changed')
    endpoint=config.fuseki_url.rstrip('/'); returned=Path(generated['nt_path']).with_name('readback.nt')
    with httpx.Client(timeout=600,trust_env=False) as client:
        response=client.post(endpoint+'/query',data={'query':'ASK { GRAPH <'+generated['graph_iri']+'> { ?s ?p ?o } }'},
                             headers={'Accept':'application/sparql-results+json'})
        response.raise_for_status(); exists=response.json()['boolean']
        if not exists:
            with Path(generated['nt_path']).open('rb') as stream:
                response=client.post(endpoint+'/data',params={'graph':generated['graph_iri']},content=stream,
                                     headers={'Content-Type':'application/n-triples'})
            response.raise_for_status()
        with client.stream('GET',endpoint+'/data',params={'graph':generated['graph_iri']},
                           headers={'Accept':'application/n-triples','Accept-Encoding':'identity'}) as response:
            response.raise_for_status(); size=0
            with returned.open('wb') as stream:
                for block in response.iter_bytes(1024*1024):
                    size+=len(block)
                    if size>generated['nt_bytes']*4+1024*1024: raise ValueError('CAD RDF readback exceeds bound')
                    stream.write(block)
    result=verify_cad_readback(generated,returned)
    result['existing_graph_verified']=exists
    return result

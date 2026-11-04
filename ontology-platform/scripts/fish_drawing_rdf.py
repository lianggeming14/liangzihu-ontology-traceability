"""Preserve all five-drawing evidence nodes as typed RDF and navigable records.

These document representations link to map objects by exact source UUID. They
are not additional physical assets or surveyed measurements.
"""
from collections import defaultdict
import json
from urllib.parse import quote
from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD
from fish_rdf_sample import typed_literal

NS='urn:lzo:fish-review:drawing:v1:'
D=Namespace(NS);C=Namespace('https://w3id.org/lzo/ontology/')
CLASS_LABELS={'Field':'田块图纸档案','Pond':'塘口图纸档案','Measurement':'图纸测量与尺寸',
 'DocumentStatement':'图纸原文陈述','EngineeringAsset':'工程设施档案','EngineeringItem':'工程量条目',
 'Project':'工程项目档案','Region':'图纸分区档案','SourceDrawing':'竣工图来源'}
PROP_LABELS={'numericValue':'原单位数值','unit':'原单位','siValue':'SI 换算值','siUnit':'SI 单位',
 'quantityKind':'量的类型','sourceQuantityKind':'原始类型','aggregationPolicy':'累计规则',
 'reviewStatus':'复核状态','sourceRecord':'来源原始记录','hasMeasurement':'具有测量记录',
 'depictedIn':'描绘于图纸','locatedIn':'所属图示分区','hasDrawingEvidence':'具有图纸证据',
 'evidenceForMapObject':'描述空间对象','label':'名称'}


def local(value):return str(value).rsplit('/',1)[-1].rsplit(':',1)[-1]
def instance(value):return URIRef(NS+'instance:'+quote(str(value),safe=''))
def source_class(value):return URIRef(NS+'class:'+local(value))
def label(value):return PROP_LABELS.get(local(value),local(value))


def term(value):
    if value['kind']=='iri':return URIRef(value['value'])
    if value['kind']!='literal':raise ValueError('Unexpected drawing RDF term')
    dtype=value.get('datatype_iri') or str(XSD.string)
    if dtype==str(XSD.decimal):return typed_literal(value['value'],{'type':'number'})
    if dtype==str(XSD.integer):return typed_literal(value['value'],{'type':'integer'})
    if dtype==str(XSD.boolean):return typed_literal(value['value'],{'type':'boolean'})
    return Literal(value['value'],datatype=URIRef(dtype),normalize=False)


def project_drawing(payload,map_objects=None):
    nodes={n['id']:n for n in payload['nodes']}
    if len(nodes)!=len(payload['nodes']):raise ValueError('Duplicate drawing evidence identity')
    for edge in payload['edges']:
        if edge['subject_id'] not in nodes or edge['object_id'] not in nodes:raise ValueError('Dangling drawing evidence edge')
    for original in sorted({n['class_iri'] for n in nodes.values()}):
        cls=source_class(original);name=local(original)
        yield cls,RDF.type,OWL.Class
        yield cls,RDFS.label,Literal(CLASS_LABELS.get(name,name),lang='zh')
        yield cls,RDFS.subClassOf,C.Observation if name=='Measurement' else C.Document
        yield cls,D.sourceClass,URIRef(original)
    for ordinal,node in enumerate(payload['nodes'],1):
        s=instance(node['id']);yield s,RDF.type,source_class(node['class_iri'])
        yield s,RDFS.label,Literal(node['label'])
        yield s,D.sourceID,Literal(node['id'])
        yield s,D.dataNature,Literal(node['data_nature'])
        yield s,D.packageSHA256,Literal(payload['source_package_sha256'])
        yield s,D.bundleSHA256,Literal(payload['content_sha256'])
        yield s,D.rowNumber,Literal(ordinal)
        yield s,D.adoptionStatus,Literal('source_drawing_evidence_not_field_verified')
        for drawing in node.get('source_drawing_ids',[]):yield s,D.sourceDrawingID,Literal(drawing)
        for index,prop in enumerate(node['properties']):
            predicate=URIRef(prop['predicate_iri']);value=term(prop['term'])
            yield s,predicate,value
            yield predicate,RDF.type,OWL.ObjectProperty if isinstance(value,URIRef) else OWL.DatatypeProperty
            yield predicate,RDFS.label,Literal(label(predicate),lang='zh')
            support=URIRef(NS+'support:'+node['id']+':'+str(index))
            yield support,RDF.type,RDF.Statement
            yield support,RDF.subject,s;yield support,RDF.predicate,predicate;yield support,RDF.object,value
            for evidence in prop.get('evidence_ids',[]):yield support,D.evidenceID,Literal(evidence)
    for index,edge in enumerate(payload['edges']):
        s,o=instance(edge['subject_id']),instance(edge['object_id']);p=URIRef(edge['predicate_iri']);inv=URIRef(str(p)+':inverse')
        yield p,RDF.type,OWL.ObjectProperty;yield inv,RDF.type,OWL.ObjectProperty
        yield p,OWL.inverseOf,inv;yield p,RDFS.label,Literal(label(p),lang='zh')
        yield s,p,o;yield o,inv,s
        record=URIRef(NS+'edge:'+str(index));yield record,RDF.type,RDF.Statement
        yield record,RDF.subject,s;yield record,RDF.predicate,p;yield record,RDF.object,o
        yield record,D.derivation,Literal(edge.get('derivation',''))
        for evidence in edge.get('evidence_ids',[]):yield record,D.evidenceID,Literal(evidence)
    for obj in (map_objects or {}).get('objects',[]):
        key=obj.get('source_resource_id')
        if key not in nodes:continue
        s,o=URIRef(obj['object_iri']),instance(key)
        yield D.hasDrawingEvidence,RDF.type,OWL.ObjectProperty
        yield D.hasDrawingEvidence,OWL.inverseOf,D.evidenceForMapObject
        yield D.hasDrawingEvidence,RDFS.label,Literal('具有原图档案及测量证据',lang='zh')
        yield s,D.hasDrawingEvidence,o;yield o,D.evidenceForMapObject,s
        yield s,D.externalClass,URIRef(obj['class_iri'])
        yield s,D.externalLabel,Literal(obj['label'])
        yield o,D.mapObject,s


class DrawingNavigation:
    def __init__(self):self.records=defaultdict(lambda:defaultdict(list))
    def add(self,s,p,o):self.records[str(s)][str(p)].append(o)
    def finish(self):
        records=self.records
        def one(s,p,default=None):
            values=records.get(str(s),{}).get(str(p),[])
            return str(values[0]) if values else default
        concepts=[];tables={};by_iri={}
        for s,props in records.items():
            if s.startswith(NS+'class:') and OWL.Class in props.get(str(RDF.type),[]):
                name=local(s);table='drawing_'+name.lower()
                concepts.append({'iri':s,'label':one(s,RDFS.label),'parent_iri':one(s,RDFS.subClassOf),
                    'children':[],'table':table,'role':'drawing_evidence','instance_count':0,'total_instance_count':0,
                    'instances_path':'classes/'+table+'.json.gz'})
                tables[table]={'contract':'fish-rdf-review/1','class_iri':s,'instances':[]}
        classes={c['iri']:c for c in concepts}
        for s,props in records.items():
            if not s.startswith(NS+'instance:'):continue
            cls=one(s,RDF.type)
            if cls not in classes:raise ValueError('Drawing RDF lacks declared source class')
            original=one(s,D.sourceID);values=[]
            unit=next((str(v[0]) for p,v in props.items() if local(p)=='unit'),None)
            for p,terms in sorted(props.items()):
                if not p.startswith(('urn:lzo:drawing-ontology:','https://w3id.org/lzo/ontology/')):continue
                for value in terms:
                    if not isinstance(value,Literal) or local(p)=='sourceRecord':continue
                    values.append({'iri':p,'field':local(p),'label':label(p),'value':str(value),
                        'datatype':str(value.datatype or XSD.string),'unit':unit if local(p)=='numericValue' else None,
                        'nature':one(s,D.dataNature)})
            item={'iri':s,'id':original,'uuid':original,'label':one(s,RDFS.label),'class_iri':cls,
                'table':classes[cls]['table'],'nature':one(s,D.dataNature),
                'adoption_status':'source_drawing_evidence_not_field_verified','properties':values,
                'outgoing':[],'incoming':[],'unresolved_relations':[],
                'provenance':{'table':classes[cls]['table'],'row_number':int(one(s,D.rowNumber,'0')),
                    'package_sha256':one(s,D.packageSHA256),'bundle_sha256':one(s,D.bundleSHA256),
                    'drawing_ids':[str(v) for v in props.get(str(D.sourceDrawingID),[])],
                    'status':'imported_unverified','source_record_available_in_rdf':True,'issues':[]}}
            by_iri[s]=item;tables[item['table']]['instances'].append(item);classes[cls]['instance_count']+=1
        count=0;external=[]
        for s,props in records.items():
            if not s.startswith(NS+'edge:'):continue
            source,target,predicate=one(s,RDF.subject),one(s,RDF.object),one(s,RDF.predicate)
            if source not in by_iri or target not in by_iri:raise ValueError('Readback drawing relation is dangling')
            first,second=by_iri[source],by_iri[target]
            edge={'iri':predicate,'edge_iri':s,'field':local(predicate),'label':one(predicate,RDFS.label,label(predicate)),
                'resolution':'resolved','source_row':first['provenance']['row_number'],'list_index':None}
            first['outgoing'].append({**edge,'target_iri':target,'target_id':second['id'],'target_label':second['label'],'target_class_iri':second['class_iri']})
            second['incoming'].append({**edge,'source_iri':source,'source_id':first['id'],'source_label':first['label'],'source_class_iri':first['class_iri']});count+=1
        for target,item in by_iri.items():
            for value in records[target].get(str(D.mapObject),[]):
                source=str(value);cls=one(source,D.externalClass);name=one(source,D.externalLabel,source)
                edge={'iri':str(D.hasDrawingEvidence),'edge_iri':source+'#drawing-evidence','field':'hasDrawingEvidence',
                    'label':'具有图纸证据','resolution':'resolved','source_iri':source,'source_id':source.rsplit(':',1)[-1],
                    'source_label':name,'source_class_iri':cls,'target_iri':target,'target_id':item['id'],
                    'target_label':item['label'],'target_class_iri':item['class_iri'],'source_row':None,'list_index':None}
                item['incoming'].append(edge);external.append(edge)
        for c in concepts:c['total_instance_count']=c['instance_count']
        for table in tables.values():table['instances'].sort(key=lambda x:(x['label'],x['iri']))
        return {'contract':'fish-rdf-review/1','concepts':concepts,'counts':{'instances':len(by_iri),
            'relations':count,'resolved_relations':count,'classes':len(concepts),'map_evidence_bridges':len(external)},
            'external_relations':external},tables

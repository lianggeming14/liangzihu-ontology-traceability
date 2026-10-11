"""Versioned graph exchange profile, not a universal RDF conversion engine."""
import copy
import json
from urllib.parse import quote

BASE='https://example.org/agri/vocab/'
PROFILE='agri-graph-exchange/1.0'
CONTEXT={'agri':BASE,'label':'agri:label','kind':'agri:kind','predicate_code':'agri:predicateCode',
         'dimension':'agri:dimension','status':'agri:status','profile':'agri:profile',
         'source':{'@id':'agri:source','@type':'@id'},'target':{'@id':'agri:target','@type':'@id'},
         'payload':{'@id':'agri:payload','@type':'@json'},'manifest':{'@id':'agri:manifest','@type':'@json'}}

def identifier(kind,key):
    return 'urn:agri:'+kind+':'+quote(str(key),safe='')

def to_jsonld(graph):
    nodes=graph.get('nodes',[]);edges=graph.get('edges',[])
    ids={str(n.get('id') or n.get('entity_key')) for n in nodes}
    items=[]
    for n in nodes:
        key=str(n.get('id') or n.get('entity_key'))
        items.append({'@id':identifier('node',key),'@type':'agri:GraphNode',
                      'label':n.get('label',n.get('name','')),'kind':n.get('kind',n.get('entity_type',n.get('type','unknown'))),
                      'payload':copy.deepcopy(n)})
    for index,e in enumerate(edges):
        source=str(e.get('source') or e.get('subject_key'));target=str(e.get('target') or e.get('object_key'))
        if source not in ids or target not in ids:raise ValueError('Graph edge references a missing node')
        key=e.get('id',str(index))
        items.append({'@id':identifier('edge',key),'@type':'agri:QualifiedRelationship',
                      'source':identifier('node',source),'target':identifier('node',target),
                      'predicate_code':e.get('predicate_id',e.get('predicate','')),
                      'dimension':e.get('dimension',''),'status':e.get('status','unknown'),'payload':copy.deepcopy(e)})
    return {'@context':CONTEXT,'@id':'urn:agri:export','@type':'agri:GraphExport','profile':PROFILE,
            'manifest':{k:copy.deepcopy(v) for k,v in graph.items() if k not in ('nodes','edges')},'@graph':items}

def from_jsonld(document):
    if document.get('profile')!=PROFILE or document.get('@context')!=CONTEXT:
        raise ValueError('Only the frozen agri-graph-exchange/1.0 profile is supported')
    nodes=[];edges=[];seen=set()
    for item in document.get('@graph',[]):
        if item.get('@id') in seen:raise ValueError('Duplicate graph resource')
        seen.add(item.get('@id'))
        body=copy.deepcopy(item.get('payload'))
        if not isinstance(body,dict):raise ValueError('Missing preservation payload')
        if item.get('@type')=='agri:GraphNode':
            if item['@id']!=identifier('node',body.get('id') or body.get('entity_key')):raise ValueError('Node identity changed')
            nodes.append(body)
        elif item.get('@type')=='agri:QualifiedRelationship':
            source=body.get('source') or body.get('subject_key');target=body.get('target') or body.get('object_key')
            if item.get('source')!=identifier('node',source) or item.get('target')!=identifier('node',target):raise ValueError('Relation endpoint changed')
            edges.append(body)
        else:raise ValueError('Unsupported resource type')
    graph=dict(document.get('manifest',{}),nodes=nodes,edges=edges)
    to_jsonld(graph)  # Referential validation, no write-back into business tables.
    return graph

def to_turtle(graph):
    document=to_jsonld(graph)
    lit=lambda value:json.dumps(value,ensure_ascii=False)
    lines=['@prefix agri: <'+BASE+'> .','@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .','']
    for item in document['@graph']:
        subject='<'+item['@id']+'>'
        lines.append(subject+' a '+item['@type']+' ;')
        if item['@type']=='agri:QualifiedRelationship':
            lines.append('  agri:source <'+item['source']+'> ; agri:target <'+item['target']+'> ;')
            lines.append('  agri:predicateCode '+lit(item['predicate_code'])+' ;')
        else:
            lines.append('  agri:label '+lit(item['label'])+' ; agri:kind '+lit(item['kind'])+' ;')
        lines.append('  agri:payload '+lit(json.dumps(item['payload'],ensure_ascii=False,sort_keys=True))+'^^rdf:JSON .')
    lines.append('<urn:agri:export> agri:profile '+lit(PROFILE)+' ; agri:manifest '+lit(json.dumps(document['manifest'],ensure_ascii=False,sort_keys=True))+'^^rdf:JSON .')
    return '\n'.join(lines)+'\n'

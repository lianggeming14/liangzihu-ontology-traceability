"""Bounded navigation from the model whose complete RDF termset was read back.

Original CSV values remain in the private source/RDF provenance. Public details
use the exact RDF literals produced by typed_literal, after full Jena equality.
"""
from collections import defaultdict
from collections.abc import Mapping
import gzip
import hashlib
import json
from pathlib import Path
import re

from rdflib import URIRef
from rdflib.namespace import RDF,RDFS,XSD
from fish_rdf_sample import PROV,typed_literal,uri_factory,datatype

STATE='csv_batch_not_formally_adopted'
DETAIL_SIZE=500
RELATION_SIZE=4800
INLINE_RELATIONS=1000


def label(node):
    return str(next((node['properties'].get(field) for field in ('name','title','label')
        if node['properties'].get(field)),node['source_pk']))


class Indices:
    def __init__(self,snapshot):
        self.nodes={row['node_id']:row for row in snapshot['nodes']}
        self.raw={(row['table_name'],row['row_number']):row for row in snapshot['raw']}
        self.registry={n['properties'].get('table',n['source_pk']):n['properties'].get('origin_kind')
            for n in snapshot['nodes'] if n['table_name']=='source_registry'}
        self.outgoing=defaultdict(list);self.incoming=defaultdict(list);self.unresolved=defaultdict(list)
        for position,edge in enumerate(snapshot['relations']):
            if edge['resolution']=='resolved':
                self.outgoing[edge['from_node']].append(position)
                self.incoming[edge['to_node']].append(position)
            else:self.unresolved[edge['from_node']].append(position)


class CanonicalRecords(Mapping):
    """Lazy exact canonical RDF subset; avoids retaining millions of raw triples."""
    def __init__(self,snapshot,namespace,index=None):
        self.snapshot=snapshot;self.namespace=namespace;self.uri=uri_factory(namespace)
        self.index=index or Indices(snapshot)
        self.subjects={str(self.uri('instance',key)):key for key in self.index.nodes}

    def __len__(self):return len(self.subjects)
    def __iter__(self):return iter(self.subjects)

    def __getitem__(self,subject):
        node=self.index.nodes[self.subjects[subject]];table=node['table_name'];u=self.uri
        values=defaultdict(list)
        values[str(RDF.type)].append(u('class',table))
        values[str(PROV.wasDerivedFrom)].append(u('source',table,node['source_row']))
        for field,definition in self.snapshot['schema']['tables'][table]['columns'].items():
            value=node['properties'].get(field)
            if value is not None:values[str(u('property',table,field))].append(typed_literal(value,definition))
        for offset in self.index.outgoing[node['node_id']]:
            edge=self.snapshot['relations'][offset]
            values[str(u('relation',table,edge['field_name'],edge['target_table']))].append(u('instance',edge['to_node']))
        for offset in self.index.incoming[node['node_id']]:
            edge=self.snapshot['relations'][offset];source=self.index.nodes[edge['from_node']]
            predicate=str(u('relation',source['table_name'],edge['field_name'],table))+':inverse'
            values[predicate].append(u('instance',edge['from_node']))
        return values

    def triples(self):
        for subject in self:
            for predicate,values in self[subject].items():
                for value in values:yield URIRef(subject),URIRef(predicate),value


def edge_detail(edge,snapshot,index,namespace,labels,direction):
    u=uri_factory(namespace);source=index.nodes[edge['from_node']]
    target_table=edge['target_table']
    result={'iri':str(u('relation',source['table_name'],edge['field_name'],target_table)),
        'edge_iri':str(u('edge',edge['edge_id'])),'field':edge['field_name'],
        'label':edge['field_name']+' → '+labels.get(target_table,target_table),
        'resolution':edge['resolution'],'source_row':edge['source_row'],'list_index':edge.get('list_index')}
    if edge['resolution']!='resolved':return {**result,'target_table':target_table,'target_id':edge['target_pk']}
    if direction=='outgoing':
        other=index.nodes[edge['to_node']];prefix='target'
    else:other=source;prefix='source'
    result.update({prefix+'_iri':str(u('instance',other['node_id'])),prefix+'_id':other['source_pk'],
        prefix+'_label':label(other),prefix+'_class_iri':str(u('class',other['table_name']))})
    return result


def detail(node,snapshot,index,namespace,metadata,labels,*,with_edges=True):
    table=node['table_name'];u=uri_factory(namespace);props=[]
    for field,definition in snapshot['schema']['tables'][table]['columns'].items():
        actual=node['properties'].get(field);term=typed_literal(actual,definition) if actual is not None else None
        value=str(term) if term is not None else None
        dtype=str(term.datatype) if term is not None else str(datatype(definition))
        if value is not None and dtype==str(XSD.boolean):value=value=='true'
        if value is not None and dtype==str(XSD.integer):value=int(value)
        props.append({'iri':str(u('property',table,field)),'field':field,'label':definition.get('description',field),
            'value':value,'datatype':dtype,'unit':definition.get('unit'),'nature':node['nature']})
    raw=index.raw[table,node['source_row']];member=metadata.get(table,{})
    ends=member.get('line_ends',[])
    result={'iri':str(u('instance',node['node_id'])),'id':node['source_pk'],'uuid':node['node_id'],
        'class_iri':str(u('class',table)),'table':'csv_'+table,'label':label(node),'nature':node['nature'],
        'adoption_status':STATE,'batch_id':snapshot['package_sha256'],'properties':props,
        'outgoing':[],'incoming':[],'unresolved_relations':[],
        'provenance':{'source_record_iri':str(u('source',table,node['source_row'])),'table':table,
            'row_number':node['source_row'],'package_sha256':snapshot['package_sha256'],'status':raw['status'],
            'sample_reason':'full_csv_batch','issues':raw['issues'],'batch_id':snapshot['package_sha256'],
            'source_file':member.get('path'),'source_sha256':member.get('sha256'),
            'source_origin_kind':index.registry.get(table,'batch_source_registry' if table=='source_registry' else None),
            'csv_line_end':ends[node['source_row']-1] if len(ends)>=node['source_row'] else None}}
    for position in index.unresolved[node['node_id']]:
        result['unresolved_relations'].append(edge_detail(snapshot['relations'][position],snapshot,index,namespace,labels,'outgoing'))
    if with_edges:
        for direction in ('outgoing','incoming'):
            result[direction]=[edge_detail(snapshot['relations'][position],snapshot,index,namespace,labels,direction)
                for position in getattr(index,direction)[node['node_id']]]
    return result


def _save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    payload=gzip.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'),mtime=0)
    if len(payload)>=20*1024*1024:raise ValueError('Public compressed data chunk exceeds repository limit')
    path.write_bytes(payload)
    return len(payload),hashlib.sha256(payload).hexdigest()


def write_classes(snapshot,namespace,metadata,labels,directory,verification):
    if (verification.get('status')!='passed' or verification.get('full_terms_equal') is not True
            or verification.get('package_sha256')!=snapshot['package_sha256']
            or not re.fullmatch(re.escape(namespace)+r'graph:[0-9a-f]{64}',verification.get('graph_iri',''))):
        raise ValueError('Public CSV navigation requires full Jena RDF termset equality')
    directory=Path(directory);index=Indices(snapshot);grouped=defaultdict(list)
    for node in snapshot['nodes']:grouped[node['table_name']].append(node)
    files={};counts={'instances':0,'class_shards':0,'detail_chunks':0,'relation_chunks':0}
    for table,nodes in sorted(grouped.items()):
        if not re.fullmatch(r'[a-z][a-z0-9_]*',table):raise ValueError('Invalid public table path')
        key='csv_'+table;summary=[];nodes.sort(key=lambda node:(node['source_pk'],node['node_id']))
        for start in range(0,len(nodes),DETAIL_SIZE):
            chunk_path=f'details/{key}/{start//DETAIL_SIZE+1:05d}.json.gz';rows=[]
            for node in nodes[start:start+DETAIL_SIZE]:
                row=detail(node,snapshot,index,namespace,metadata,labels,with_edges=False)
                row['detail_path']=chunk_path
                for direction in ('outgoing','incoming'):
                    positions=getattr(index,direction)[node['node_id']]
                    row[direction+'_count']=len(positions)
                    if len(positions)<=INLINE_RELATIONS:
                        row[direction]=[edge_detail(snapshot['relations'][p],snapshot,index,namespace,labels,direction) for p in positions]
                    else:
                        row[direction+'_page_size']=RELATION_SIZE;row[direction+'_pages']=[]
                        for offset in range(0,len(positions),RELATION_SIZE):
                            part=f'relations/{key}/{node["node_id"]}/{direction}-{offset//RELATION_SIZE+1:05d}.json.gz'
                            page={'contract':'fish-rdf-relations/1','instance_iri':row['iri'],'direction':direction,
                                'edges':[edge_detail(snapshot['relations'][p],snapshot,index,namespace,labels,direction)
                                    for p in positions[offset:offset+RELATION_SIZE]]}
                            size,sha=_save(directory/part,page);files[part]={'bytes':size,'sha256':sha}
                            row[direction+'_pages'].append(part);counts['relation_chunks']+=1
                rows.append(row)
                summary.append({field:row[field] for field in ('iri','id','uuid','label','class_iri','table','nature','adoption_status','batch_id','detail_path')})
            payload={'contract':'fish-rdf-review/1','class_iri':str(uri_factory(namespace)('class',table)),
                'jena_verified':True,'graph_iri':verification['graph_iri'],'instances':rows}
            size,sha=_save(directory/chunk_path,payload);files[chunk_path]={'bytes':size,'sha256':sha};counts['detail_chunks']+=1
        class_path=f'classes/{key}.json.gz'
        payload={'contract':'fish-rdf-review/1','class_iri':str(uri_factory(namespace)('class',table)),
            'jena_verified':True,'graph_iri':verification['graph_iri'],'instances':summary}
        size,sha=_save(directory/class_path,payload);files[class_path]={'bytes':size,'sha256':sha}
        counts['class_shards']+=1;counts['instances']+=len(nodes)
    return {'contract':'csv-bounded-navigation/1',**counts,'detail_chunk_size':DETAIL_SIZE,
        'relation_chunk_size':RELATION_SIZE,'total_compressed_bytes':sum(x['bytes'] for x in files.values()),
        'maximum_compressed_bytes':max(x['bytes'] for x in files.values()),'files':files,
        'derivation':'Canonical RDF model proven exactly equal to complete Jena readback; bounded serialization uses its exact RDF literals',
        'raw_payload_public':False}

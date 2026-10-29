"""Reproducible drawing package from hash-checked originals and reviewed derivatives."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from lzo.gis.drawing_package import seal_package


def load(path):return json.loads(path.read_text('utf8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


DRAWING_SOURCES={
 'detail-miaoxia':('pdf-01','9258ee26b29860579c900aeb1dbf3a4ca6d2cef6c02ec2d317e3349f4157c91a'),
 'detail-xinwumao':('pdf-02','56847eb506216516e30e0ad5a33d3550d905ed9a9dd923456bbbd899c376c5ef'),
 'detail-zhangjia':('pdf-03','2c1f84927f1d4ff3678aed2804569e43b9272f95744c5364696a857d640edd6d'),
 'detail-tanshen':('pdf-04','0805f1a484b099ed69c6fc0056420a645d6fa2fb09bae03cdca486fe0976a0d0'),
 'detail-abcdef':('pdf-05','5345f24a15514dd14dd64ee58d62abdfb3f8874126c6a82a7f2860397da1e55d')}


def drawing_identity(record):
    expected=DRAWING_SOURCES.get(record['asset_id'])
    if expected is None or record['source_hash']!=expected[1]:raise ValueError('Unreviewed drawing source identity')
    return expected[0]


def table_annotations(sid,index,table,filename):
    context={k:v for k,v in table.items() if k!='rows'}
    common={'drawing_id':sid,'review_status':'manual_transcription_not_survey','table':context,
            'review_file':filename,'aggregation_policy':'Do not sum duplicate project totals or distribute totals to individual features'}
    result=[dict(common,annotation_id=f'{sid}:table:{index:02}',record_type='table',row_count=len(table.get('rows',[])))]
    result.extend(dict(common,annotation_id=f'{sid}:table:{index:02}:{j:04}',record_type='table_row',row=row)
                  for j,row in enumerate(table.get('rows',[])))
    return result


def identity_index(entities):
    result={}
    for entity in entities:
        if entity['dataset']!='real' or entity['data_nature']!='imported_unverified':continue
        for identifier in entity['spatial_ids']:
            if identifier in result and result[identifier]['resource_id']!=entity['resource_id']:
                raise ValueError('Conflicting identity owners: '+identifier)
            result[identifier]=entity
    return result


def feature_record(record,drawing_id,identity):
    kind=record['kind']
    if record.get('identity_scope')=='drawing_annotation_not_verified_unique_asset':kind='facility_annotation'
    if record.get('identity_scope')=='unresolved_drawing_label':kind='unresolved_label'
    class_name={'field':'Field','pond':'Pond','road':'Road','channel':'Channel'}.get(kind,'DrawingAnnotation')
    return {'feature_id':record['representation_id'],'entity_id':identity.get('resource_id'),
        'entity_iri':'urn:lzo:object:'+identity['resource_id'] if identity.get('resource_id') else None,
        'entity_origin':'farm_persisted_identity','core_registration_status':'not_imported_by_this_package',
        'class_iri':('https://w3id.org/lzo/ontology/' if kind in ('field','pond') else 'urn:lzo:drawing-vocab:')+class_name,'kind':kind,'label':record['label'],
        'drawing_id':drawing_id,'geometry':record['geometry'],'data_nature':'imported_unverified',
        'area_m2':None,'length_m':None,'ledger_area':{'value':record.get('area_original'),'unit':record.get('area_unit')},
        'source':{k:v for k,v in record.items() if k!='geometry'},
        'identity_evidence':{k:v for k,v in identity.items() if k in ('resource_id','source_key','revision','spatial_ids','evidence_ids')}}


def build(farm,output,version):
    output.mkdir(parents=True,exist_ok=True)
    source=load(farm/'data/spatial/drawing-entities.json')
    native=load(farm/'data/spatial/native-annotations.json')
    identities=identity_index(load(farm/'data/audit/entity-mapping.json')['entities'])
    drawing_ids={};sheets=[];inputs=[]
    if len(source['drawings'])!=5:raise ValueError('Exactly five reviewed drawings required')
    for d in sorted(source['drawings'],key=drawing_identity):
        sid=drawing_identity(d);path=farm/d['source_file']
        actual=sha(path)
        if actual!=d['source_hash']:raise ValueError('Source PDF changed: '+d['source_file'])
        sheet={**d,'drawing_id':sid,'source_sha256':actual,'coordinate_system':'PDF_LANDSCAPE_LOCAL','coordinate_units':'pt',
            'georeferenced':False,'origin':'top_left','axes':['right','down'],'source_page':1,
            'source_path_on_original_farm':d['source_file']}
        # No absolute workstation path or unavailable image URL in the contract.
        sheet.pop('image_path',None);sheets.append(sheet);drawing_ids[d['asset_id']]=sid
        inputs.append({'path':d['source_file'],'sha256':actual,'bytes':path.stat().st_size,'role':'original_drawing_not_republished'})
    features=[]
    for record in source['records']:
        identity=identities.get(record['representation_id']) or identities.get(record.get('source_representation_id'))
        if identity is None:raise ValueError('Missing persistent farm identity: '+record['representation_id'])
        features.append(feature_record(record,drawing_ids[record['asset_id']],identity))
    if sum(f['kind']=='field' for f in features)!=100:raise ValueError('Expected exactly 100 source ledger field representations')
    annotations=[]
    for drawing in native:
        for i,row in enumerate(drawing['annotations']):
            annotations.append({'annotation_id':f"{drawing['slug']}:native:{i:04}",'drawing_id':drawing['slug'],
                'record_type':'native_text','text_original':row['text'],'review_status':'unverified_native_text',
                'contains_replacement_char':'\ufffd' in row['text'],'source_native':row,
                'coordinate_warning':'Native extraction matrices preserved; do not assume anchor is physical asset location'})
    review_summaries=[]
    for filename in ('review-12.json','review-345.json'):
        review=load(output/filename)
        for d in review['drawings']:
            sid=d['id'];review_summaries.append({'drawing_id':sid,'coverage':d.get('coverage'),
                'notes':d.get('notes',[]),'review_limitations':d.get('review_limitations',[])})
            for category in ('legend','measurements','background_categories','region_labels'):
                for i,item in enumerate(d.get(category,[])):
                    annotations.append({'annotation_id':f'{sid}:review:{category}:{i:04}','drawing_id':sid,'record_type':category,
                        'review_status':'manual_transcription_not_survey','evidence':item,'review_file':filename})
            for i,table in enumerate(d.get('tables',[])):
                annotations.extend(table_annotations(sid,i,table,filename))
    ocr_path=output/'ocr-candidates.json'
    ocr_summary={'status':'not_run'}
    if ocr_path.exists():
        ocr=load(ocr_path)
        complete=len(ocr.get('drawings',[]))==5 and all(d['coverage']['all_tiles_succeeded'] for d in ocr['drawings'])
        ocr_summary={'status':'all_tiles_processed_unverified' if complete else 'partial','source_sha256':sha(ocr_path),
                     'drawings':[{'drawing_id':d['drawing_id'],'coverage':d['coverage'],'candidates':len(d['candidates'])} for d in ocr['drawings']]}
        for d in ocr.get('drawings',[]):
            sid=d.get('drawing_id') or d.get('id') or d.get('slug')
            for i,row in enumerate(d.get('candidates',[])):
                annotations.append({'annotation_id':f'{sid}:ocr:{i:05}','drawing_id':sid,'record_type':'ocr_candidate',
                    'review_status':'unverified','evidence':row})
    for relative in ('data/spatial/drawing-entities.json','data/spatial/native-annotations.json','data/audit/entity-mapping.json'):
        path=farm/relative;inputs.append({'path':relative,'sha256':sha(path),'bytes':path.stat().st_size,'role':'reviewed_derivative_input'})
    for filename in ('review-12.json','review-345.json','ocr-candidates.json','vocabulary.ttl'):
        path=output/filename
        if path.exists():inputs.append({'path':'datasets/drawings/'+filename,'sha256':sha(path),'bytes':path.stat().st_size,'role':'extraction_evidence'})
    coverage={'source_drawings':len(sheets),'features':len(features),'features_by_kind':dict(Counter(f['kind'] for f in features)),
        'annotations':len(annotations),'annotation_types':dict(Counter(a['record_type'] for a in annotations)),
        'semantic_complete':False,'georeferencing_complete':False,'source_location':'farm originals; upload location not independently confirmed',
        'reviews':review_summaries,'ocr':ocr_summary,
        'unresolved':['Not all background buildings, ponds, land cover and elevation points have individual vector features.',
                      'CAD outlined text and OCR candidates require per-label human verification and explicit feature association.',
                      'No common surveyed control points, horizontal CRS or vertical datum; five sheets must not be stitched as surveyed geography.',
                      'Engineering table totals and drawing labels can differ; preserve conflicts rather than average or overwrite.',
                      'Ledger planting area has no stated unit; no conversion to mu or square metres.']}
    package=seal_package({'schema_version':'drawing-gis/1','dataset_id':'liangzihu-asbuilt-2026','version':version,
        'source_manifest':inputs,'drawings':sheets,'features':features,'annotations':annotations,'coverage':coverage})
    (output/'package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (output/'coverage.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    proposals={'@context':{'rdfs':'http://www.w3.org/2000/01/rdf-schema#','draw':'urn:lzo:drawing-vocab:'},
        '@id':'urn:lzo:drawing-proposals:'+package['content_sha256'],
        '@graph':[{'@id':f['entity_iri'],'@type':f['class_iri'],'rdfs:label':f['label'],
                   'draw:representationId':f['feature_id'],'draw:drawingId':f['drawing_id'],
                   'draw:registrationStatus':f['core_registration_status'],'draw:dataNature':f['data_nature']}
                  for f in features if f['entity_iri']]}
    (output/'entity-proposals.jsonld').write_text(json.dumps(proposals,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    return package


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--farm-root',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'datasets/drawings');parser.add_argument('--version',type=int,default=1)
    args=parser.parse_args();result=build(args.farm_root,args.output,args.version)
    print(json.dumps({'sha256':result['content_sha256'],'features':len(result['features']),'annotations':len(result['annotations'])}))

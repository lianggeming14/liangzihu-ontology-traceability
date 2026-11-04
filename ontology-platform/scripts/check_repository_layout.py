"""Check the published review entry/configuration without databases or secrets."""
from pathlib import Path
from contextlib import redirect_stdout
import io
import json
import re
import shutil
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def ontology_check(root=ROOT):
    """Check shipped evidence/snapshots; do not claim a fresh live-service run."""
    from verify_fish_rdf_navigation import verify
    from rdflib import Graph, Namespace, URIRef
    from rdflib.namespace import RDF, RDFS, OWL

    directory=root/'docs/fish/ontology-review'
    required=('README.md','index.html','assets.css','assets.js','model.mjs','model.test.mjs',
        'data/manifest.json','data/map-features.json','rdf-readback.json','shacl-readback.json',
        'navigation-readback.json','vocabulary.ttl','shapes.ttl','live-api-readback.json',
        'browser-report.json','independent-review.json')
    for name in required:
        assert (directory/name).is_file(),f'Missing ontology review entry: {name}'
    manifest=json.loads((directory/'data/manifest.json').read_text(encoding='utf-8'))
    report=json.loads((directory/'rdf-readback.json').read_text(encoding='utf-8'))
    shacl=json.loads((directory/'shacl-readback.json').read_text(encoding='utf-8'))
    stored=json.loads((directory/'navigation-readback.json').read_text(encoding='utf-8'))
    assert manifest['contract']=='fish-rdf-review/1'
    browser=json.loads((directory/'browser-report.json').read_text(encoding='utf-8'))
    independent=json.loads((directory/'independent-review.json').read_text(encoding='utf-8'))
    live=json.loads((directory/'live-api-readback.json').read_text(encoding='utf-8'))
    assert browser['status']==independent['status']==live['status']=='passed'
    assert browser['javascript_errors']==[]
    assert live['triple_count']==2720969 and live['database_mutations']==0
    assert independent['unresolved_critical_findings']==independent['unresolved_important_findings']==0
    for image in browser['screenshots']:
        assert re.fullmatch(r'screenshots/[a-z0-9-]+\.png',image) and (directory/image).is_file()
    assert (root/'scripts/check_ontology_review_browser.mjs').is_file()
    assert manifest['jena_verified'] is True and manifest['fuseki_readback'] is True
    assert manifest['formal_adoption'] is False and report['formal_adoption'] is False
    assert len(manifest['rdf_graphs'])==len(set(manifest['rdf_graphs']))==4
    for family in ('sample','map','demo','drawing'):
        assert sum(graph.startswith(f'urn:lzo:fish-review:{family}:v1:graph:')
            for graph in manifest['rdf_graphs'])==1,f'Missing or duplicate {family} review graph'
    expected={'instances':27135,'relations':79069,'resolved_relations':79002,'classes':112,
        'source_classes':84,'triples':2720969,'map_objects':284,'map_layers':6,
        'demo_assignments':10495,'demo_activity_links':10475,'demo_profile_links':20,
        'drawing_instances':6297,'drawing_measurements':3202,'drawing_relations':10279,
        'drawing_map_bridges':163}
    for name,value in expected.items():
        assert manifest['counts'][name]==value,f'Ontology manifest count differs: {name}'
    assert report['navigation']==manifest['counts']
    assert report['status']==stored['status']==shacl['status']=='passed'
    assert report['rdf_graphs']==stored['rdf_graphs']==manifest['rdf_graphs']
    graph_checks=[report,report['map_and_demo']['map'],report['map_and_demo']['demo'],report['drawing']]
    assert {item['graph_iri'] for item in graph_checks}==set(manifest['rdf_graphs'])
    assert sum(item['triple_count'] for item in graph_checks)==expected['triples']
    for item in graph_checks:
        assert item['all_triples_readback']=='passed' and item['unexpected_or_missing_triples']==0
        assert item['preexisting_graphs_unchanged'] is True
        assert item['sparql'].get('missing_inverse',0)==item['sparql'].get('orphan_targets',0)==0
    assert report['drawing']['sparql']['evidence_bridges']==163
    assert report['drawing']['sparql']['measurements']==3202
    assert report['raw_payload_public'] is False and report['raw_retained_in_local_rdf'] is True
    assert shacl['instances_validated']==20548 and shacl['datatype_constraints']==1354 and shacl['violations']==0
    assert len(shacl['classes'])==64 and sum(item['instances'] for item in shacl['classes'])==20548
    assert all(item['conforms'] is True and item['violations']==0 for item in shacl['classes'])
    assert report['shacl']['status']=='passed' and report['shacl']['violations']==0
    vocabulary=Graph().parse(directory/'vocabulary.ttl',format='turtle')
    shapes=Graph().parse(directory/'shapes.ttl',format='turtle')
    sh=Namespace('http://www.w3.org/ns/shacl#')
    for concept in manifest['concepts']:
        subject=URIRef(concept['iri'])
        assert (subject,RDF.type,OWL.Class) in vocabulary,f'Undeclared ontology class: {subject}'
        if concept['parent_iri']:
            assert (subject,RDFS.subClassOf,URIRef(concept['parent_iri'])) in vocabulary,f'RDF hierarchy differs: {subject}'
    assert len(set(shapes.subjects(RDF.type,sh.NodeShape)))==64
    assert len(list(shapes.triples((None,sh.datatype,None))))==shacl['datatype_constraints']
    assert len(list(shapes.triples((None,sh['class'],None))))==shacl['relation_class_constraints']
    assert {str(value) for value in shapes.objects(None,sh.targetClass)}=={item['class_iri'] for item in shacl['classes']}
    assert len(list((directory/'data/classes').glob('*.json.gz')))==84
    # The standalone verifier writes a report. Run it against a private copy so
    # CI and local repository checks leave all published artifacts unchanged.
    with tempfile.TemporaryDirectory(prefix='ontology-repository-check-') as temporary:
        target=Path(temporary)
        shutil.copytree(directory/'data',target/'data')
        with redirect_stdout(io.StringIO()):
            actual=verify(target)
    for name,value in actual.items():
        if name!='checked_at':
            assert stored.get(name)==value,f'Stored navigation evidence differs: {name}'
    assert actual['shard_count']==84 and actual['dangling_links']==actual['type_mismatches']==0
    assert actual['maximum_compressed_bytes']<20*1024*1024
    assert report['public_shards']['files']==84
    assert report['public_shards']['maximum_compressed_bytes']==actual['maximum_compressed_bytes']
    assert report['public_shards']['total_compressed_bytes']==actual['total_compressed_bytes']
    for name in ('index.html','assets.js','model.mjs'):
        content=(directory/name).read_text(encoding='utf-8')
        targets=re.findall(r'''(?:src|href)=["']([^"']+)["']''',content) if name.endswith('.html') else []
        targets+=re.findall(r'''from\s+["'](\./[^"']+)["']''',content)
        targets+=re.findall(r'''(?:json|fetch)\(["'](data/[^"']+\.(?:json|svg))["']\)''',content)
        for link in targets:
            if link.startswith(('#','https:','http:')):continue
            path=(directory/link.split('#')[0]).resolve()
            assert path.is_relative_to(directory.resolve()) and path.is_file(),f'Broken ontology UI reference: {link}'
    for document in (root.parent/'README.md',root/'README.md'):
        assert 'docs/fish/ontology-review/' in document.read_text(encoding='utf-8'),f'Missing current RDF entry: {document.name}'
    assert 'serve_ontology_review.py' in (directory/'README.md').read_text(encoding='utf-8')
    return {'named_graphs':4,'concepts':112,'instances':27135,'gzip_shards':84,
        'source_links_verified':79002,'demo_links_verified':10495,'live_services_contacted':False}


def check():
    if not __debug__:raise ValueError('Repository checks require assertions enabled; do not use -O')
    repository=ROOT.parent
    files=['README.md','ontology-platform/README.md','ontology-platform/config/fish-review.example.json',
        'ontology-platform/scripts/requirements-fish-review.txt','ontology-platform/scripts/build_fish_review_sample.py',
        'ontology-platform/scripts/verify_fish_review_sample.py','ontology-platform/docs/fish/review-sample/README.md',
        'ontology-platform/docs/fish/review-sample/index.html','ontology-platform/docs/fish/review-sample/readback.json',
        'ontology-platform/docs/fish/review-sample/schema.sql','ontology-platform/docs/fish/review-sample/preview.png']
    for path in files:assert (repository/path).is_file(),f'Missing published entry: {path}'
    readme=(repository/'README.md').read_text(encoding='utf-8')
    assert 'lianggeming14/liangzihu-ontology-traceability' in readme
    for target in re.findall(r'\]\(([^)]+)\)',readme):
        if target.startswith(('https:','http:','#')):continue
        assert (repository/target.split('#')[0]).is_file(),f'Broken root README link: {target}'
    report=json.loads((ROOT/'docs/fish/review-sample/readback.json').read_text(encoding='utf-8'))
    assert report['seed_rows']==(report['full_input_rows']+9)//10
    assert report['seed_rows']+report['dependency_rows']==report['total_sample_rows']
    assert len(report['tables'])==report['business_tables']==64
    assert sum(len(t['columns']) for t in report['tables'])==report['schema_fields']==1346
    assert sum(t['raw_rows'] for t in report['tables'])==report['total_sample_rows']
    checks=report['checks']
    assert checks['raw_field_mismatches']==checks['invalid_gis_geometries']==checks['resolved_edges_without_target']==0
    assert checks['independent_source_readback']==checks['independent_typed_readback']=='passed'
    assert sum(checks['graph_node_roles'].values())==checks['ontology_nodes']
    assert len(report['ponds'])==6 and checks['gis_features']==126
    page=(ROOT/'docs/fish/review-sample/index.html').read_text(encoding='utf-8')
    assert '__REVIEW_DATA__' not in page
    ddl=(ROOT/'docs/fish/review-sample/schema.sql').read_text(encoding='utf-8')
    assert len(re.findall(r'CREATE TABLE ',ddl))==70
    assert 'ADD COLUMN geom geometry(Geometry,4326)' in ddl
    config=json.loads((ROOT/'config/fish-review.example.json').read_text(encoding='utf-8'))
    serialized=json.dumps(config).lower()
    assert not any(word in serialized for word in ('postgresql://','postgresql+psycopg://','password','access_token'))
    assert not list(repository.glob('snapshot-*.zip')),'Obsolete snapshot transports remain'
    for name in ('.document-build','.document-build-v1.1'):
        assert not list((repository/name).glob('contact-*.png'))
        assert not list((repository/name).glob('preview-pages/*.png'))
    cleanup=json.loads((ROOT/'docs/operations/repository-cleanup.json').read_text(encoding='utf-8'))
    for item in cleanup['remove']:
        assert not (repository/item['path']).exists(),f"Reviewed removal still present: {item['path']}"
    ontology=ontology_check()
    print(json.dumps({'status':'passed','published_entries':len(files),'business_tables':64,'source_fields':1346,
        'sample_total':report['total_sample_rows'],'database_connections':0,'ontology':ontology,
        'verification_scope':'published artifacts and offline tests; existing service evidence is not rerun in CI'},ensure_ascii=False))


if __name__=='__main__':check()

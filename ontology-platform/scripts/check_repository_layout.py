"""Check the published review entry/configuration without databases or secrets."""
from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parents[1]


def check():
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
    print(json.dumps({'status':'passed','published_entries':len(files),'business_tables':64,'source_fields':1346,
        'sample_total':report['total_sample_rows'],'database_connections':0},ensure_ascii=False))


if __name__=='__main__':check()

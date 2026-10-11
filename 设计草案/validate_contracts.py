import copy
import json
from pathlib import Path
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
schema = json.loads((ROOT / 'canonical-record.schema.json').read_text(encoding='utf-8'))
fixture = json.loads((ROOT / 'canonical-record.examples.json').read_text(encoding='utf-8'))
design = json.loads((ROOT / 'liangzihu-ontology.v0.1.json').read_text(encoding='utf-8'))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())

def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def semantic_check(value):
    if isinstance(value, dict):
        if value.get('kind') == 'interval' and value.get('end') is not None:
            if dt(value['end']) <= dt(value['start']):
                raise ValueError('INVALID_TIME_INTERVAL')
        if value.get('meaning') == 'probability' and not 0 <= value['value'] <= 1:
            raise ValueError('INVALID_PROBABILITY')
        if value.get('kind') == 'image_region':
            x,y,w,h = value['bbox']
            bound_x = 1 if value['coordinateSystem'] == 'normalized' else value['imageWidth']
            bound_y = 1 if value['coordinateSystem'] == 'normalized' else value['imageHeight']
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > bound_x or y+h > bound_y:
                raise ValueError('INVALID_BBOX')
        if value.get('kind') == 'document_span' and value['endOffset'] <= value['startOffset']:
            raise ValueError('INVALID_DOCUMENT_SPAN')
        for item in value.values():
            semantic_check(item)
    elif isinstance(value, list):
        for item in value:
            semantic_check(item)

records = fixture['records']
ids = {r['recordId'] for r in records}
assert len(ids) == len(records), 'duplicate recordId'
registry = {(r['type'],r['id']) for r in fixture['externalObjectRegistry']}
known_types = {t['id'] for t in design['objectTypes']}

def walk_references(value):
    if isinstance(value, dict):
        if set(value) == {'type','id'}:
            assert value['type'] in known_types, 'unknown object type'
            assert (value['type'],value['id']) in registry, 'unresolved fixture object'
        if 'recordId' in value:
            assert value['recordId'] in ids, 'unresolved fixture record'
        for v in value.values():
            walk_references(v)
    elif isinstance(value,list):
        for v in value:
            walk_references(v)

for record in records:
    validator.validate(record)
    semantic_check(record)
    walk_references(record)
assert {r['recordType'] for r in records} == set(schema['properties']['recordType']['enum'])
for link in design['linkTypes']:
    assert set(link['from'] + link['to']) <= known_types

def dependencies(value):
    result = set()
    if isinstance(value,dict):
        if 'recordId' in value:
            result.add(value['recordId'])
        for v in value.values():
            result |= dependencies(v)
    elif isinstance(value,list):
        for v in value:
            result |= dependencies(v)
    return result
edges = {r['recordId']: dependencies(r['provenance']) | dependencies(r['data']) for r in records}
seen, visiting = set(), set()
def visit(node):
    assert node not in visiting, 'lineage cycle'
    if node in seen:
        return
    visiting.add(node)
    for child in edges[node]:
        visit(child)
    visiting.remove(node)
    seen.add(node)
for node in edges:
    visit(node)

negative_checks = []
def must_reject(label, record, change, semantic=False):
    v = copy.deepcopy(record)
    change(v)
    try:
        validator.validate(v)
        if semantic:
            semantic_check(v)
    except Exception:
        negative_checks.append(label)
        return
    raise AssertionError('Unexpected acceptance: '+label)

by_type = {r['recordType']: r for r in records}
must_reject('unknown top-level field',records[0],lambda x:x.update(approved=True))
must_reject('invalid UUID',records[0],lambda x:x.update(recordId='not-a-uuid'))
must_reject('unknown record type',records[0],lambda x:x.update(recordType='untyped'))
must_reject('forecast payload disguised as observation',by_type['forecast'],lambda x:x.update(recordType='observation'))
must_reject('number supplied as text',by_type['observation'],lambda x:x['data']['result'].update(value='4.2'))
must_reject('assertion without evidence',by_type['assertion'],lambda x:x['data'].update(evidenceRefs=[]))
must_reject('unknown property in payload',by_type['event'],lambda x:x['data'].update(executeCommand='pump_on'))
must_reject('asset checksum malformed',by_type['asset'],lambda x:x['data'].update(sha256='abc'))
must_reject('invalid time interval',by_type['forecast'],lambda x:x['data']['validTime'].update(end='2026-10-10T00:00:00+08:00'),True)
must_reject('probability outside bounds',by_type['feature'],lambda x:x['quality']['modelScore'].update(value=1.2),True)
must_reject('image box outside asset dimensions',by_type['feature'],lambda x:x['provenance']['evidenceRefs'][0]['locator'].update(bbox=[1910,80,200,160]),True)
report = {'status':'passed','schemaDraft':'2020-12','validExamples':len(records),'coveredRecordTypes':len(by_type),'negativeChecks':negative_checks,'referenceClosure':'passed for declared synthetic fixture registry','lineageCycleCheck':'passed','catalogLinkTypeReferences':'passed','limits':['设计契约与合成示例校验；未运行平台代码或数据库迁移','未验证外部源内容、资产字节/哈希、实际测量、模型效果或生产权限','跨单位、对象绑定、来源审核和撤回传播须平台集成测试验证']}
(ROOT/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))

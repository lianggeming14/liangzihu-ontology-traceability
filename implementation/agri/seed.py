"""Idempotent synthetic fixtures. No real farm or quality claims are created."""
import hashlib
import json
from pathlib import Path


def seed_demo(service, base: Path, persist_manifest=True):
    tenant = 'demo-farm'
    actor = {'id': 'synthetic-seeder', 'roles': ['admin']}
    def write(action, name, body):
        return service.mutate(action, tenant, actor, body, 'demo-v1:' + name)
    packages = [
        {'package_id': 'agri.core', 'version': '1.0.0', 'namespace': 'https://example.org/agri/core/',
         'types': [{'type_id': 'core:' + name, 'identity_type': name, 'label': label} for name, label in
                   [('field','田块'),('production_system','生产系统'),('production_batch','生产批次'),('lot','物料批次'),('package','包装'),('device','设备')]],
         'predicates': [
             {'predicate_id': 'core:locatedIn', 'subject_types': ['production_system','production_batch','device'], 'object_types': ['field'], 'dimension': 'space'},
             {'predicate_id': 'core:participatesIn', 'subject_types': ['production_batch'], 'object_types': ['production_system'], 'dimension': 'production'},
             {'predicate_id': 'core:monitors', 'subject_types': ['device'], 'object_types': ['field'], 'dimension': 'observation'}], 'dependencies': []},
        {'package_id':'agri.rice-crayfish','version':'1.0.0','namespace':'https://example.org/agri/rice-crayfish/',
         'types':[{'type_id':'rice:RiceCycle','identity_type':'production_batch','label':'水稻生产周期'},
                  {'type_id':'rice:CrayfishCycle','identity_type':'production_batch','label':'小龙虾养殖周期'}],
         'predicates':[], 'dependencies':[{'package_id':'agri.core','version':'1.0.0'}]},
        {'package_id':'agri.vegetable','version':'1.0.0','namespace':'https://example.org/agri/vegetable/',
         'types':[{'type_id':'vegetable:GrowingCycle','identity_type':'production_batch','label':'蔬菜种植周期'}],
         'predicates':[], 'dependencies':[{'package_id':'agri.core','version':'1.0.0'}]},
        {'package_id':'agri.poultry','version':'1.0.0','namespace':'https://example.org/agri/poultry/',
         'types':[{'type_id':'poultry:EggCycle','identity_type':'production_batch','label':'禽蛋产出周期'}],
         'predicates':[], 'dependencies':[{'package_id':'agri.core','version':'1.0.0'}]},
    ]
    for package in packages:
        write('register_package', package['package_id'], package)
    ids = {}
    def entity(alias, kind, name, package=None, type_id=None):
        body = {'entity_type': kind, 'name': name, 'attrs': {'synthetic': True}}
        if package:
            body['semantic_types'] = [{'package_id': package, 'version':'1.0.0', 'type_id':type_id}]
        result = write('create_entity', alias, body)
        ids[alias] = result['entity_key']
        return result['entity_key']
    entity('field','field','演示田块 F01')
    entity('system','production_system','虾稻共作系统 演示')
    entity('rice_cycle','production_batch','水稻生产周期 2026 演示','agri.rice-crayfish','rice:RiceCycle')
    entity('crayfish_cycle','production_batch','小龙虾养殖周期 演示','agri.rice-crayfish','rice:CrayfishCycle')
    entity('vegetable_cycle','production_batch','叶菜种植周期 演示','agri.vegetable','vegetable:GrowingCycle')
    entity('egg_cycle','production_batch','禽蛋收集周期 演示','agri.poultry','poultry:EggCycle')
    entity('device','device','水质测点 D01 演示')
    entity('package','package','精米包装组 P01 批次级演示')
    raw = json.dumps({'synthetic': True, 'note': '结构验证用合成凭证，不证明真实生产或质量合格',
                      'source':'synthetic-seeder', 'generated_for':'ontology-and-traceability-demo'},ensure_ascii=False).encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    folder = base / 'data' / 'assets' / hashlib.sha256(tenant.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / digest).write_bytes(raw)
    evidence = write('create_evidence','evidence',{'kind':'document','uri':'asset://' + digest,'content_hash':digest,
          'source_id':'synthetic-demo','public_summary':'演示凭证，仅用于验证系统链路',
          'metadata':{'synthetic':True,'asset_key':digest,'filename':'synthetic-evidence.json','media_type':'application/json'}})
    evidence_id = evidence['id']; ids['evidence'] = evidence_id
    for alias, source, predicate, target in [('system_location','system','core:locatedIn','field'),
          ('rice_participation','rice_cycle','core:participatesIn','system'),
          ('crayfish_participation','crayfish_cycle','core:participatesIn','system'),
          ('device_location','device','core:locatedIn','field'),('device_monitor','device','core:monitors','field')]:
        write('create_relation', alias, {'subject_key':ids[source],'object_key':ids[target],
              'package_id':'agri.core','package_version':'1.0.0','predicate_id':predicate,
              'valid_from':'2026-10-01T00:00:00+08:00','evidence_ids':[evidence_id], 'status':'accepted', 'qualifiers':{'synthetic':True}})
    write('create_observation','water_reading',{'subject_key':ids['field'],'property_id':'water:dissolvedOxygen',
          'value':{'value':'6.20','unit':'mg/L'},'observed_at':'2026-10-01T08:00:00+08:00','method':'synthetic-sensor',
          'origin':'reported','evidence_ids':[evidence_id]})
    def lot(alias, label, product, batch):
        result=write('create_lot',alias,{'name':label,'product_type':product,'unit':'kg',
                       'production_batch_key':ids[batch], 'attrs':{'synthetic':True}})
        ids[alias]=result.get('lot_key',result.get('entity_key',result.get('id')))
    for row in [('paddy','稻谷原料 L01','rice:paddy','rice_cycle'),('rice','精米 L02','rice:milled','rice_cycle'),
                ('byproduct','稻壳米糠副产物','rice:byproduct','rice_cycle'),('rice_a','精米批次 A','rice:milled','rice_cycle'),
                ('rice_b','精米批次 B','rice:milled','rice_cycle'),('crayfish','小龙虾起捕批次','crayfish:live','crayfish_cycle'),
                ('vegetable','叶菜采收批次','vegetable:leafy','vegetable_cycle'),('eggs','禽蛋收集批次','poultry:eggs','egg_cycle')]:
        lot(*row)
    def line(alias, qty):return {'lot_key':ids[alias],'quantity':qty,'unit':'kg'}
    def event(alias, typ, at, **fields):
        result=write('create_event',alias,{'event_type':typ,'occurred_at':at,'evidence_ids':[evidence_id],
                    'metadata':{'synthetic':True},**fields})
        ids[alias]=result['id'];return result['id']
    event('harvest','harvest','2026-10-02T08:00:00+08:00',outputs=[line('paddy','1000')],
          participants=[{'entity_key':ids['rice_cycle'],'role':'production_origin'}])
    event('milling','transform','2026-10-03T08:00:00+08:00',inputs=[line('paddy','600')],
          outputs=[line('rice','420'),line('byproduct','120')],loss_quantity='60',loss_unit='kg')
    event('split','split','2026-10-03T10:00:00+08:00',inputs=[line('rice','420')],
          outputs=[line('rice_a','200'),line('rice_b','220')],loss_quantity='0',loss_unit='kg')
    event('packing','package','2026-10-03T12:00:00+08:00',participants=[{'entity_key':ids['package'],'role':'container'},
          {'entity_key':ids['rice_a'],'role':'contained_item'}])
    event('shipping','ship','2026-10-04T08:00:00+08:00',items=[line('rice_a','50')])
    event('receiving','receive','2026-10-04T14:00:00+08:00',shipment_id=ids['shipping'],items=[line('rice_a','30')])
    for alias, batch, qty in [('crayfish','crayfish_cycle','80'),('vegetable','vegetable_cycle','150'),('eggs','egg_cycle','12')]:
        event(alias+'_harvest','harvest','2026-10-02T09:00:00+08:00',outputs=[line(alias,qty)],
              participants=[{'entity_key':ids[batch],'role':'production_origin'}])
    statement=write('create_assertion','origin_statement',{'subject_key':ids['rice_a'],'predicate_id':'trace:originDescription',
             'value':{'public_text':'本条仅演示批次来源信息的人工审核，不构成质量认证'},'evidence_ids':[evidence_id],'origin':'reported'})
    ids['assertion']=statement['id']
    write('review_assertion','origin_review',{'assertion_id':statement['id'],'status':'accepted','rationale':'审核合成示例的结构与来源引用，仅用于软件演示'})
    publication=write('publish','rice_publication',{'lot_key':ids['rice_a'],
           'summary':{'product_name':'梁子湖精米 演示批次','origin':'合成示例田块','description':'所有记录均为合成数据，未完成真实生产与质量验收'},
           'assertion_ids':[statement['id']],'evidence_ids':[evidence_id]})
    ids['public_code']=publication['public_code']
    ids['synthetic']=True
    (base / 'data').mkdir(exist_ok=True)
    if persist_manifest:
        (base / 'data' / 'demo-manifest.json').write_text(json.dumps(ids,ensure_ascii=False,indent=2),encoding='utf-8')
    return ids

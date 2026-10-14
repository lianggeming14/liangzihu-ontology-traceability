"""Discoverable API contract for the implemented engineering surface."""
import copy
import json


def describe(base, mutations, queries):
    schemas = json.loads((base / 'contracts' / 'input-schemas.json').read_text(encoding='utf-8'))
    from .device_ingestion import DEVICE_SCHEMAS
    schemas.update(copy.deepcopy(DEVICE_SCHEMAS))
    from .ontology_core import CORE_SCHEMAS
    from .core_intake import INTAKE_SCHEMAS
    schemas.update(copy.deepcopy(CORE_SCHEMAS))
    schemas.update(copy.deepcopy(INTAKE_SCHEMAS))
    schemas['Error'] = {'type': 'object', 'required': ['error'], 'properties': {'error': {'type': 'object', 'properties': {'code': {'type': 'string'}, 'message': {'type': 'string'}, 'request_id': {'type': ['string','null']}, 'details': {}}}}}
    schemas['Envelope'] = {'type': 'object', 'properties': {'data': {}, 'request_id': {'type': 'string'}}}
    paths = {}
    responses = {str(status): {'description': title, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/' + ('Envelope' if status == 200 else 'Error')}}}} for status, title in [(200,'成功；data 载荷因资源不同而不同'),(401,'未认证'),(403,'无权限或主机/来源受限'),(404,'不存在'),(409,'幂等、证据或业务状态冲突'),(413,'结构化请求超过2MiB或原件超过配置上限(默认32MiB)'),(422,'契约或业务约束不符')]}
    def param(name, kind='query', schema=None, required=False, description=''):
        return {'name':name,'in':kind,'required':required,'description':description,'schema':schema or {'type':'string'}}
    def op(action, public=False, parameters=None, description=''):
        return {'operationId':action,'security':[] if public else [{'bearerAuth':[]}], 'parameters':parameters or [],'description':description,'responses':copy.deepcopy(responses)}
    def body(operation, schema, media='application/json'):
        operation['requestBody']={'required':True,'content':{media:{'schema':schema}}}
    idem = param('Idempotency-Key','header',{'type':'string','minLength':1,'maxLength':200},True,'同一业务请求重试复用；键相同但内容不同返回 409。租户从认证身份取得。')
    page = [param('limit',schema={'type':'integer','minimum':1,'maximum':1000,'default':100}),param('offset',schema={'type':'integer','minimum':0,'default':0})]
    for path, action in mutations.items():
        operation=op(action,parameters=[idem]);body(operation,{'$ref':'#/components/schemas/'+action})
        paths.setdefault('/api/v1'+path,{})['post']=operation
    for path, action in queries.items():
        paths.setdefault('/api/v1'+path,{})['get']=op(action,parameters=copy.deepcopy(page) if action not in ('graph','stats','action_types') else [])
    graph_params=[param('center',description='可选的中心实体 UUID（entity_key）；虚拟关系/事件节点不能作为中心'),param('depth',schema={'type':'integer','minimum':1,'maximum':5,'default':3}),param('limit',schema={'type':'integer','minimum':1,'maximum':300,'default':150}),param('dimension',schema={'type':'string','enum':['all','identity','space','production','material','event','evidence','observation','assertion','device'],'default':'all'})]
    paths['/api/v1/ontology/entities']['get']['parameters'] += [param('entity_type'),param('name_contains')]
    paths['/api/v1/ontology/relations']['get']['parameters'] += [param('entity_key'),param('predicate_id'),param('dimension'),param('status',schema={'type':'string','enum':['accepted','candidate','rejected','needs_review','all'],'default':'accepted'}),param('valid_at',schema={'type':'string','format':'date-time'},description='仅过滤关系有效期，不重建当时知识快照')]
    paths['/api/v1/ontology/object-sets']['get']['parameters'].append(param('id'))
    for route, methods in paths.items():
        if 'get' in methods and any(p['name']=='offset' for p in methods['get']['parameters']):
            methods['get']['description']='当前集合的 offset/next_offset 分页；集合发生变化时不是冻结快照。需要可靠增量同步请用 trace/changes。'
    paths['/api/v1/ontology/graph']['get']['parameters']=graph_params
    paths['/api/v1/ontology/graph']['get']['description']='当前有界子图；必须处理 truncated/gaps。不支持 valid_at、known_at、revision 历史重建。候选断言不等同于已确认事实。'
    paths['/api/v1/trace/changes']['get']['parameters']=[param('cursor',description='首次省略；后续原样传 next_cursor'),page[0]]
    paths['/api/v1/trace/changes']['get']['description']='按租户递增 outbox。至少一次交付，消费端按事件 ID 去重，持久化业务结果后再保存游标；尚无 webhook 和 ACK 服务。'
    for route in ('observations','assertions','trace/events'):
        paths['/api/v1/'+route]['get']['parameters'].append(param('entity_key'))
    for route in ('trace/lots','trace/publications'):
        paths['/api/v1/'+route]['get']['parameters'].append(param('lot_key'))
    for path, action, key, public in [('/ontology/entities/{entity_key}','entity','entity_key',False),('/trace/lots/{lot_key}/lineage','lineage','lot_key',False),('/trace/lots/{lot_key}/bundle','trace_bundle','lot_key',False),('/inference/bundles/{entity_key}','evidence_bundle','entity_key',False),('/evidence/{evidence_id}','evidence_item','evidence_id',False),('/trace/events/{event_id}','event_item','event_id',False),('/public/trace/{code}','public_trace','code',True),('/public/trace/{code}/qr.svg','public_qr','code',True),('/evidence/{evidence_id}/asset','evidence_asset','evidence_id',False)]:
        paths['/api/v1'+path]={'get':op(action,public,[param(key,'path',required=True)])}
    paths['/api/v1/trace/lots/{lot_key}/lineage']['get']['parameters'] += [param('direction',schema={'type':'string','enum':['upstream','downstream'],'default':'upstream'}),param('depth',schema={'type':'integer','minimum':1,'maximum':30,'default':10}),param('max_nodes',schema={'type':'integer','minimum':1,'maximum':2000,'default':200})]
    paths['/api/v1/public/trace/{code}']['get']['description']='无需私有身份；字段白名单输出。每次读取检查当前撤回和召回状态；历史正文冻结不代表持续有效。'
    for path, media, desc in [('/public/trace/{code}/qr.svg','image/svg+xml','公开页 URL 的 QR SVG；本地回环地址不能用于手机外部扫码。'),('/evidence/{evidence_id}/asset','application/octet-stream','有权限且哈希完整性通过后下载原件；原件不公开。')]:
        operation=paths['/api/v1'+path]['get'];operation['description']=desc
        operation['responses']['200']={'description':desc,'content':{media:{'schema':{'type':'string','format':'binary'}}}}
    export=op('graph_export',parameters=graph_params+[param('format',schema={'type':'string','enum':['jsonld','turtle'],'default':'jsonld'})],description='agri-graph-exchange/1.0 专用配置。原生 JSON-LD 可用 exchange.from_jsonld 还原为图数据；不代表任意 OWL/RDF 自动互转或导入数据库。')
    export['responses']['200']={'description':'有界图谱导出','content':{'application/ld+json':{'schema':{'type':'object'}},'text/turtle':{'schema':{'type':'string'}}}}
    paths['/api/v1/ontology/export']={'get':export}
    source_kind={'type':'string','enum':['sensor','weather','image','video','remote_sensing','document','manual','official_api']}
    asset=op('upload_asset',parameters=[idem],description='原件保存在租户私有目录，生成 SHA-256 和证据记录；原件默认限制32MiB(请求33MiB，管理员可配置)；仅做载体签名/图片结构校验，不解码视频、不生成预览、不执行识别。metadata.carrier 与原件哈希、外部processing状态分开，内容矛盾保留原件并标needs_mapping。')
    body(asset,{'type':'object','required':['file'],'properties':{'file':{'type':'string','format':'binary'},'source_kind':source_kind,'source_id':{'type':'string'},'public_summary':{'type':'string'}}},'multipart/form-data')
    paths['/api/v1/ingestion/assets']={'post':asset}
    records=op('ingest_records',parameters=[param('Idempotency-Key','header',{'type':'string','minLength':1,'maxLength':150},True)],description='逐条事务，可部分成功，必须检查 receipts。原样重试保留相同键及顺序；图像/视频/遥感观测标为 estimated，forecast 和 model_candidate 均需后续审核。原件引用必填。')
    alternatives=[]
    for kind, action in [('observation','create_observation'),('assertion','create_assertion'),('forecast','create_assertion'),('model_candidate','create_assertion'),('event','create_event')]:
        alternatives.append({'type':'object','required':['record_kind','payload'],'properties':{'record_kind':{'const':kind},'payload':{'$ref':'#/components/schemas/'+action}}})
    body(records,{'type':'object','required':['source_kind','records'],'properties':{'source_kind':source_kind,'synthetic':{'type':'boolean'},'records':{'type':'array','minItems':1,'maxItems':100,'items':{'oneOf':alternatives}}}})
    paths['/api/v1/ingestion/records']={'post':records}
    for path, filters in [('/devices',['id','device_kind','bound_entity_key']),('/device-policies',['id','device_id']),('/device-records',['id','device_id','record_type'])]:
        paths['/api/v1'+path]['get']['parameters']=[param('limit',schema={'type':'integer','minimum':1,'maximum':500,'default':100}),page[1]]+[param(name) for name in filters]
    status_op=op('set_capture_policy_status',parameters=[idem,param('policy_id','path',required=True)],description='显式启停不可变采集策略；不执行闸门命令。')
    body(status_op,{'type':'object','required':['enabled'],'properties':{'enabled':{'type':'boolean'}},'additionalProperties':False})
    paths['/api/v1/device-policies/{policy_id}/status']={'post':status_op}
    paths['/api/v1/device-captures/due']['get']['parameters']=[param('since',schema={'type':'string','format':'date-time'},required=True),param('as_of',schema={'type':'string','format':'date-time'}),param('device_id'),param('limit',schema={'type':'integer','minimum':1,'maximum':500}),page[1]]
    paths['/api/v1/device-captures/due']['get']['description']='仅未收到回执的计划时点；最多七天/500策略/10000槽。周期与重点窗口并集，时点重复合并，窗口半开。不是已执行记录。查询期间回执会改变分页集合，网关应先完整取页再执行。'
    paths['/api/v1/ingestion/manual']['post']['description']='原始人工表单、操作者和接收时间生成内嵌原文证据；证据与记录在同一幂等事务中提交或回滚。人工观测固定reported，陈述为manual候选，不自动采纳。现场事件不修改库存。'
    preview=op('evidence_preview',parameters=[param('evidence_id','path',required=True),param('frame',schema={'type':'integer','minimum':0,'default':0})],description='兼容旧版已经生成的JPEG派生预览；新上传不再生成预览。每次验证哈希、租户与撤回状态。')
    preview['responses']['200']={'description':'受控JPEG预览','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}
    paths['/api/v1/evidence/{evidence_id}/preview']={'get':preview}
    paths['/api/v1/ontology/properties']['get']['parameters'] += [param(n) for n in ('package_id','version','type_id','usage','entity_key','at')]
    paths['/api/v1/ontology/properties']['get']['description']='按对象有效语义类返回可用属性；at 为有效时点，并非知识历史快照。观测同时校验精确包版本、类、单位和值类型。'
    paths['/api/v1/ontology/packages']['get']['parameters'] += [param('package_id'),param('version')]
    paths['/api/v1/ontology/packages']['get']['description']='返回结构化类/属性/关系和独立显示名revision；原定义与content_hash保持不变。'
    paths['/api/v1/ontology/package-labels']['post']['description']='只修改本体、类、属性和关系显示名；expected_revision控制并发。语义结构变更须另发包版本。'
    paths['/api/v1/ingestion/mappings']['get']['parameters'] += [param(n) for n in ('source_id','mapping_id','version')]
    paths['/api/v1/ingestion/mappings']['post']['description']='登记不可变的显式来源映射版本；只允许字段路径、单位缩放、枚举及时区转换，不执行代码或模型。'
    paths['/api/v1/ingestion/receipts']['post']['description']='合法接入信封生成原文证据及持久回执。必须检查data.status：needs_mapping/validation_failed/stored；HTTP 200不等同目标数据已入库。相同来源记录冲突返回409。'
    paths['/api/v1/ingestion/receipts']['get']['parameters'] += [param(n) for n in ('status','source_id')]
    paths['/api/v1/ingestion/receipts/{receipt_id}']={'get':op('intake_receipt',parameters=[param('receipt_id','path',required=True)])}
    retry=op('retry_intake',parameters=[idem,param('receipt_id','path',required=True)],description='以指定映射版本重试原始信封，追加attempt历史；stored回执不可重复生成目标记录。')
    retry_schema=copy.deepcopy(schemas['retry_intake'])
    retry_schema['required']=[key for key in retry_schema.get('required',[]) if key!='receipt_id']
    body(retry,retry_schema)
    paths['/api/v1/ingestion/receipts/{receipt_id}/retry']={'post':retry}
    intake_preview=op('preview_intake',description='只读样本预览；所有临时写入回滚，不创建回执、证据、audit、outbox或幂等键。输出状态与issues，不能当正式接收确认。')
    body(intake_preview,{'$ref':'#/components/schemas/receive_intake'})
    paths['/api/v1/ingestion/preview']={'post':intake_preview}
    for route,methods in paths.items():
        compatibility=route.startswith(('/api/v1/devices','/api/v1/device-','/api/v1/trace/','/api/v1/public/trace')) or route.endswith('/preview') and '/evidence/' in route or route=='/api/v1/ingestion/records'
        for method,operation in methods.items():
            operation['tags']=['compatibility-extensions' if compatibility else 'database-core']
    paths['/api/v1/health']={'get':op('health',True,description='进程状态；不是数据库恢复、现场接入或生产验收证明。')}
    paths['/api/v1/auth/me']={'get':op('me')}
    login=op('demo_login',True,description='仅启用本地演示且来源回环时可用。生产必须关闭。')
    body(login,{'type':'object','properties':{'role':{'type':'string','enum':['admin','operator','reviewer','viewer'],'default':'viewer'}}})
    paths['/api/v1/auth/demo']={'post':login};paths['/api/v1/auth/logout']={'post':op('logout',True)}
    paths['/api/v1/openapi.json']={'get':op('openapi',True)}
    return {'openapi':'3.1.0','info':{'title':'梁子湖农业本体数据库 API','version':'0.3.0','description':'数据库职责收敛版：本体、显式映射、受约束存储、原件与血缘、数据输出；旧采集和产品溯源为兼容扩展。租户身份由访问令牌确定；演示界面另外支持仅限回环的 Cookie 会话。响应载荷仍以领域实现和示例为准，Envelope 不构成完整强类型 SDK。真实平台、PostgreSQL 和现场验收待完成。'},'servers':[{'url':'/'}],'paths':paths,'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}},'schemas':schemas}}

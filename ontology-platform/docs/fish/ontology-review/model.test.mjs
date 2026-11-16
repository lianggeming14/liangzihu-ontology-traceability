import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import * as lazyModel from './model.mjs';
import { createCatalog, pageInstances, routeHash, readRoute, relationTarget, demoTarget, propertyUnit, decodeSnapshot, formatValue, natureLabel, instanceNature } from './model.mjs';

const manifest = { contract:'fish-rdf-review/1', concepts:[
  {iri:'root',label:'本体',parent_iri:null,children:['domain'],table:null},
  {iri:'domain',label:'空间资源',parent_iri:'root',children:['pond'],table:null},
  {iri:'pond',label:'塘口',parent_iri:'domain',children:[],table:'ponds',instances_path:'classes/ponds.json'},
] };

test('navigation follows the supplied ontology hierarchy',()=>{
  const catalog=createCatalog(manifest);
  assert.deepEqual(catalog.top.map(v=>v.iri),['domain']);
  assert.deepEqual(catalog.path('pond').map(v=>v.label),['本体','空间资源','塘口']);
  assert.deepEqual(catalog.children('domain').map(v=>v.iri),['pond']);
});
test('unknown parents, cycles and unsafe fragment paths fail closed',()=>{
  for(const concepts of [
    [{iri:'x',parent_iri:'absent',children:[]}],
    [{iri:'x',parent_iri:'y',children:['y']},{iri:'y',parent_iri:'x',children:['x']}],
    [{iri:'x',parent_iri:null,children:[],instances_path:'../private.json'}],
  ]) assert.throws(()=>createCatalog({...manifest,concepts}));
});
test('instance paging stays within selected class and resets beyond the last page',()=>{
  const rows=Array.from({length:25},(_,i)=>({id:`P${i+1}`,label:`塘口 ${i+1}`}));
  assert.equal(pageInstances(rows,'',2,12).items[0].id,'P13');
  assert.equal(pageInstances(rows,'P25',9,12).page,1);
  assert.equal(pageInstances(rows,'P25',9,12).items[0].id,'P25');
});
test('IRI routes survive hash encoding and relation back/forward state',()=>{
  const route={view:'instance',iri:'urn:example:塘口/P01',class:'urn:class:pond',tab:'relations',page:2};
  assert.deepEqual(readRoute(routeHash(route)),route);
  assert.equal(readRoute('#view=unsupported').view,'home');
});
test('CAD instance map routes require the exact published IRI and class, including unlocated objects',()=>{
  assert.equal(typeof lazyModel.spatialObjectRoute,'function');
  const row={iri:'urn:lzo:cad-gis:v1:instance:设施/甲&乙',class_iri:'urn:lzo:cad-gis:v1:class:facility',kind:'facility'};
  const data={contract:'lzo-spatial-map/2',features:[],unlocated:[{...row,geometry:null}]};
  const route=lazyModel.spatialObjectRoute(row,data);
  assert.deepEqual(route,{view:'map',object:row.iri});assert.deepEqual(readRoute(routeHash(route)),route);
  assert.deepEqual(lazyModel.spatialObjectRoute(row,{...data,features:[{...row,geometry:{type:'Point',coordinates:[114,30]}}],unlocated:[]}),route);
  assert.equal(lazyModel.spatialObjectRoute({...row,iri:'urn:lzo:cad-gis:v1:instance:same-label'},data),null);
  assert.equal(lazyModel.spatialObjectRoute({...row,class_iri:'urn:lzo:cad-gis:v1:class:camera'},data),null);
});
test('CAD map links do not rewrite legacy feature or historical-map routes',()=>{
  assert.equal(typeof lazyModel.spatialObjectRoute,'function');
  const row={iri:'urn:lzo:fish-review:map:one',class_iri:'urn:lzo:fish-review:map:pond',kind:'pond'};
  assert.equal(lazyModel.spatialObjectRoute(row,{contract:'lzo-spatial-map/2',features:[row]}),null);
  assert.equal(lazyModel.spatialObjectRoute({...row,iri:'urn:lzo:cad-gis:v1:instance:a'},{schema_version:'farm-local-map/1',layers:[]}),null);
  const route={view:'feature',historical:'1',layer:'drawing',iri:'original-feature'};assert.deepEqual(readRoute(routeHash(route)),route);
});
test('only resolved relations can navigate to a real supplied endpoint',()=>{
  assert.equal(relationTarget({resolution:'unresolved',target_iri:'fake'},'outgoing'),null);
  assert.deepEqual(relationTarget({resolution:'resolved',target_iri:'target',target_class_iri:'class'},'outgoing'),
    {iri:'target',class:'class'});
  assert.deepEqual(relationTarget({resolution:'resolved',source_iri:'source',source_class_iri:'class'},'incoming'),
    {iri:'source',class:'class'});
});
test('missing measurement and exact decimal text are retained',()=>{
  assert.equal(formatValue(null),'未提供');
  assert.equal(formatValue('999999999999.123456789'),'999999999999.123456789');
  assert.equal(natureLabel('synthetic'),'合成场景');
  assert.equal(natureLabel('derived_simulation'),'模拟边界计算值');
});
test('gzip fragments use the same strict relative class path',()=>{
  assert.equal(createCatalog({...manifest,concepts:[{iri:'x',parent_iri:null,children:[],instances_path:'classes/ponds.json.gz'}]}).byId.get('x').instances_path,'classes/ponds.json.gz');
});
test('demo assignments remain separately labeled and must explicitly be synthetic',()=>{
  const edge={direction:'incoming',source_iri:'business',source_class_iri:'activity',assignment_policy:'balanced_demo_only',synthetic:true};
  assert.deepEqual(demoTarget(edge),{iri:'business',class:'activity'});
  assert.equal(demoTarget({...edge,synthetic:false}),null);
  assert.equal(demoTarget({...edge,assignment_policy:'actual_ownership'}),null);
});
test('original and SI numeric values use only their own explicit sibling units',()=>{
  const properties=[{field:'numericValue',value:'1.29',unit:null},{field:'unitText',value:'亩'},
    {field:'siValue',value:'860.0',unit:null},{field:'siUnit',value:'m2'}];
  assert.equal(propertyUnit(properties[0],properties),'亩');
  assert.equal(propertyUnit(properties[2],properties),'m2');
  assert.equal(propertyUnit(properties[0],properties.slice(0,1)),null);
});
test('explicit unadopted scenario evidence is distinguished from surveyed values',()=>{
  assert.equal(instanceNature({nature:'imported_unverified',properties:[{field:'reviewStatus',value:'scenario_only_not_adopted'}]}),'场景估算 · 未采用');
  assert.equal(instanceNature({nature:'imported_unverified',properties:[{field:'reviewStatus',value:'computed_paper_geometry_not_ground_survey'}]}),'纸面几何计算 · 非实测');
});

test('complete CSV adoption status remains distinct from preserved legacy review samples',()=>{
  assert.equal(lazyModel.instanceAdoption({adoption_status:'csv_batch_not_formally_adopted'}),'完整 CSV 批次 · 未正式采用');
  assert.equal(lazyModel.instanceAdoption({provenance:{sample_reason:'full_csv_batch'}}),'完整 CSV 批次 · 未正式采用');
  assert.equal(lazyModel.instanceAdoption({nature:'synthetic',provenance:{sample_reason:'stratified_seed'}}),'审阅样本 · 未正式采用');
});

const csvSummary={iri:'urn:csv:pond:two',id:'two',label:'CSV 塘口二',class_iri:'urn:csv:Pond',table:'ponds',nature:'synthetic',detail_path:'details/csv_ponds/00001.json.gz'};
const csvDetail={...csvSummary,properties:[{field:'area',value:'12.3456789'}],incoming:[],outgoing:[],provenance:{source_file:'ponds.csv',source_sha256:'abc'}};
const compressedResponse=value=>new Response(gzipSync(JSON.stringify(value)));

test('detail loading decodes only the requested gzip chunk and selects the exact IRI',async()=>{
  const paths=[];
  const loader=lazyModel.createSnapshotLoader(async path=>{
    paths.push(path);
    return decodeSnapshot(compressedResponse({contract:'fish-rdf-review/1',class_iri:csvSummary.class_iri,instances:[{...csvDetail,iri:'urn:csv:pond:one'},csvDetail]}));
  });
  const legacy={iri:'legacy',properties:[]};
  assert.equal(await loader.detail(legacy,'legacy-class'),legacy);
  assert.deepEqual(paths,[]);
  assert.equal((await loader.detail(csvSummary,csvSummary.class_iri)).iri,'urn:csv:pond:two');
  assert.equal((await loader.detail(csvSummary,csvSummary.class_iri)).properties[0].value,'12.3456789');
  assert.deepEqual(paths,['details/csv_ponds/00001.json.gz']);
});

test('detail and relation paths reject traversal, protocols, encoding and non-gzip assets before reading',async()=>{
  const loader=lazyModel.createSnapshotLoader(async()=>{assert.fail('unsafe path was read');});
  for(const detail_path of ['../private.json.gz','/details/csv_ponds/00001.json.gz','https://example.com/x.json.gz','details/csv_ponds/../x.json.gz','details\\csv_ponds\\00001.json.gz','details/csv_ponds/%2e%2e.json.gz','details/csv_ponds/a.json.gz?q=1','details/csv_ponds/a.json.gz#x','details/csv_ponds/a.json.gz\n','details/csv_ponds/a.json','relations/csv_ponds/x/incoming-00001.json.gz']){
    await assert.rejects(()=>loader.detail({...csvSummary,detail_path},csvSummary.class_iri),/路径/);
  }
  for(const path of ['../relations/a.json.gz','relations/csv_ponds/../../incoming-00001.json.gz','relations/csv_ponds/x/incoming-00001.json.gz?secret=1','details/csv_ponds/00001.json.gz']){
    await assert.rejects(()=>loader.relations({iri:csvSummary.iri,incoming:[],incoming_count:1,incoming_page_size:4800,incoming_pages:[path]},'incoming',1),/路径/);
  }
});

test('detail chunks reject a different contract, class, missing IRI or mismatched instance class',async()=>{
  for(const chunk of [
    {contract:'wrong',class_iri:csvSummary.class_iri,instances:[csvDetail]},
    {contract:'fish-rdf-review/1',class_iri:'wrong-class',instances:[csvDetail]},
    {contract:'fish-rdf-review/1',class_iri:csvSummary.class_iri,instances:[{...csvDetail,iri:'another-object'}]},
    {contract:'fish-rdf-review/1',class_iri:csvSummary.class_iri,instances:[{...csvDetail,class_iri:'wrong-class'}]},
  ]){
    const loader=lazyModel.createSnapshotLoader(async()=>chunk);
    await assert.rejects(()=>loader.detail(csvSummary,csvSummary.class_iri),/实例|类型|格式/);
  }
});

test('legacy inline relations keep their pages and declared external counts are retained',async()=>{
  const loader=lazyModel.createSnapshotLoader(async()=>assert.fail('legacy relations fetched a chunk'));
  const row={outgoing:Array.from({length:13},(_,i)=>({target_id:String(i)})),incoming:[]};
  assert.deepEqual(await loader.relations(row,'outgoing',2),{items:[{target_id:'12'}],page:2,pages:2,total:13});
  assert.equal(lazyModel.relationCount(row,'outgoing'),13);
  assert.equal(lazyModel.relationCount({incoming:[],incoming_count:9601},'incoming'),9601);
});

test('global relation pages cross 4800-edge gzip chunks without loading adjacent chunks',async()=>{
  const paths=[];
  const row={iri:csvSummary.iri,incoming:[],incoming_count:9601,incoming_page_size:4800,incoming_pages:[1,2,3].map(n=>`relations/csv_ponds/abc/incoming-${String(n).padStart(5,'0')}.json.gz`)};
  const loader=lazyModel.createSnapshotLoader(async path=>{
    paths.push(path);
    const index=Number(path.match(/(\d+)\.json/)[1])-1;
    const edges=Array.from({length:index===2?1:4800},(_,i)=>({source_id:String(index*4800+i)}));
    return decodeSnapshot(compressedResponse({contract:'fish-rdf-relations/1',instance_iri:row.iri,direction:'incoming',edges}));
  });
  let page=await loader.relations(row,'incoming',400);
  assert.deepEqual([page.items[0].source_id,page.items.at(-1).source_id,page.page,page.pages,page.total],['4788','4799',400,801,9601]);
  assert.equal(paths.length,1);
  page=await loader.relations(row,'incoming',401);
  assert.deepEqual([page.items[0].source_id,page.items.at(-1).source_id],['4800','4811']);
  assert.equal(paths.length,2);
  assert.equal((await loader.relations(row,'incoming',402)).items[0].source_id,'4812');
  assert.equal(paths.length,2);
  page=await loader.relations(row,'incoming',9999);
  assert.deepEqual([page.items.map(edge=>edge.source_id),page.page,page.pages],[['9600'],801,801]);
  assert.deepEqual(paths,row.incoming_pages);
});

test('relation chunks reject a wrong identity, direction, contract or truncated edge array',async()=>{
  const row={iri:csvSummary.iri,outgoing:[],outgoing_count:1,outgoing_page_size:4800,outgoing_pages:['relations/csv_ponds/abc/outgoing-00001.json.gz']};
  const good={contract:'fish-rdf-relations/1',instance_iri:row.iri,direction:'outgoing',edges:[{target_id:'one'}]};
  for(const chunk of [{...good,contract:'wrong'},{...good,instance_iri:'another'},{...good,direction:'incoming'},{...good,edges:[]}]){
    const loader=lazyModel.createSnapshotLoader(async()=>chunk);
    await assert.rejects(()=>loader.relations(row,'outgoing',1),/关系/);
  }
});

test('failed snapshot reads can retry and external relation metadata fails closed',async()=>{
  let attempts=0;
  const loader=lazyModel.createSnapshotLoader(async()=>{
    if(++attempts===1)throw Error('temporary failure');
    return {contract:'fish-rdf-review/1',class_iri:csvSummary.class_iri,instances:[csvDetail]};
  });
  await assert.rejects(()=>loader.detail(csvSummary,csvSummary.class_iri),/temporary/);
  assert.equal((await loader.detail(csvSummary,csvSummary.class_iri)).iri,csvSummary.iri);
  assert.equal(attempts,2);
  for(const extra of [
    {incoming_count:-1,incoming_page_size:4800,incoming_pages:[]},
    {incoming_count:1,incoming_page_size:0,incoming_pages:['relations/csv_ponds/x/incoming-00001.json.gz']},
    {incoming_count:4801,incoming_page_size:4800,incoming_pages:['relations/csv_ponds/x/incoming-00001.json.gz']},
  ])await assert.rejects(()=>loader.relations({iri:csvSummary.iri,incoming:[],...extra},'incoming',1),/关系/);
});
test('published manifest and every real gzip shard load with the browser decoder',async()=>{
  const real=await decodeSnapshot(new Response(await readFile(new URL('./data/manifest.json',import.meta.url))));
  const index=createCatalog(real);
  let rows=0,shards=0,demo=0,measurements=0;
  for(const concept of index.byId.values()){
    if(!concept.instances_path)continue;
    const shard=await decodeSnapshot(new Response(await readFile(new URL('./data/'+concept.instances_path,import.meta.url))));
    assert.equal(shard.contract,'fish-rdf-review/1');assert.equal(shard.class_iri,concept.iri);
    assert.equal(shard.instances.length,concept.instance_count);
    shards++;rows+=shard.instances.length;
    for(const row of shard.instances){
      for(const edge of row.demo_assignments||[]){assert.ok(demoTarget(edge));demo++;}
      for(const property of row.properties||[])if(property.field==='numericValue'&&row.properties.some(p=>p.field==='unitText'&&p.value)){assert.ok(propertyUnit(property,row.properties));measurements++;}
    }
  }
  assert.equal(rows,real.counts.instances);assert.equal(shards,real.counts.source_classes);
  assert.ok(demo>=real.counts.demo_assignments);assert.ok(measurements>0);
});

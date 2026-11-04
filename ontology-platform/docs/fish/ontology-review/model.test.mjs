import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
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

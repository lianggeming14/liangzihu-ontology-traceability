// Real Chrome acceptance of the published CSV lazy snapshots and legacy map data.
import assert from 'node:assert/strict';
import {chromium} from '../frontend/node_modules/@playwright/test/index.mjs';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import {createCatalog,decodeSnapshot,relationCount,relationTarget,routeHash,formatValue} from '../docs/fish/ontology-review/model.mjs';

const {values:options}=parseArgs({options:{'base-url':{type:'string',default:'http://127.0.0.1:8792/'},'executable-path':{type:'string',default:'C:/Program Files/Google/Chrome/Application/chrome.exe'}}});
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../docs/fish/ontology-review');
const endpoint=new URL(options['base-url']);
if(endpoint.protocol!=='http:'||endpoint.hostname!=='127.0.0.1'||!endpoint.port||endpoint.username||endpoint.password||endpoint.search||endpoint.hash)throw Error('Explicit local review server URL required');
const base=endpoint.href.endsWith('/')?endpoint.href:endpoint.href+'/';
const local=async relative=>decodeSnapshot(new Response(await readFile(path.join(root,relative))));
const manifest=await local('data/manifest.json'),catalog=createCatalog(manifest);
const concept=manifest.concepts.find(c=>c.instances_path==='classes/csv_ponds.json.gz');
assert.ok(concept,'published CSV pond class is required');
const summaries=(await local('data/'+concept.instances_path)).instances;
const details=new Map();
let selected;
for(const summary of summaries){
  assert.ok(summary.detail_path,'CSV summaries must keep their lazy detail paths');
  if(!details.has(summary.detail_path))details.set(summary.detail_path,await local('data/'+summary.detail_path));
  const detail=details.get(summary.detail_path).instances.find(row=>row.iri===summary.iri);
  assert.ok(detail,'detail IRI is present');
  if(!selected||relationCount(detail,'incoming')>relationCount(selected,'incoming'))selected=detail;
}
assert.ok(selected&&selected.incoming_pages?.length>1,'a CSV pond with multiple external incoming chunks is required');
const summary=summaries.find(row=>row.iri===selected.iri);
const browser=await chromium.launch({headless:true,executablePath:options['executable-path']});
const report={contract:'fish-csv-browser-readback/1',checked_at:new Date().toISOString(),source:'published full CSV snapshots and preserved legacy shards',data_nature:{record_nature:selected.nature,source_origin_kind:selected.provenance?.source_origin_kind,field_acceptance:false},database_writes:false,checks:{},screenshots:[]};
const errors=[];
await mkdir(path.join(root,'screenshots'),{recursive:true});
try{
  const page=await browser.newPage({viewport:{width:1500,height:1050}}),requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{const relative=new URL(request.url()).pathname.replace(/^\/data\//,'');if(/^(details|relations)\//.test(relative))requests.push(relative);});
  // Deterministic snapshot navigation; live Fuseki acceptance is recorded separately.
  await page.route('**/api/ontology/**',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
  const sameIri=async iri=>page.waitForFunction(value=>document.querySelector('.object-iri')?.textContent===value,iri);
  const incoming=()=>page.locator('#object-panel .relation-section').nth(1);
  const incomingChunkCount=()=>requests.filter(p=>p.startsWith('relations/')&&p.includes('/incoming-')).length;
  const noOverflow=async p=>assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow');
  const shot=async(name,p=page)=>{await p.screenshot({path:path.join(root,'screenshots',name),fullPage:false});report.screenshots.push('screenshots/'+name);};
  const incomingEdges=async index=>(await local('data/'+selected.incoming_pages[index])).edges;
  const expectedPage=async number=>{
    const start=(number-1)*12,index=Math.floor(start/selected.incoming_page_size);
    return (await incomingEdges(index)).slice(start%selected.incoming_page_size,start%selected.incoming_page_size+12);
  };
  const assertIncoming=async number=>{
    const expected=await expectedPage(number);
    const cards=expected.map(edge=>[edge.resolution==='resolved'?edge.source_iri:null,edge.source_label||edge.source_id||'来源未标注名称']);
    await page.waitForFunction(want=>{const section=document.querySelectorAll('#object-panel .relation-section')[1];return section&&JSON.stringify([...section.querySelectorAll('.relation-card')].map(card=>[card.getAttribute('data-relation'),card.querySelector('strong')?.textContent]))===JSON.stringify(want);},cards);
    assert.equal(await incoming().locator('.relation-card').count(),expected.length);
    assert.equal((await incoming().locator('.relation-heading').innerText()).includes(selected.incoming_count.toLocaleString('zh-CN')),true);
    return expected;
  };
  await page.goto(base);await page.locator('[data-concept]').first().waitFor();
  const hasCsvBatches=Array.isArray(manifest.csv_batches)?manifest.csv_batches.length>0:!!manifest.csv_batches;
  const homeSource=await page.locator('.source-note').last().innerText();
  assert.ok(homeSource.includes(hasCsvBatches?'已接入完整CSV批次':'养殖数据是审阅样本'),'home source note matches the published CSV batch state');
  if(hasCsvBatches)assert.ok(homeSource.includes('模拟数据/天气再分析各自标明，不能当实测。'));
  report.checks.home_source_note=true;
  await shot('desktop-csv-overview.png');
  report.checks.hierarchy_click_path=[];
  for(const item of catalog.path(concept.iri).filter(item=>!catalog.roots.some(root=>root.iri===item.iri))){
    await page.locator(`[data-concept="${item.iri}"]`).click();
    await page.locator('h1').filter({hasText:item.label}).waitFor();
    report.checks.hierarchy_click_path.push({iri:item.iri,label:item.label});
  }
  await page.locator('[data-instance]').first().waitFor();
  assert.deepEqual(requests,[],'class listing must not load object details or relations');
  assert.ok((await page.locator('.instance-card-foot').first().innerText()).includes('按需读取'));
  report.checks.hierarchy_and_summary_only=true;
  await page.locator('#instance-search').fill(selected.id);
  await page.locator(`[data-instance="${selected.iri}"]`).click();await sameIri(selected.iri);
  assert.equal(await page.locator('.property-row').count(),selected.properties.length);
  assert.deepEqual((await page.locator('.property-value').allTextContents()).sort(),selected.properties.map(property=>formatValue(property.value)).sort());
  assert.deepEqual(requests,[summary.detail_path],'one requested detail chunk only');
  report.checks.exact_detail_and_properties={iri:selected.iri,properties:selected.properties.length,detail:summary.detail_path};
  await page.locator('[data-tab=evidence]').click();await page.locator('#object-panel .evidence-card').first().waitFor();
  for(const key of ['source_file','source_sha256','source_file_sha256','batch_id'])if(selected.provenance?.[key])assert.ok((await page.locator('#object-panel').innerText()).includes(String(selected.provenance[key])),key+' is visible');
  assert.equal(requests.filter(p=>p.startsWith('details/')).length,1,'tab switch uses the cached detail chunk');
  report.checks.source_provenance=true;
  await page.locator('[data-tab=relations]').click();await assertIncoming(1);
  assert.equal(incomingChunkCount(),1);
  await incoming().locator('[data-action=relation-page]').last().click();const second=await assertIncoming(2);
  assert.equal(incomingChunkCount(),1,'page two uses the already cached first relation chunk');
  const returnHash=new URL(page.url()).hash,target=relationTarget(second[0],'incoming');
  assert.ok(target,'resolved incoming relation is navigable');
  await incoming().locator('[data-relation]').first().click();await sameIri(target.iri);
  await page.locator('#go-back').click();await sameIri(selected.iri);await assertIncoming(2);
  assert.equal(new URL(page.url()).hash,returnHash,'Back restores the relation page');
  report.checks.relation_navigation_back_and_cache=true;
  const atBoundary={view:'instance',iri:selected.iri,class:selected.class_iri,tab:'relations',incomingPage:400};
  await page.evaluate(hash=>{location.hash=hash;},routeHash(atBoundary));await assertIncoming(400);
  const beforeBoundary=incomingChunkCount();
  await incoming().locator('[data-action=relation-page]').last().click();await assertIncoming(401);
  assert.equal(incomingChunkCount(),beforeBoundary+1,'crossing 4800 loads exactly one new external chunk');
  report.checks.chunk_boundary_400_to_401=true;
  const last=Math.ceil(selected.incoming_count/12);
  await page.evaluate(hash=>{location.hash=hash;},routeHash({...atBoundary,incomingPage:last}));await assertIncoming(last);
  assert.equal(await incoming().locator('[data-action=relation-page]').last().isDisabled(),true);
  assert.equal(await incoming().locator('[data-action=relation-page]').first().isDisabled(),false);
  report.checks.final_page={page:last,total:selected.incoming_count};
  await noOverflow(page);await shot('desktop-csv-relations.png');
  await page.locator('[data-tab=rdf]').click();await page.locator('#object-panel .source-note').waitFor();await assertIncoming(last);
  assert.ok((await page.locator('#object-panel').innerText()).includes('未连接实时 SPARQL'));
  report.checks.csv_rdf_snapshot_pagination=true;
  const beforeLegacy=requests.length,maps=await local('data/map-features.json');
  await page.locator('[data-view=map]').click();await page.locator('#source-map').waitFor();
  await shot('desktop-legacy-map.png');
  report.checks.legacy_map_layers=[];
  for(const layer of maps.layers){
    await page.selectOption('#map-layer',layer.id);await page.waitForFunction(id=>document.querySelector('#source-map')?.dataset.layer===id,layer.id);
    assert.equal(await page.locator('#source-map .map-feature').count(),layer.features.length);await noOverflow(page);
    report.checks.legacy_map_layers.push({id:layer.id,features:layer.features.length});
  }
  const layer=maps.layers.find(layer=>layer.features.some(feature=>feature.properties?.object_iri&&catalog.byId.has(feature.properties.object_class_iri)));
  const index=layer.features.findIndex(feature=>feature.properties?.object_iri&&catalog.byId.has(feature.properties.object_class_iri));
  await page.selectOption('#map-layer',layer.id);await page.waitForFunction(id=>document.querySelector('#source-map')?.dataset.layer===id,layer.id);
  await page.locator(`.map-feature-button[data-feature="${index}"]`).click();await sameIri(layer.features[index].properties.object_iri);
  assert.equal(requests.length,beforeLegacy,'legacy map objects keep their embedded shard behavior');
  await page.locator('[data-tab=relations]').click();await page.locator('#object-panel .relation-section').first().waitFor();
  await shot('desktop-legacy-map-object.png');report.checks.legacy_map_object_and_relations={navigation:'visible map object list',iri:layer.features[index].properties.object_iri};
  const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  mobile.on('pageerror',error=>errors.push(error.message));
  await mobile.route('**/api/ontology/**',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
  await mobile.goto(base+routeHash({view:'instance',iri:selected.iri,class:selected.class_iri,tab:'relations'}));
  await mobile.locator('.object-header').waitFor();await noOverflow(mobile);await shot('mobile-csv-relations.png',mobile);report.checks.mobile_csv_no_overflow=true;
  const legacyHome=await browser.newPage(),legacyManifest={...manifest};delete legacyManifest.csv_batches;
  legacyHome.on('pageerror',error=>errors.push(error.message));
  await legacyHome.route('**/data/manifest.json',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(legacyManifest)}));
  await legacyHome.route('**/api/ontology/**',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
  await legacyHome.goto(base);await legacyHome.locator('[data-concept]').first().waitFor();
  assert.ok((await legacyHome.locator('.source-note').last().innerText()).includes('养殖数据是审阅样本，场景值不等于实测值。'));
  report.checks.home_without_csv_preserves_note=true;
  assert.deepEqual(errors,[]);report.javascript_errors=errors;report.status='passed';
}catch(error){report.status='failed';report.error=error.stack||error.message;report.javascript_errors=errors;console.error(error);}
finally{await browser.close();await writeFile(path.join(root,'csv-browser-report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
if(report.status!=='passed')process.exitCode=1;

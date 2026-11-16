// Real Chromium readback of a published GIS/ontology release. No writes or tokens.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {values:args}=parseArgs({options:{
  'base-url':{type:'string',default:'http://127.0.0.1:8792/'},
  'playwright-module':{type:'string'},'executable-path':{type:'string'},
  'output-dir':{type:'string',default:path.join(root,'docs/local-server')},
}});
const base=new URL(args['base-url']);
assert.ok(base.protocol==='http:'&&['127.0.0.1','localhost'].includes(base.hostname)&&!base.username&&!base.password,'Explicit local deployment only');
const output=path.resolve(args['output-dir']);await mkdir(path.join(output,'screenshots'),{recursive:true});
const report={contract:'lzo-gis-sphere-browser-acceptance/1',checked_at:new Date().toISOString(),status:'running',browser:'real Chromium',field_acceptance:false,checks:[],screenshots:[],javascript_errors:[]};
const save=()=>writeFile(path.join(output,'gis-sphere-browser.json'),JSON.stringify(report,null,2)+'\n');
async function check(name,fn){try{const result=await fn();report.checks.push({name,status:'passed',result});await save();console.log(name+': passed');return result;}catch(error){report.checks.push({name,status:'failed',error:error.message});await save();throw error;}}
async function get(route,params={}){const url=new URL(route,base);url.search=new URLSearchParams(params);const response=await fetch(url);assert.equal(response.status,200,url.pathname);return response.json();}
async function shot(page,name){await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(output,'screenshots',name),fullPage:page.viewportSize().width<760});report.screenshots.push('screenshots/'+name);}
const status=await get('/api/v1/status');
const releases=await get('/api/v1/releases');
const releaseId=releases.release_id;assert.ok(releaseId);report.release_id=releaseId;
const pin={release_id:releaseId},manifest=await get('/api/v1/manifest',pin);
const map=await get('/api/v1/maps',pin),network=await get('/api/v1/network',pin);
await check('published map and network contracts',()=>{
  assert.equal(map.contract,'lzo-spatial-map/2');assert.equal(network.contract,'lzo-ontology-network/1');
  assert.equal(map.release_id,releaseId);assert.equal(network.release_id,releaseId);
  const count=kind=>map.features.filter(f=>f.kind===kind&&f.geometry).length;
  assert.equal(count('field'),67);assert.equal(count('pond'),5);assert.equal(count('facility'),28);assert.equal(count('camera'),39);
  assert.equal(new Set(map.features.map(f=>f.iri)).size,map.features.length);
  assert.ok(manifest.counts.instances>=180997);assert.ok(network.edges.some(e=>e.kind==='schema'));assert.ok(network.edges.some(e=>e.kind==='observed'));
  return {positioned:{field:67,pond:5,facility:28,camera:39},map_objects:map.features.length,display_faces:map.display_features.length,unlocated:map.unlocated.length,network_nodes:network.nodes.length,network_edges:network.edges.length};
});
const {chromium}=await import(pathToFileURL(path.resolve(args['playwright-module']||path.join(root,'frontend/node_modules/@playwright/test/index.mjs'))).href);
let browser;
try{
  browser=await chromium.launch({headless:true,...(args['executable-path']?{executablePath:args['executable-path']}:{})});
  const page=await browser.newPage({viewport:{width:1540,height:1040},deviceScaleFactor:1});page.setDefaultTimeout(30000);
  page.on('pageerror',error=>report.javascript_errors.push(error.message));
  const route=view=>new URL('/ontology/?release_id='+releaseId+'#view='+view,base).href;
  await check('flat map main entry and object navigation',async()=>{
    await page.goto(route('map'));await page.locator('.spatial-canvas').waitFor();
    assert.equal(await page.locator('.spatial-canvas').count(),1);
    assert.equal(await page.locator('.spatial-feature.camera').count(),39);
    assert.equal(await page.locator('.spatial-feature.facility').count(),28);
    const polygons=await page.locator('.spatial-feature[d$="Z"]').count();assert.equal(polygons,map.display_features.length);
    const pointAndLineCount=map.features.filter(f=>['Point','LineString','MultiLineString'].includes(f.geometry?.type)).length;
    assert.equal(await page.locator('.spatial-feature').count(),map.display_features.length+pointAndLineCount);
    const before=await page.locator('.spatial-canvas').getAttribute('viewBox');
    await page.getByRole('button',{name:'放大地图',exact:true}).click();
    assert.notEqual(await page.locator('.spatial-canvas').getAttribute('viewBox'),before);
    await page.getByRole('button',{name:'显示全部有效对象',exact:true}).click();
    await shot(page,'gis-flat-map.png');
    await page.locator('.spatial-feature.camera').first().focus();await page.keyboard.press('Enter');
    await page.locator('[data-open-object]').waitFor();const iri=await page.locator('[data-open-object]').getAttribute('data-open-object');
    await page.locator('[data-open-object]').click();await page.locator('#object-panel').waitFor();
    assert.ok(decodeURIComponent(page.url()).includes(iri));
    await page.getByRole('link',{name:'在地图中查看 →',exact:true}).click();
    await page.locator('[data-open-object]').waitFor();assert.equal(await page.locator('[data-open-object]').getAttribute('data-open-object'),iri);
    const parcel=map.features.find(f=>f.kind==='field');
    await page.goto(route('map')+'&object='+encodeURIComponent(parcel.iri));await page.locator('[data-open-object]').waitFor();
    assert.equal(await page.locator('[data-open-object]').getAttribute('data-open-object'),parcel.iri);
    assert.match(await page.locator('.spatial-detail').innerText(),/周长/);
    await shot(page,'gis-parcel-detail.png');
    return {one_flat_view:true,polygon_faces:polygons,camera_iri:iri,instance_map_round_trip:true,parcel_measurements_visible:true};
  });
  await check('unlocated objects and historical map remain accessible',async()=>{
    await page.goto(route('map'));await page.locator('[data-unlocated-only]').check();
    assert.ok(await page.locator('.spatial-object-row').count()>0);
    await page.locator('[data-spatial="legacy"]').click();await page.locator('#map-layer').waitFor();
    const oldLayerCount=await page.locator('#map-layer option').count();assert.equal(oldLayerCount,6);
    return {unlocated:map.unlocated.length,old_layers:oldLayerCount};
  });
  await check('sphere actual drag zoom and bounded relationship drilldown',async()=>{
    await page.goto(route('network'));const canvas=page.locator('.sphere-canvas');await canvas.waitFor();
    await page.waitForFunction(()=>document.querySelector('.sphere-canvas')?.width>0);
    const firstImage=await canvas.evaluate(el=>el.toDataURL()),bounds=await canvas.boundingBox(),url=page.url();
    await page.mouse.move(bounds.x+bounds.width*.45,bounds.y+bounds.height*.48);await page.mouse.down();
    await page.mouse.move(bounds.x+bounds.width*.7,bounds.y+bounds.height*.63,{steps:18});await page.mouse.up();
    await page.waitForTimeout(120);assert.equal(page.url(),url);assert.notEqual(await canvas.evaluate(el=>el.toDataURL()),firstImage);
    const dragged=await canvas.evaluate(el=>el.toDataURL());await page.mouse.wheel(0,-180);await page.waitForTimeout(120);
    assert.notEqual(await canvas.evaluate(el=>el.toDataURL()),dragged);
    await shot(page,'ontology-sphere.png');
    const edge=network.edges.find(e=>e.kind==='observed'&&e.count>12),node=network.nodes.find(n=>n.iri===edge.source);assert.ok(node);
    await page.locator('[data-filter="kind"]').selectOption('observed');
    await page.locator('[data-filter="query"]').fill(node.label);
    const button=page.locator('[data-node]').filter({has:page.locator('span',{hasText:node.label})}).first();
    await button.click();await page.locator('[data-filter="query"]').fill('');
    const edges=page.locator('.sphere-neighbors [data-edge]');assert.ok(await edges.count()>0);
    await edges.first().click();await page.locator('[data-open-edge]').click();
    await page.locator('.network-instance-pair').first().waitFor();assert.ok(await page.locator('.network-instance-pair').count()<=12);
    const firstLink=page.locator('.network-instance-pair a').first(),href=await firstLink.getAttribute('href');
    await firstLink.click();await page.locator('#object-panel').waitFor();assert.ok(page.url().endsWith(href));
    return {mouse_rotation:true,wheel_zoom:true,drag_did_not_navigate:true,relationship_to_instance:true};
  });
  await check('mobile layouts and release pinning',async()=>{
    await page.setViewportSize({width:390,height:844});
    for(const view of ['map','network']){
      await page.goto(route(view));await page.locator(view==='map'?'.spatial-canvas':'.sphere-canvas').waitFor();
      await page.waitForFunction(()=>document.querySelector('#sidebar').getBoundingClientRect().right<=0);
      const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(size.scroll<=size.width+1,view+' horizontal overflow');
      await page.locator('#open-tree').click();await page.locator('#close-tree').click();
      await page.waitForFunction(()=>document.querySelector('#sidebar').getBoundingClientRect().right<=0);
      await shot(page,'gis-sphere-mobile-'+view+'.png');
    }
    const old=releases.items.find(r=>r.release_id!==releaseId&&r.status==='published');assert.ok(old);
    const oldManifest=await get('/api/v1/manifest',{release_id:old.release_id});assert.ok(oldManifest.counts.instances>=180997);
    assert.equal((await get('/api/v1/maps',{release_id:old.release_id})).schema_version,'farm-local-map/1');
    return {mobile_width:390,current_release:releaseId,old_release:old.release_id};
  });
  assert.deepEqual(report.javascript_errors,[]);report.status='passed';
}catch(error){report.status='failed';report.error=error.message;throw error;}
finally{report.completed_at=new Date().toISOString();await save();if(browser)await browser.close();}

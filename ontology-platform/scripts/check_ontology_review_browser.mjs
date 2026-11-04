// Actual browser acceptance; requires the local live review server and frontend Playwright dependency.
import {chromium} from '../frontend/node_modules/@playwright/test/index.mjs';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {gunzipSync} from 'node:zlib';
import {createCatalog} from '../docs/fish/ontology-review/model.mjs';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
const {values:options}=parseArgs({options:{'base-url':{type:'string',default:'http://127.0.0.1:8792/'},'executable-path':{type:'string'}}});
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../docs/fish/ontology-review');
const endpoint=new URL(options['base-url']);
if(endpoint.protocol!=='http:'||endpoint.hostname!=='127.0.0.1'||!endpoint.port||endpoint.username||endpoint.password||endpoint.search||endpoint.hash)throw Error('Explicit local review server URL required');
const base=endpoint.href.endsWith('/')?endpoint.href:endpoint.href+'/';
const manifest=JSON.parse(await readFile(path.join(root,'data/manifest.json'),'utf8')),catalog=createCatalog(manifest);
const shard=async table=>{const c=manifest.concepts.find(x=>x.table===table);return {concept:c,data:JSON.parse(gunzipSync(await readFile(path.join(root,'data',c.instances_path))).toString())};};
await mkdir(path.join(root,'screenshots'),{recursive:true});
const browser=await chromium.launch({headless:true,...(options['executable-path']?{executablePath:options['executable-path']}:{})});
const report={contract:'fish-ontology-browser-readback/1',checked_at:new Date().toISOString(),source:'actual 4-graph manifest and 84 published gzip shards',database_writes:false,checks:{},screenshots:[]};
const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1500,height:1050}});
 page.on('pageerror',e=>errors.push(e.message));
 const shot=async(name,p=page)=>{await p.screenshot({path:path.join(root,'screenshots',name),fullPage:false});report.screenshots.push('screenshots/'+name);};
 const noOverflow=async(p=page)=>{const sizes=await p.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));if(sizes.scroll>sizes.width+1)throw Error('horizontal overflow '+JSON.stringify(sizes));return sizes;};
 await page.goto(base);await page.locator('[data-concept]').first().waitFor();
 await shot('desktop-overview.png');await noOverflow();report.checks.boot=true;
 const ponds=await shard('ponds');
 for(const c of catalog.path(ponds.concept.iri).filter(c=>!catalog.roots.some(r=>r.iri===c.iri))){
   await page.locator('[data-concept]').filter({has:page.locator('h3',{hasText:c.label})}).first().click();
   await page.locator('h1').filter({hasText:c.label}).waitFor();
 }
 await page.locator('[data-instance]').first().waitFor();report.checks.hierarchy_to_instances=true;
 await page.locator('[data-instance]').first().click();await page.locator('.object-header').waitFor();
 const origin=page.url();await page.locator('[data-tab=relations]').click();await page.locator('[data-relation]').first().waitFor();
 await page.locator('[data-relation]').first().click();await page.locator('.object-header').waitFor();
 if(page.url()===origin)throw Error('relation did not navigate');
 await page.locator('#go-back').click();await page.locator('[data-tab=relations].active').waitFor();report.checks.relation_and_back=true;
 await page.locator('[data-view=map]').click();await page.locator('#source-map .map-feature').first().waitFor();
 await shot('desktop-map.png');
 const maps=JSON.parse(await readFile(path.join(root,'data/map-features.json'),'utf8'));
 report.checks.map_layers=[];
 for(const layer of maps.layers){await page.selectOption('#map-layer',layer.id);await page.waitForFunction(id=>document.querySelector('#source-map')?.dataset.layer===id,layer.id);const count=await page.locator('#source-map .map-feature').count();if(count!==layer.features.length)throw Error('map count '+layer.id+' '+count);await noOverflow();report.checks.map_layers.push({id:layer.id,features:count});}
 const mapPonds=await shard('map_pond'),mapRow=mapPonds.data.instances.find(r=>r.id==='DRAW-pdf-01-QING15')||mapPonds.data.instances.find(r=>r.outgoing.some(e=>e.field==='hasDrawingEvidence'||e.iri.endsWith('hasDrawingEvidence')));
 if(!mapRow)throw Error('drawing pond fixture absent');
 const layer=maps.layers.find(l=>l.features.some(f=>f.properties?.object_iri===mapRow.iri));
 await page.selectOption('#map-layer',layer.id);await page.waitForFunction(id=>document.querySelector('#source-map')?.dataset.layer===id,layer.id);
 const featureIndex=layer.features.findIndex(f=>f.properties?.object_iri===mapRow.iri);
 await page.locator(`.map-feature[data-feature="${featureIndex}"]`).click();await page.locator('.object-header h1').waitFor();
 report.checks.map_to_real_pond=mapRow.iri;await noOverflow();
 await page.locator('[data-tab=demo]').click();await page.locator('[data-demo]').first().waitFor();
 if(!(await page.locator('#object-panel').textContent()).includes('原始塘口标识'))throw Error('original pond missing');
 await shot('desktop-demo.png');
 await page.locator('[data-demo]').first().click();await page.locator('.object-header').waitFor();report.checks.demo_to_source=true;
 await page.locator('#go-back').click();await page.locator('[data-tab=demo].active').waitFor();
 const nextDemo=page.locator('[data-action=demo-page]').last();if(await nextDemo.count()){await nextDemo.click();await page.waitForFunction(()=>new URLSearchParams(location.hash.slice(1)).get('demoPage')==='2');report.checks.demo_pagination=true;}
 await page.locator('[data-tab=relations]').click();
 const bridge=mapRow.outgoing.find(e=>(e.field||e.iri).endsWith('hasDrawingEvidence'));
 await page.locator(`[data-relation="${bridge.target_iri}"]`).click();await page.locator('.object-header').waitFor();
 const profileConcept=catalog.byId.get(bridge.target_class_iri),profileData=JSON.parse(gunzipSync(await readFile(path.join(root,'data',profileConcept.instances_path))).toString());
 const profile=profileData.instances.find(r=>r.iri===bridge.target_iri),measurementClass=profile.outgoing.find(e=>/measurement/i.test(e.target_class_iri))?.target_class_iri, measurementData=JSON.parse(gunzipSync(await readFile(path.join(root,'data',catalog.byId.get(measurementClass).instances_path))).toString()), measurement=profile.outgoing.find(e=>/measurement/i.test(e.target_class_iri)&&measurementData.instances.find(r=>r.iri===e.target_iri)?.properties.some(p=>p.field==='reviewStatus'&&p.value==='computed_paper_geometry_not_ground_survey'));
 if(!measurement)throw Error('measurement relation absent');
 await page.locator('[data-tab=relations]').click();
 for(let i=0;i<20&&await page.locator(`[data-relation="${measurement.target_iri}"]`).count()===0;i++){await page.locator('[data-action=relation-page][data-direction=outgoing]').last().click();}
 await page.locator(`[data-relation="${measurement.target_iri}"]`).click();await page.locator('.object-header').waitFor();
 await shot('desktop-measurement.png');report.checks.map_to_drawing_to_measurement={map:mapRow.iri,profile:profile.iri,measurement:measurement.target_iri};
 if(await page.locator('.property-unit').count()===0)throw Error('measurement units absent');report.checks.measurement_units=true;
 await page.goto(base+'#view=instance&iri='+encodeURIComponent(mapRow.iri)+'&class='+encodeURIComponent(mapRow.class_iri)+'&tab=rdf');
 await page.getByRole('button',{name:'更多出向陈述'}).waitFor({timeout:60000});
 const more=page.getByRole('button',{name:'更多出向陈述'});if(!await more.isDisabled()){await more.click();await page.waitForFunction(()=>Number(new URLSearchParams(location.hash.slice(1)).get('rdfOut'))>0);await page.getByRole('button',{name:'更多出向陈述'}).waitFor({timeout:60000});report.checks.live_offset_pagination=true;}else report.checks.live_offset_pagination='no next page';
 report.checks.live_rdf=(await page.locator('#object-panel').textContent()).includes('Fuseki');
 const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});mobile.on('pageerror',e=>errors.push(e.message));
 await mobile.goto(base);await mobile.locator('[data-concept]').first().waitFor();await noOverflow(mobile);await shot('mobile-overview.png',mobile);
 await mobile.goto(base+'#view=instance&iri='+encodeURIComponent(mapRow.iri)+'&class='+encodeURIComponent(mapRow.class_iri)+'&tab=demo');await mobile.locator('[data-demo]').first().waitFor();await noOverflow(mobile);await shot('mobile-object.png',mobile);
 await mobile.locator('[data-view=map]').click();await mobile.locator('#source-map').waitFor();await noOverflow(mobile);await shot('mobile-map.png',mobile);report.checks.mobile_no_overflow=true;
 const offline=await browser.newPage({viewport:{width:1000,height:800}});offline.on('pageerror',e=>errors.push(e.message));await offline.route('**/api/**',route=>route.fulfill({status:503,contentType:'application/json',body:'{}'}));
 await offline.goto(base+'#view=instance&iri='+encodeURIComponent(mapRow.iri)+'&class='+encodeURIComponent(mapRow.class_iri)+'&tab=rdf');await offline.locator('#object-panel .source-note').waitFor();
 if(!(await offline.locator('#object-panel').textContent()).includes('未连接实时 SPARQL'))throw Error('offline mode mislabeled');report.checks.offline_verified_snapshot=true;
 if(errors.length)throw Error(errors.join('\n'));report.javascript_errors=errors;report.status='passed';
}catch(error){report.status='failed';report.error=error.message;report.javascript_errors=errors;console.error(error);}
finally{await browser.close();await writeFile(path.join(root,'browser-report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));}
if(report.status!=='passed')process.exitCode=1;

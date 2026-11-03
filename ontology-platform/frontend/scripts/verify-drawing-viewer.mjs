import {chromium} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';

// Uses a new headless profile; never connects to the user's browser or account.
const browser=await chromium.launch({headless:true,...(process.env.DRAWING_BROWSER_EXECUTABLE?{executablePath:process.env.DRAWING_BROWSER_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(process.env.DRAWING_VIEWER_URL||'http://127.0.0.1:8791');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('空间表示'));
 assert.equal(await page.locator('#sheet option').count(),5);
 const counts=[];
 for(const id of ['pdf-01','pdf-02','pdf-03','pdf-04','pdf-05']){
  await page.locator('#sheet').selectOption(id);
  await page.waitForFunction(()=>document.getElementById('status').textContent.includes('空间表示'));
  const features=await page.locator('.feature').count();assert.ok(features>0);
  counts.push({drawing_id:id,features});
  // A source point has a guaranteed clickable centre; polygon centres may lie outside.
  await page.locator('path.feature').first().dispatchEvent('click');
  await page.waitForFunction(()=>document.getElementById('details').textContent.includes('entity_id'));
  await page.waitForFunction(()=>document.getElementById('metrics-summary').textContent.includes('纸面周长'));
  assert.ok(await page.locator('#measurements button').count()>0);
  counts[counts.length-1].profile_metrics_verified=true;
  const next=page.getByRole('button',{name:'下一页',exact:true});
  if(await next.isEnabled()){await next.click();await page.waitForFunction(()=>document.getElementById('evidence-list').textContent.includes('第 2/'));}
 }
 await page.locator('#sheet').selectOption('pdf-03');
 await page.waitForFunction(()=>document.getElementById('status').textContent.includes('空间表示'));
 await page.locator('path.feature').first().dispatchEvent('click');
 await page.waitForFunction(()=>document.getElementById('metrics-summary').textContent.includes('参考长度推算周长'));
 await page.locator('aside').evaluate(el=>el.scrollTop=0);
 await mkdir('../docs/gis',{recursive:true});
 await page.screenshot({path:'../docs/gis/drawing-viewer.png',fullPage:true});
 assert.deepEqual(errors,[]);
 await writeFile('../docs/gis/viewer-verification.json',JSON.stringify({status:'passed',source:'offline SQLite mirror; not production auth acceptance',drawings:counts,metric_profile_queries:'verified all five drawings',browser_errors:errors},null,2)+'\n');
 console.log(JSON.stringify({status:'passed',drawings:counts}));
}catch(error){await page.screenshot({path:'../.runtime/drawing-viewer-failure.png',fullPage:true});console.error({status:await page.locator('#status').textContent(),errors});throw error;}
finally{await browser.close();}

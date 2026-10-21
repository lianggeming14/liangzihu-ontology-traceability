/* Capture exact source excerpts in isolated Chrome; no application or network access. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const playwrightPath = process.env.PLAYWRIGHT_MODULE || 'C:/Users/robot/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
const { chromium } = require(playwrightPath);
const root = path.resolve(__dirname, '../..');
const folder = path.join(root, '交付文档', '数据库结构源码图解_20261021');
const hash = b => crypto.createHash('sha256').update(b).digest('hex');
(async () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'sources.json'), 'utf8'));
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', args:['--disable-background-networking']});
  try {
    const context = await browser.newContext({viewport:{width:1460,height:1100},deviceScaleFactor:1.5});
    await context.route(/^https?:/, route => route.abort());
    const page = await context.newPage();
    const checks = [];
    for (const item of manifest.items) {
      if(hash(fs.readFileSync(path.join(root,item.path)))!==item.source_sha256) throw Error('Source changed: '+item.path);
      await page.goto(pathToFileURL(path.join(folder,'captures',item.id+'.html')).href);
      await page.evaluate(()=>document.fonts.ready);
      const displayed=await page.locator('.code').allTextContents();
      if(JSON.stringify(displayed)!==JSON.stringify(item.lines)) throw Error('Rendered text mismatch: '+item.id);
      const numbers=await page.locator('.ln').allTextContents();
      if(numbers.some((n,i)=>Number(n)!==item.start+i)) throw Error('Line number mismatch');
      const overflow=await page.locator('.capture').evaluate(el=>({outside:el.scrollWidth>el.clientWidth+2,code:[...el.querySelectorAll('.code')].some(x=>x.scrollWidth>x.clientWidth+2)}));
      if(overflow.outside||overflow.code) throw Error('Horizontal clipping: '+item.id);
      const target=path.join(folder,item.screenshot);
      await page.locator('.capture').screenshot({path:target,animations:'disabled'});
      const bounds=await page.locator('.capture').boundingBox();
      checks.push({id:item.id,status:'passed',source_lines_exact:true,line_numbers_exact:true,no_horizontal_clipping:true,width:bounds.width,height:bounds.height,screenshot_sha256:hash(fs.readFileSync(target))});
    }
    await page.goto(pathToFileURL(path.join(folder,'index.html')).href);
    await page.locator('img').evaluateAll(images=>images.forEach(img=>img.loading='eager'));
    await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
    if(await page.locator('.section').count()!==manifest.items.length) throw Error('Report count mismatch');
    const fullOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
    if(fullOverflow)throw Error('Report overflow');
    await page.screenshot({path:path.join(folder,'screenshots','00-report-overview.png'),fullPage:false});
    const result={date:'2026-10-21',browser:await browser.version(),method:'verbatim source extraction + real browser screenshots',passed:checks.length,failed:0,checks,report_images_loaded:true,report_no_horizontal_overflow:true,application_changes:false,backend_tests:'not_run_documentation_only',postgresql_validation:'not_run',visual_review:'pending'};
    fs.writeFileSync(path.join(folder,'verification.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify({captured:checks.length,result:path.join(folder,'verification.json')}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});

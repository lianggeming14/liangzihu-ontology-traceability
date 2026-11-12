const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const short=value=>String(value??'').split(/[:/#]/).filter(Boolean).slice(-2).join(' / ');
const exportLabel='下载完整公开类型数据';
const statuses={queued:'等待导入',running:'正在处理',failed:'导入失败',succeeded:'已发布'};
let selectedRelease=null,activeRelease=null,viewEpoch=0,nextPage=null,refreshNumber=0;
let historyActive=null,releaseHistory=[];
const operations=new Map();
async function request(path,options){const response=await fetch(path,{credentials:'same-origin',...options});if(!response.ok){let value={};try{value=await response.json();}catch{}throw Error(value.error?.message||'服务请求失败');}return response;}
async function json(path,options){return(await request(path,options)).json();}
function query(path,params={},version=selectedRelease){return path+'?'+new URLSearchParams({release_id:version,...params});}
function cancel(kind){operations.get(kind)?.controller.abort();operations.delete(kind);}
function begin(kind){cancel(kind);const ticket={kind,version:selectedRelease,epoch:viewEpoch,controller:new AbortController()};operations.set(kind,ticket);return ticket;}
function owns(ticket){return ticket.version===selectedRelease&&ticket.epoch===viewEpoch&&operations.get(ticket.kind)===ticket&&!ticket.controller.signal.aborted;}
function checked(value,ticket){if(value.release_id!==ticket.version)throw Error('响应版本不匹配，请重新选择版本。');return value;}
function updateVersionNotice(){
  const different=activeRelease&&selectedRelease&&activeRelease!==selectedRelease;
  $('new-release-message').textContent=different?'当前已发布新版本 '+activeRelease.slice(0,8)+'；此面板仍固定浏览 '+selectedRelease.slice(0,8)+'，可选择切换。':'浏览内容固定在所选版本；发布更新不会自动替换此面板。';
  $('use-active-release').hidden=!different;
}
function versionOptions(){
  const rows=[...releaseHistory];
  if(selectedRelease&&!rows.some(row=>row.release_id===selectedRelease))rows.push({release_id:selectedRelease});
  $('release-select').innerHTML=rows.length?rows.map(row=>`<option value="${esc(row.release_id)}">${row.release_id===activeRelease?'当前发布 · ':''}${row.legacy_snapshot?'审阅快照 · ':''}${esc(row.release_id)}</option>`).join(''):'<option value="">尚无发布版本</option>';
  $('release-select').value=selectedRelease||'';
}
async function selectRelease(version){
  if(!version)return;
  for(const ticket of operations.values())ticket.controller.abort();
  operations.clear();selectedRelease=version;viewEpoch++;nextPage=null;
  $('release-select').value=version;
  $('class-select').innerHTML='<option value="">正在读取所选版本…</option>';$('class-select').value='';
  $('instances').textContent='选择类型后查看此版本实例。';$('resource').textContent='点击此版本的实例查看属性和双向关系。';
  $('next-button').hidden=true;$('export-button').disabled=false;$('export-button').textContent=exportLabel;
  $('browse-version').textContent='固定版本 '+version.slice(0,8);
  for(const anchor of document.querySelectorAll('[data-ontology-link]'))anchor.href='/ontology/?release_id='+encodeURIComponent(version);
  const url=new URL(location.href);url.searchParams.set('release_id',version);history.replaceState(null,'',url);updateVersionNotice();
  const ticket=begin('manifest');
  try{
    const manifest=await json(query('/api/v1/manifest',{},ticket.version),{signal:ticket.controller.signal});
    if(!owns(ticket))return;checked(manifest,ticket);
    $('class-select').innerHTML='<option value="">请选择本体类型</option>'+manifest.concepts.map(row=>`<option value="${esc(row.iri)}">${esc(row.label)}${row.total_instance_count?' · '+row.total_instance_count:''}</option>`).join('');$('class-select').value='';
  }catch(error){if(owns(ticket))$('resource').textContent=error.message;}
}
async function loadHistory(number){
  let offset=0,rows=[];
  do{const page=await json('/api/v1/releases'+(offset?'?offset='+offset:''));if(number!==refreshNumber)return false;rows.push(...page.items);offset=page.next_offset;}while(offset!==null&&offset!==undefined);
  releaseHistory=[...new Map(rows.map(row=>[row.release_id,row])).values()];historyActive=activeRelease;versionOptions();return true;
}
async function refresh(){
  const number=++refreshNumber;
  try{
    const state=await json('/api/v1/status');if(number!==refreshNumber)return;activeRelease=state.release_id;
    $('connection').textContent='本机已连接';$('service-state').textContent=state.status==='ready'?'运行中':'等待初始发布';
    $('release-label').textContent=state.active_release?.legacy_snapshot?'现有审阅快照':state.active_release?.batch_id?.slice(0,12)||'已验证版本';
    $('release-id').textContent=activeRelease||'请先导入或登记初始版本';$('instance-count').textContent=Number(state.active_release?.counts?.instances||0).toLocaleString('zh-CN');
    $('data-nature').textContent=state.active_release?.data_nature==='mixed_review_data'?'含来源导入与演示 · 按实例保留性质':'来源导入 · 尚未现场确认';
    $('jobs').innerHTML=state.jobs.length?state.jobs.map(job=>`<tr><td>${esc(job.job_id.slice(0,8))}</td><td>${esc(statuses[job.status]||job.status)}</td><td>${esc(job.stage||'queued')}</td><td>${esc(job.error?.message||job.result?.release_id?.slice(0,8)||'—')}</td></tr>`).join(''):'<tr><td colspan="4">暂无导入任务</td></tr>';
    updateVersionNotice();if(historyActive!==activeRelease||!releaseHistory.length){if(!await loadHistory(number))return;}if(number!==refreshNumber)return;
    if(!selectedRelease){const requested=new URLSearchParams(location.search).get('release_id');if(requested||activeRelease)await selectRelease(requested||activeRelease);}updateVersionNotice();
  }catch(error){if(number===refreshNumber){$('connection').textContent='连接暂不可用';$('service-state').textContent='请检查服务';}}
}
$('release-select').addEventListener('change',()=>selectRelease($('release-select').value));
$('use-active-release').addEventListener('click',()=>selectRelease(activeRelease));
$('upload-form').addEventListener('submit',async event=>{
  event.preventDefault();const file=$('upload-file').files[0],token=$('token').value;if(!file)return;
  const button=event.target.querySelector('button');button.disabled=true;$('upload-message').textContent='正在上传并登记…';
  try{const job=await json('/api/v1/batches?filename='+encodeURIComponent(file.name),{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/octet-stream'},body:file});$('upload-message').textContent='任务已登记：'+job.job_id+'。验证发布后可从版本列表切换，当前浏览版本保持固定。';$('token').value='';await refresh();}
  catch(error){$('upload-message').textContent=error.message;}finally{button.disabled=false;}
});
async function instances(cursor=null,concept=$('class-select').value,version=selectedRelease){
  if(!selectedRelease||!concept||version!==selectedRelease)return;
  cancel('resource');$('resource').textContent='点击此版本的实例查看属性和双向关系。';$('instances').textContent='正在读取实例…';$('next-button').hidden=true;nextPage=null;
  const ticket=begin('instances');
  try{
    const value=await json(query('/api/v1/instances',{class:concept,limit:30,...(cursor?{cursor}:{})},ticket.version),{signal:ticket.controller.signal});
    if(!owns(ticket))return;checked(value,ticket);
    $('instances').innerHTML=value.items.length?value.items.map(row=>`<button data-iri="${esc(row.iri)}" data-release-id="${esc(ticket.version)}">${esc(row.label)}<small>${esc(short(row.iri))}</small></button>`).join(''):'此类型暂无实例。';
    nextPage=value.next_cursor?{cursor:value.next_cursor,concept,version:ticket.version}:null;$('next-button').hidden=!nextPage;
  }catch(error){if(owns(ticket))$('instances').textContent=error.message;}
}
$('query-button').addEventListener('click',()=>instances());$('class-select').addEventListener('change',()=>instances());
$('next-button').addEventListener('click',()=>nextPage&&instances(nextPage.cursor,nextPage.concept,nextPage.version));
async function resource(iri,params={},version=selectedRelease){
  if(!selectedRelease||version!==selectedRelease)return;
  const ticket=begin('resource');$('resource').textContent='正在读取属性与关系…';
  try{
    const value=await json(query('/api/v1/resource',{iri,limit:100,...params},ticket.version),{signal:ticket.controller.signal});
    if(!owns(ticket))return;checked(value,ticket);
    const link=(target,label)=>`<a href="?release_id=${encodeURIComponent(ticket.version)}#browse" data-iri="${esc(target)}" data-release-id="${esc(ticket.version)}">${esc(label)} ↗</a>`;
    $('resource').innerHTML=`<h3>${esc(short(iri))}</h3><p>${esc(iri)}</p><h4>属性与正向关系</h4><dl>${value.outgoing.map(row=>`<dt>${esc(short(row.predicate))}</dt><dd>${row.object.type==='uri'?link(row.object.value,short(row.object.value)):esc(row.object.value)}</dd>`).join('')}</dl><h4>反向关系</h4>${value.incoming.map(row=>`<p>${esc(short(row.predicate))}${link(row.subject,short(row.subject))}</p>`).join('')||'<p>没有反向关系</p>'}${value.next_cursor?'<button id="resource-out-next" class="secondary">更多属性 / 正向关系</button>':''}${value.next_incoming_cursor?'<button id="resource-in-next" class="secondary">更多反向关系</button>':''}<p class="hint">来源性质：${esc(value.provenance.data_nature??'本属性页未提供')} · 版本 ${esc(ticket.version.slice(0,8))}</p>`;
    if(value.next_cursor)$('resource-out-next').addEventListener('click',()=>resource(iri,{cursor:value.next_cursor,incoming_offset:value.incoming_offset},ticket.version));
    if(value.next_incoming_cursor)$('resource-in-next').addEventListener('click',()=>resource(iri,{outgoing_offset:value.outgoing_offset,incoming_cursor:value.next_incoming_cursor},ticket.version));
  }catch(error){if(owns(ticket))$('resource').textContent=error.message;}
}
document.addEventListener('click',event=>{const target=event.target.closest('[data-iri]');if(target){event.preventDefault();return resource(target.dataset.iri,{},target.dataset.releaseId);}});
$('export-button').addEventListener('click',async()=>{
  const concept=$('class-select').value;if(!selectedRelease||!concept){$('resource').textContent='请先选择本体类型。';return;}
  const button=$('export-button'),format=$('export-format').value,ticket=begin('export');button.disabled=true;
  try{
    let cursor=null,pages=[],items=[],total=0;
    do{
      const response=await request(query('/api/v1/export',{class:concept,format,limit:1000,...(cursor?{cursor}:{})},ticket.version),{signal:ticket.controller.signal});
      if(!owns(ticket))return;const responseVersion=response.headers.get('X-Release-ID');if(responseVersion&&responseVersion!==ticket.version)throw Error('导出响应版本不匹配。');
      if(format==='json'){const value=await response.json();if(!owns(ticket))return;checked(value,ticket);items.push(...value.items);cursor=value.next_cursor;}
      else{let text=await response.text();if(!owns(ticket))return;if(format==='csv'&&pages.length)text=text.slice(text.indexOf('\n')+1);pages.push(text);cursor=response.headers.get('X-Next-Cursor');}
      total++;button.textContent='正在导出第 '+total+' 页…';if((format==='json'?JSON.stringify(items).length:pages.reduce((sum,row)=>sum+row.length,0))>128*1024*1024)throw Error('导出超过浏览器 128 MiB 限额，请按更具体类型导出。');
    }while(cursor);
    if(!owns(ticket))return;
    const content=format==='json'?JSON.stringify({release_id:ticket.version,scope:'public-normalized-triples',raw_payload_public:false,items},null,2):pages.join('');
    const blob=new Blob([content],{type:format==='json'?'application/json':format==='csv'?'text/csv;charset=utf-8':'text/turtle;charset=utf-8'});const anchor=document.createElement('a');anchor.href=URL.createObjectURL(blob);anchor.download='ontology-'+ticket.version.slice(0,8)+'.'+(format==='rdf'?'ttl':format);anchor.click();setTimeout(()=>URL.revokeObjectURL(anchor.href),1000);
  }catch(error){if(owns(ticket))$('resource').textContent=error.message;}finally{if(owns(ticket)){button.disabled=false;button.textContent=exportLabel;}}
});
await refresh();setInterval(refresh,4000);

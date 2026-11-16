import {createCatalog,pageInstances,routeHash,readRoute,spatialObjectRoute,relationTarget,demoTarget,propertyUnit,decodeSnapshot,createSnapshotLoader,relationCount,formatValue,natureLabel,instanceNature,instanceAdoption} from './model.mjs';
import {mountSpatialMap} from './spatial-map.mjs';
import {mountOntologySphere,createViewSession} from './ontology-sphere.mjs';

const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const number=value=>Number(value||0).toLocaleString('zh-CN');
const href=route=>esc(routeHash(route));
const icons=[
  '<path d="M3 9 12 4l9 5-9 5-9-5Zm0 5 9 5 9-5M3 19l9 5 9-5" transform="translate(0 -2)"/>',
  '<path d="M4 17V8l8-4 8 4v9l-8 4-8-4Zm0-9 8 5 8-5m-8 5v8"/>',
  '<path d="M3 17h4l3-10 4 14 3-10h4M3 4v17h18"/>',
  '<path d="M5 4h14v17H5V4Zm4 5h6m-6 4h6m-6 4h3M9 2v4m6-4v4"/>',
  '<path d="m3 5 6-2 6 2 6-2v17l-6 2-6-2-6 2V5Zm6-2v17m6-15v17"/>',
];
const icon=index=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[index%icons.length]}</svg>`;
const badge=(text,tone='')=>`<span class="badge ${tone}">${esc(text)}</span>`;
let manifest,catalog,renderId=0,currentRoute={view:'home'},currentRows=[],currentClass=null,mapData=null;
let legacyMapData=null,networkData=null,mountedView=null;
const releaseId=document.querySelector('meta[name="local-release-id"]')?.content||'';
let live={mode:'snapshot',available:false},liveChecked=false;
const fragments=new Map(),expanded=new Set(),routeHistory=[location.hash||'#view=home'];
const snapshots=createSnapshotLoader(path=>json('data/'+path));

async function json(path){
  if(releaseId&&path.startsWith('/api/v1/')){const pinned=new URL(path,location.origin);pinned.searchParams.set('release_id',releaseId);path=pinned.pathname+pinned.search;}
  const response=await fetch(path,{credentials:'same-origin'});
  if(!response.ok) throw new Error(`快照文件未就绪（${response.status}）`);
  const data=await decodeSnapshot(response);
  if(releaseId&&data.release_id&&data.release_id!==releaseId)throw Error('响应发布版本与当前页面不一致，请重新打开页面');
  return data;
}
async function instances(concept){
  if(!concept?.instances_path) return [];
  if(!fragments.has(concept.iri)){
    const promise=json('data/'+concept.instances_path).then(value=>{
      if(value.contract!=='fish-rdf-review/1'||value.class_iri!==concept.iri||!Array.isArray(value.instances)) throw new Error('实例分片与本体类型不一致');
      return value.instances;
    });
    fragments.set(concept.iri,promise);
    promise.catch(()=>fragments.delete(concept.iri));
  }
  return fragments.get(concept.iri);
}
function go(route){const hash=routeHash(route);if(location.hash===hash) render();else location.hash=hash;}
function empty(title,message){return `<section class="empty-state"><h1>${esc(title)}</h1><p>${esc(message)}</p><a href="#view=home">返回本体总览 →</a></section>`;}
function loading(){return '<section class="empty-state"><span class="loader"></span><h1>正在读取对象</h1><p>按本体类型打开对应的 RDF 回读快照。</p></section>';}
function closeTree(){$('sidebar').classList.remove('open');$('tree-shade').hidden=true;}

function breadcrumbs(concept,instance){
  const path=concept?catalog.path(concept.iri):[];
  $('breadcrumbs').innerHTML=`<a href="#view=home">本体总览</a>`+path.map(item=>`<span class="breadcrumb-separator">/</span><a href="${href({view:'class',iri:item.iri})}">${esc(item.label)}</a>`).join('')+(instance?`<span class="breadcrumb-separator">/</span><strong>${esc(instance.label)}</strong>`:'');
  if(currentRoute.view==='map'||currentRoute.view==='feature') $('breadcrumbs').innerHTML='<a href="#view=home">本体总览</a><span class="breadcrumb-separator">/</span><strong>空间地图</strong>';
  if(currentRoute.view==='network') $('breadcrumbs').innerHTML='<a href="#view=home">本体总览</a><span class="breadcrumb-separator">/</span><strong>本体关系球</strong>';
  $('go-back').hidden=currentRoute.view==='home';
}
function tree(){
  const selected=currentRoute.class||currentRoute.iri;
  catalog.path(selected).forEach(item=>expanded.add(item.iri));
  const branch=item=>{
    const children=catalog.children(item.iri),open=expanded.has(item.iri);
    return `<div class="tree-branch"><div class="tree-row ${selected===item.iri?'active':''}"><button class="tree-toggle ${children.length?'':'empty'}" data-action="tree" data-iri="${esc(item.iri)}" aria-label="${open?'折叠':'展开'}${esc(item.label)}" aria-expanded="${open}">${open?'⌄':'›'}</button><a href="${href({view:'class',iri:item.iri})}">${esc(item.label)}</a><span class="tree-counter">${number(item.total_instance_count??item.instance_count)}</span></div>${children.length&&open?`<div class="tree-children">${children.map(branch).join('')}</div>`:''}</div>`;
  };
  $('concept-tree').innerHTML=catalog.top.map(branch).join('');
  document.querySelector('.tree-home').classList.toggle('active',currentRoute.view==='home');
  document.querySelectorAll('[data-view]').forEach(link=>link.classList.toggle('active',link.dataset.view===(['map','feature'].includes(currentRoute.view)?'map':currentRoute.view==='network'?'network':'ontology')));
}
function conceptCard(item,index,child=false){
  const children=catalog.children(item.iri),count=item.total_instance_count??item.instance_count;
  const summary=children.length?children.slice(0,4).map(value=>value.label).join(' · ')+(children.length>4?' …':''):'查看该类型下的对象与对应信息';
  return `<a class="concept-card" href="${href({view:'class',iri:item.iri})}" data-concept="${esc(item.iri)}"><div class="concept-card-top"><span class="concept-icon">${icon(index)}</span><span class="card-arrow">↗</span></div><h3>${esc(item.label)}</h3><p class="subtype-names">${esc(summary)}</p><div class="concept-card-bottom">${children.length?`<span><b>${children.length}</b> 子本体</span>`:''}<span><b>${number(count)}</b> 实例</span><span>${child?'继续查看':'进入本体'} →</span></div></a>`;
}
function home(){
  breadcrumbs();
  const counts=manifest.counts||{};
  const hasCsvBatches=Array.isArray(manifest.csv_batches)?manifest.csv_batches.length>0:!!manifest.csv_batches;
  const sourceIntro=hasCsvBatches?'已接入完整CSV批次；历史审阅样本保留追溯。模拟数据/天气再分析各自标明，不能当实测。':'养殖数据是审阅样本，场景值不等于实测值。';
  const total=counts.instances??catalog.roots.reduce((sum,item)=>sum+(item.total_instance_count||0),0);
  $('content').innerHTML=`<section class="hero"><div><div class="eyebrow">LIANGZIHU · ONTOLOGY EXPLORER</div><h1>从一个本体，找到它的全部联系。</h1><p>先选择本体分类，再逐层进入子本体与实例。每个对象的属性、关联和证据，都在它自己的信息页中。</p><div class="summary-strip"><span class="summary-stat"><strong>${number(counts.classes??manifest.concepts.length)}</strong> 本体类型</span><span class="summary-stat"><strong>${number(total)}</strong> 对象实例</span><span class="summary-stat"><strong>${number(counts.resolved_relations)}</strong> 已解析关联</span></div></div><div class="hero-illustration" aria-hidden="true"><svg viewBox="0 0 180 140" fill="none"><path d="M90 26v33M90 60H35v32m55-32h55v32M35 92v20m55-52v52m55-20v20" stroke="currentColor" stroke-width="1.5"/><rect x="71" y="6" width="38" height="30" rx="8" fill="#e1ead8" stroke="#bccdaf"/><rect x="19" y="92" width="32" height="31" rx="7" fill="#edf1e7" stroke="#cbd6c0"/><rect x="74" y="92" width="32" height="31" rx="7" fill="#e5eddd" stroke="#c0d0b3"/><rect x="129" y="92" width="32" height="31" rx="7" fill="#edf1e7" stroke="#cbd6c0"/><circle cx="90" cy="21" r="4" fill="#9ab386"/><circle cx="35" cy="107" r="3" fill="#aabb97"/><circle cx="90" cy="107" r="3" fill="#aabb97"/><circle cx="145" cy="107" r="3" fill="#aabb97"/></svg></div></section><div class="section-heading"><h2>选择本体分类</h2><small>分类 → 子本体 → 实例 → 对应信息</small></div><div class="concept-grid">${catalog.top.map((item,index)=>conceptCard(item,index)).join('')}</div><div class="source-note"><span class="note-icon">ⓘ</span><div><strong>数据来源分别保留</strong><br>${sourceIntro}总方案与图纸空间对象保留独立来源、坐标说明和证据；缺失测量显示“未提供”。</div></div>`;
}
async function classView(concept,token){
  breadcrumbs(concept);
  const children=catalog.children(concept.iri);
  $('content').innerHTML=`<section class="class-header"><div class="eyebrow">ONTOLOGY / ${concept.instances_path?'OBJECT TYPE':'SUB-ONTOLOGY'}</div><div class="title-row"><h1>${esc(concept.label)}</h1><span class="count-pill">${number(concept.total_instance_count??concept.instance_count)} 个实例</span></div><p class="section-intro">${children.length?'选择一个子本体，进一步查看这一类对象。':'选择一个实例，查看它的属性、关系与来源信息。'}</p></section>${children.length?`<div class="section-heading"><h2>子本体</h2><small>${children.length} 个分类</small></div><div class="concept-grid child-grid">${children.map((item,index)=>conceptCard(item,index,true)).join('')}</div>`:''}${concept.instances_path?`<section id="instances-section"><div class="instance-toolbar"><h2>对象实例</h2><label class="instance-search"><span aria-hidden="true">⌕</span><input id="instance-search" type="search" placeholder="在当前本体中查找实例" aria-label="在当前本体中查找实例" value="${esc(currentRoute.q||'')}"></label></div><div id="instances-list"><p class="loading-label">正在读取实例…</p></div><div id="pagination"></div></section>`:''}`;
  if(concept.instances_path){
    const rows=await instances(concept);
    if(token!==renderId)return;
    currentClass=concept;currentRows=rows;paintInstances(currentRoute.q||'',currentRoute.page||1);
    $('instance-search').addEventListener('input',event=>paintInstances(event.target.value,1,true));
  }else if(!children.length){$('content').insertAdjacentHTML('beforeend','<div class="source-note">当前类型保留在本体结构中，没有纳入审阅的实例。</div>');}
}
function paintInstances(query,page,replace=false){
  const result=pageInstances(currentRows,query,page,12);
  if(replace){currentRoute={...currentRoute,q:query,page:result.page};history.replaceState(null,'',routeHash(currentRoute));routeHistory[routeHistory.length-1]=location.hash;}
  $('instances-list').innerHTML=result.items.length?`<div class="instance-grid">${result.items.map(row=>`<a class="instance-card" data-instance="${esc(row.iri)}" href="${href({view:'instance',iri:row.iri,class:currentClass.iri})}"><div class="instance-top"><span class="instance-dot"></span><h3>${esc(row.label||row.id)}</h3></div><div class="instance-id">${esc(row.id)}</div>${badge(instanceNature(row),row.nature==='synthetic'?'amber':'blue')}<div class="instance-card-foot"><span>${row.detail_path?'属性与关系按需读取':`${(row.properties||[]).length} 项属性 · ${relationCount(row,'outgoing')+relationCount(row,'incoming')} 条关联`}</span><span>↗</span></div></a>`).join('')}</div>`:'<p class="data-empty">当前本体中没有匹配的实例。</p>';
  $('pagination').innerHTML=`<div class="pagination"><button data-action="page" data-page="${result.page-1}" ${result.page<=1?'disabled':''}>← 上一页</button><span>${result.page} / ${result.pages} · 共 ${number(result.total)} 个实例</span><button data-action="page" data-page="${result.page+1}" ${result.page>=result.pages?'disabled':''}>下一页 →</button></div>`;
}
function provenanceRows(provenance){
  const labels={table:'来源记录类型',row_number:'原始行号',csv_line_end:'CSV 记录结束行',batch_id:'导入批次',package_sha256:'来源包 SHA256',source_sha256:'来源文件 SHA256',source_file_sha256:'来源文件 SHA256',source_origin_kind:'来源生成方式',status:'源记录状态',sample_reason:'纳入方式',source_record_iri:'来源记录 IRI',source_repository:'来源仓库',source_commit:'来源提交',source_file:'来源文件'};
  const reasons={small_table_coverage:'主数据完整保留',status_coverage:'状态分层覆盖',stratified_seed:'10% 分层样本',seed_fill:'确定性抽样',gis_owner:'GIS 要素所属对象',foreign_key_dependency:'关联完整性补入',full_csv_import:'完整 CSV 导入',full_source_table:'来源表完整保留',full_csv_batch:'完整 CSV 批次'};
  const origins={revised_rule_simulation:'规则模拟',weather_reanalysis:'天气再分析',reused_format_asset_catalog:'复用格式资产目录',batch_source_registry:'批次来源注册'};
  return Object.entries(labels).filter(([key])=>provenance?.[key]!==undefined&&provenance[key]!==null).map(([key,label])=>`<dt>${label}</dt><dd class="${key.includes('sha256')||key.includes('iri')?'mono':''}">${esc(key==='sample_reason'?reasons[provenance[key]]||provenance[key]:key==='source_origin_kind'?origins[provenance[key]]||provenance[key]:formatValue(provenance[key]))}</dd>`).join('');
}
function propertyPanel(row){
  const fields=[...(row.properties||[])];
  const scenario=fields.some(p=>p.field==='reviewStatus'&&p.value==='scenario_only_not_adopted');
  const priority=field=>/area|perimeter|depth|volume|面积|周长|水深|深度|体积/.test(`${field.field} ${field.label}`)?0:1;
  fields.sort((a,b)=>priority(a)-priority(b));
  return `${scenario?'<div class="map-warning">此记录为场景估算，未正式采用，不是现场实测值。</div>':''}<div class="property-filter"><span>${fields.length} 项来源属性 · 保留原始精度</span></div><dl class="property-list">${fields.map(property=>`<div class="property-row"><dt>${esc(property.label||property.field)}</dt><dd><span class="property-value">${esc(formatValue(property.value))}</span>${propertyUnit(property,fields)?`<span class="property-unit">${esc(propertyUnit(property,fields))}</span>`:''}<div class="property-meta">${badge(natureLabel(property.value===null?'missing':property.nature||row.nature),property.value===null?'gray':row.nature==='synthetic'?'amber':'')}<span>${esc(property.field||'')}</span></div></dd></div>`).join('')}</dl>${fields.length?'':'<p class="data-empty">当前对象没有已提供的属性值。</p>'}<p class="panel-note">数值性质由来源记录给出。未提供的长度、水深等信息保持为空，不使用其他对象的数据补全。</p>`;
}
async function relationsPanel(row){
  const directions=['outgoing','incoming'];
  const pages=await Promise.all(directions.map(direction=>snapshots.relations(row,direction,Number(currentRoute[direction+'Page'])||1,12)));
  let sections='';
  for(const [index,direction] of directions.entries()){
    const page=pages[index];
    sections+=`<section class="relation-section"><h3 class="relation-heading"><span>${direction==='outgoing'?'这个对象关联到':'关联到这个对象'}</span><span>${number(page.total)} 条</span></h3>${page.items.map(edge=>{
      const target=relationTarget(edge,direction),prefix=direction==='outgoing'?'target':'source';
      const contents=`<span class="relation-card-icon">${direction==='outgoing'?'↗':'↙'}</span><div class="relation-card-text"><div class="relation-predicate">${esc(edge.label||edge.field||edge.iri)}</div><strong>${esc(edge[prefix+'_label']||edge[prefix+'_id']||'来源未标注名称')}</strong><small>${esc(edge[prefix+'_id']||'')}</small></div>${badge(catalog.byId.get(edge[prefix+'_class_iri'])?.label||'关联对象')}<span class="card-arrow">›</span>`;
      return target?`<a class="relation-card" data-relation="${esc(target.iri)}" href="${href({view:'instance',...target})}">${contents}</a>`:`<div class="relation-card">${contents}</div>`;
    }).join('')||'<p class="data-empty">没有纳入当前快照的关联。</p>'}${page.pages>1?`<div class="pagination"><button data-action="relation-page" data-direction="${direction}" data-page="${page.page-1}" ${page.page<=1?'disabled':''}>←</button><span>${page.page} / ${page.pages}</span><button data-action="relation-page" data-direction="${direction}" data-page="${page.page+1}" ${page.page>=page.pages?'disabled':''}>→</button></div>`:''}</section>`;
  }
  const unresolved=row.unresolved_relations||[];
  if(unresolved.length)sections+=`<div class="unresolved-box">${unresolved.length} 条来源关系尚未解析，未建立对象跳转。<details><summary>查看来源关联记录</summary><pre class="mono">${esc(JSON.stringify(unresolved,null,2))}</pre></details></div>`;
  return sections;
}
function evidencePanel(row){
  const provenance=row.provenance||{},issues=provenance.issues||[];
  return `<article class="evidence-card"><h3>来源记录</h3><dl>${provenanceRows(provenance)}</dl></article><article class="evidence-card"><h3>RDF 身份</h3><dl><dt>对象 IRI</dt><dd class="mono">${esc(row.iri)}</dd><dt>类型 IRI</dt><dd class="mono">${esc(row.class_iri)}</dd><dt>数据性质</dt><dd>${esc(natureLabel(row.nature))}</dd><dt>采用状态</dt><dd>${esc(instanceAdoption(row).replace(' · ','，'))}</dd></dl></article>${provenance.source_evidence?`<article class="evidence-card"><h3>原图证据</h3><pre class="mono">${esc(JSON.stringify(provenance.source_evidence,null,2))}</pre></article>`:''}${issues.length?`<h3>来源问题保留</h3><ul class="issue-list">${issues.map(issue=>`<li>${esc(JSON.stringify(issue))}</li>`).join('')}</ul>`:'<p class="panel-note">来源位置随对象保留，审阅快照不改写原始证据。</p>'}`;
}
function demoPanel(row){
  const all=(row.demo_assignments||[]).filter(edge=>demoTarget(edge));
  const profiles=all.filter(edge=>edge.kind==='pond_profile'),activities=all.filter(edge=>edge.kind!=='pond_profile');
  const page=pageInstances(activities,'',Number(currentRoute.demoPage)||1,12);
  const card=edge=>{
    const target=demoTarget(edge),prefix=edge.direction==='incoming'?'source':'target';
    return `<a class="relation-card" data-demo="${esc(target.iri)}" href="${href({view:'instance',...target})}"><span class="relation-card-icon">↗</span><div class="relation-card-text"><div class="relation-predicate">${edge.kind==='pond_profile'?'演示水深 / 体积模板':'均衡演示分配'} · ${esc(catalog.byId.get(target.class)?.label||'关联对象')}</div><strong>${esc(edge[prefix+'_label']||edge[prefix+'_id'])}</strong><small>原始塘口标识：${esc(edge.original_pond_id||'未提供')} · ${esc(edge.reason)}</small></div>${badge('仅供演示','amber')}</a>`;
  };
  return `<div class="source-note" style="margin-top:0">这些关联来自独立演示分配图，便于查看对应业务，不代表现场归属。原始外键保持不变；演示水深与体积不会写入真实对象的测量属性。</div>${profiles.length?`<section class="relation-section" style="margin-top:22px"><h3 class="relation-heading">演示参数模板 · ${profiles.length}</h3>${profiles.map(card).join('')}</section>`:''}<section class="relation-section" style="margin-top:22px"><h3 class="relation-heading"><span>演示业务记录</span><span>${number(activities.length)} 条</span></h3>${page.items.map(card).join('')||'<p class="data-empty">当前对象没有演示业务记录。</p>'}${page.pages>1?`<div class="pagination"><button data-action="demo-page" data-page="${page.page-1}" ${page.page===1?'disabled':''}>← 上一页</button><span>${page.page} / ${page.pages}</span><button data-action="demo-page" data-page="${page.page+1}" ${page.page===page.pages?'disabled':''}>下一页 →</button></div>`:''}</section>`;
}
async function instanceView(concept,token){
  const rows=await instances(concept);
  if(token!==renderId)return;
  const summary=rows.find(item=>item.iri===currentRoute.iri);
  if(!summary){$('content').innerHTML=empty('当前快照没有这个实例','对象未找到，未使用其他记录替代。请返回对应本体查看。');return;}
  const row=await snapshots.detail(summary,concept.iri);
  if(token!==renderId)return;
  let spatialRoute=null;
  if(row.iri?.startsWith('urn:lzo:cad-gis:v1:instance:')){try{spatialRoute=spatialObjectRoute(row,await getMap());}catch{}}
  if(token!==renderId)return;
  breadcrumbs(concept,row);
  const tab=['properties','relations','evidence','rdf','demo'].includes(currentRoute.tab)?currentRoute.tab:'properties';
  const isMap=row.class_iri.startsWith('urn:lzo:fish-review:map:');
  const relationTotal=relationCount(row,'outgoing')+relationCount(row,'incoming');
  const panel=tab==='properties'?propertyPanel(row):tab==='relations'?await relationsPanel(row):tab==='evidence'?evidencePanel(row):tab==='demo'?demoPanel(row):'<p class="loading-label">正在读取 RDF 证据…</p>';
  if(token!==renderId)return;
  $('content').innerHTML=`<section class="object-header"><div class="eyebrow">${esc(concept.label)} / INSTANCE</div><h1>${esc(row.label||row.id)}</h1><div class="object-meta">${badge(instanceNature(row),row.nature==='synthetic'?'amber':'blue')}${badge(instanceAdoption(row),'gray')}${badge(live.available?'RDF 在线查询':'RDF 回读快照')}<span class="instance-id">${esc(row.id)}</span></div><div class="object-iri">${esc(row.iri)}</div></section><div class="object-panels"><section class="panel"><nav class="tabs" aria-label="对象详情">${[['properties',isMap?'来源资料':'属性',(row.properties||[]).length],['relations','关系',relationTotal],['evidence','来源',null],...((row.demo_assignments||[]).length||isMap?[['demo','演示业务',(row.demo_assignments||[]).length]]:[]),['rdf','RDF 证据',null]].map(([key,label,count])=>`<a href="${href({...currentRoute,tab:key})}" class="${tab===key?'active':''}" data-tab="${key}">${label}${count!==null?`<small>${number(count)}</small>`:''}</a>`).join('')}</nav><div class="panel-body" id="object-panel">${panel}</div></section><aside class="detail-side"><section class="panel"><div class="panel-heading"><h2>对象归属</h2></div><div class="panel-body"><dl class="source-list"><dt>所属本体</dt><dd><a class="link-text" href="${href({view:'class',iri:concept.iri})}">${esc(concept.label)}</a></dd><dt>来源标识</dt><dd>${esc(row.id)}</dd><dt>已解析关联</dt><dd>${number(relationTotal)} 条</dd><dt>来源性质</dt><dd>${esc(natureLabel(row.nature))}</dd></dl><a class="side-action" href="${href({...currentRoute,tab:'relations'})}">沿关系继续查看 →</a></div></section><section class="panel"><div class="panel-heading"><h2>来源定位</h2></div><div class="panel-body"><dl class="source-list">${provenanceRows(row.provenance)}</dl><a class="side-action" href="${href({...currentRoute,tab:'evidence'})}">查看完整证据 →</a></div></section></aside></div>`;
  if(spatialRoute)$('content').querySelector('.object-header').insertAdjacentHTML('beforeend',`<a class="side-action" href="${href(spatialRoute)}">在地图中查看 →</a>`);
  if(tab==='rdf') await rdfPanel(row,token);
}
async function rdfPanel(row,token){
  let result;
  if(live.available){
    try{result=await json('/api/ontology/resource?iri='+encodeURIComponent(row.iri)+'&outgoing_offset='+(Number(currentRoute.rdfOut)||0)+'&incoming_offset='+(Number(currentRoute.rdfIn)||0));}catch{}
  }
  if(token!==renderId)return;
  if(result?.mode==='fuseki'){
    const outgoing=result.outgoing||[],incoming=result.incoming||[];
    $('object-panel').innerHTML=`<div class="source-note" style="margin-top:0">当前内容直接读取本机 Fuseki / SPARQL。${result.truncated?'结果已限量，完整属性与关联可在其他页签查看。':''}</div><h3 class="relation-heading" style="margin-top:22px">当前对象的 RDF 陈述 · ${outgoing.length}</h3><dl class="property-list">${outgoing.map(triple=>`<div class="property-row"><dt>${esc(triple.label||triple.predicate)}<div class="mono">${esc(triple.predicate)}</div></dt><dd>${esc(formatValue(triple.object?.value))}<div class="property-meta">${esc(triple.object?.datatype||triple.object?.type||'')}${triple.object?.lang?' · '+esc(triple.object.lang):''}</div></dd></div>`).join('')}</dl><h3 class="relation-heading" style="margin-top:22px">指向当前对象的 RDF 陈述 · ${incoming.length}</h3>${incoming.map(triple=>`<div class="relation-card"><div class="relation-card-text"><div class="relation-predicate">${esc(triple.label||triple.predicate)}</div><small class="mono">${esc(triple.subject)}</small></div></div>`).join('')||'<p class="data-empty">当前查询没有入向陈述。</p>'}`;
    $('object-panel').insertAdjacentHTML('beforeend',`<div class="pagination"><button data-action="rdf-page" data-direction="rdfOut" data-offset="${result.next_outgoing_offset??0}" ${result.next_outgoing_offset==null?'disabled':''}>更多出向陈述</button><button data-action="rdf-page" data-direction="rdfIn" data-offset="${result.next_incoming_offset??0}" ${result.next_incoming_offset==null?'disabled':''}>更多入向陈述</button></div><p class="panel-note">当前出向起点 ${Number(currentRoute.rdfOut)||0}，入向起点 ${Number(currentRoute.rdfIn)||0}。${result.truncated?'还有未显示的陈述，可分别继续分页。':'当前查询已无未显示陈述。'}</p>`);
  }else{
    const relations=await relationsPanel(row);
    if(token!==renderId)return;
    $('object-panel').innerHTML=`<div class="source-note" style="margin-top:0">当前是 RDF 回读快照，未连接实时 SPARQL 服务。以下 IRI 和已解析关系来自发布的本体图谱。</div><article class="evidence-card" style="margin-top:20px"><h3>对象与类型</h3><dl><dt>subject</dt><dd class="mono">${esc(row.iri)}</dd><dt>rdf:type</dt><dd class="mono">${esc(row.class_iri)}</dd></dl></article><h3 class="relation-heading">已解析对象关系</h3>${relations}`;
  }
}

async function getMap(historical=false){
  if(!mapData){const value=await json('data/map-features.json');if(!['farm-local-map/1','lzo-spatial-map/2'].includes(value.contract||value.schema_version)||!Array.isArray(value.layers))throw Error('地图来源格式不匹配');mapData=value;}
  if(!historical||mapData.schema_version==='farm-local-map/1')return mapData;
  if(!legacyMapData){const path=mapData.legacy_map_path||'data/legacy-map-features.json';if(!/^data\/[a-z0-9_-]+\.json$/i.test(path))throw Error('历史地图路径无效');const value=await json(path);if(value.schema_version!=='farm-local-map/1'||!Array.isArray(value.layers))throw Error('历史地图格式不匹配');legacyMapData=value;}
  return legacyMapData;
}
function coordinates(geometry){
  const result=[];
  function walk(value){if(Array.isArray(value)&&value.length>=2&&typeof value[0]==='number'&&typeof value[1]==='number'){if(value.slice(0,2).every(Number.isFinite))result.push(value);}else if(Array.isArray(value))value.forEach(walk);}
  walk(geometry?.coordinates);return result;
}
function geometryMarkup(feature,index){
  const geometry=feature.geometry,kind=geometry?.type,props=feature.properties||{},point=p=>p.slice(0,2).map(Number).join(',');
  if(!coordinates(geometry).length)return '';
  const boundary=/boundary|redline|红线/.test(props.kind||'')||(!props.object_iri&&/bound|redline/i.test(feature.id));
  const color=/^#[0-9a-f]{6}$/i.test(props.color||'')?props.color:null;
  const attrs=`class="map-feature ${/pond|塘|水/.test(props.kind||'')?'pond':''} ${boundary?'boundary':''}" ${color?`style="--feature-fill:${color}80;--feature-stroke:${color}"`:''} data-action="feature" data-feature="${index}" tabindex="0" role="button" aria-label="${esc(props.label||feature.id)}"`;
  const ring=points=>'M'+points.map(point).join('L')+'Z';
  if(kind==='Polygon')return `<path ${attrs} d="${geometry.coordinates.map(ring).join('')}" fill-rule="evenodd"/>`;
  if(kind==='MultiPolygon')return `<path ${attrs} d="${geometry.coordinates.flatMap(poly=>poly.map(ring)).join('')}" fill-rule="evenodd"/>`;
  if(kind==='LineString')return `<polyline ${attrs} points="${geometry.coordinates.map(point).join(' ')}" fill="none"/>`;
  if(kind==='Point')return `<circle ${attrs} cx="${geometry.coordinates[0]}" cy="${geometry.coordinates[1]}" r="3"/>`;
  return '';
}
async function mapView(token){
  breadcrumbs();
  const data=await getMap(currentRoute.historical==='1');if(token!==renderId)return;
  if(data.contract==='lzo-spatial-map/2'){
    $('content').innerHTML='<section class="class-header"><div class="eyebrow">SPATIAL OBJECTS / CANDIDATE PLAN</div><h1>在地图中找到对象</h1><p class="section-intro">一张平面图，连接图纸范围、设施文字锚点与摄像头候选。选择对象，继续查看本体属性与关系。</p></section><div id="spatial-mount"></div>';
    mountedView=mountSpatialMap($('spatial-mount'),data,{releaseId,selectedIri:currentRoute.object,onSelect:target=>{if(token===renderId)go({view:'instance',...target});},onLegacy:()=>{if(token===renderId)go({view:'map',historical:1});}});
    return;
  }
  const layer=data.layers.find(item=>item.id===currentRoute.layer)||data.layers[0];
  if(!layer){$('content').innerHTML=empty('地图资料尚未就绪','没有收到已标注来源的地图图层。');return;}
  if(layer.axis?.y!=='down'||layer.georeferenced!==false)throw Error('此页面只显示明确标注的未配准局部坐标图层');
  const features=layer.features||[],bounds=layer.viewBox;
  const points=features.flatMap(feature=>coordinates(feature.geometry));
  const extent=points.reduce((box,p)=>[Math.min(box[0],p[0]),Math.min(box[1],p[1]),Math.max(box[2],p[0]),Math.max(box[3],p[1])],[Infinity,Infinity,-Infinity,-Infinity]);
  const padding=Math.max(extent[2]-extent[0],extent[3]-extent[1])*.06;
  const camera=points.length?[extent[0]-padding,extent[1]-padding,extent[2]-extent[0]+padding*2,extent[3]-extent[1]+padding*2]:bounds;
  if(!Array.isArray(bounds)||bounds.length!==4||!bounds.every(Number.isFinite))throw Error('地图范围无效');
  $('content').innerHTML=`<section class="class-header"><div class="eyebrow">SPATIAL OBJECTS / SOURCE PLAN</div><div class="title-row"><h1>在地图中找到对象</h1><span class="count-pill">${features.length} 个图形</span></div><p class="section-intro">选择图层，点击田块或塘口，进入对应的真实来源空间对象。不同图纸分别显示。</p></section><div class="map-toolbar"><select id="map-layer" aria-label="选择来源地图图层">${data.layers.map(item=>`<option value="${esc(item.id)}" ${item.id===layer.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select><label><input id="map-labels" type="checkbox"> 显示图形名称</label></div><div class="map-warning">总方案与纸面图均按原始局部坐标显示，尚未地理配准，不能用于经纬度定位。此处未以合成塘口示意图替代真实来源地图。</div><div class="map-layout"><section class="map-stage"><svg id="source-map" viewBox="${camera.join(' ')}" preserveAspectRatio="xMidYMid meet" aria-label="${esc(layer.label)}">${features.map(geometryMarkup).join('')}<g id="map-name-labels" hidden>${features.map(feature=>{const points=coordinates(feature.geometry);if(!points.length)return '';const x=points.reduce((sum,p)=>sum+p[0],0)/points.length,y=points.reduce((sum,p)=>sum+p[1],0)/points.length;return `<text class="map-label" x="${x}" y="${y}">${esc(feature.properties?.label||feature.id)}</text>`;}).join('')}</g></svg><div class="map-caption"><span>${esc(layer.label)} · 原始图形轮廓</span><span>${esc(layer.coordinate_space)} / ${esc(layer.units)} · 未配准</span></div></section><aside class="map-sidebar"><section class="panel"><div class="panel-heading"><h2>图层来源</h2></div><div class="panel-body"><p>此图层保留来源几何，不与养殖合成样本中的塘口自动合并。</p><dl class="source-list"><dt>来源仓库</dt><dd>${esc(data.source?.repository||'未提供')}</dd><dt>来源提交</dt><dd class="mono">${esc(data.source?.commit||'未提供')}</dd><dt>空间参考</dt><dd>局部图面坐标 · CRS 未确定</dd><dt>对象跳转</dt><dd>仅按已给出的本体 IRI 关联</dd></dl><div class="map-legend"><span><i class="legend-swatch"></i>田块 / 空间对象</span><span><i class="legend-swatch pond"></i>塘口 / 水体</span></div></div></section><section class="panel"><div class="panel-heading"><h2>图中对象</h2></div><div class="panel-body"><p>也可以从以下名称进入对象。</p><div class="map-feature-list">${features.map((feature,index)=>`<button class="map-feature-button" data-action="feature" data-feature="${index}"><span>${esc(feature.properties?.label||feature.id)}</span><span>↗</span></button>`).join('')}</div></div></section></aside></div>`;
  if(mapData?.contract==='lzo-spatial-map/2')$('content').insertAdjacentHTML('afterbegin','<a class="side-action historical-return" href="#view=map">← 返回当前 CAD 平面地图</a>');
  $('map-layer').addEventListener('change',event=>go({view:'map',historical:currentRoute.historical,layer:event.target.value}));
  $('map-labels').addEventListener('change',event=>{$('map-name-labels').style.display=event.target.checked?'':'none';$('map-name-labels').removeAttribute('hidden');});
  $('map-name-labels').style.display='none';
  $('source-map').dataset.layer=layer.id;
}
async function openFeature(index){
  const token=renderId,data=await getMap(currentRoute.historical==='1');if(token!==renderId)return;
  const layer=data.layers.find(item=>item.id===$('source-map')?.dataset.layer)||data.layers[0],feature=layer.features[index],props=feature.properties||{};
  if(props.object_iri&&props.object_class_iri&&catalog.byId.has(props.object_class_iri))go({view:'instance',iri:props.object_iri,class:props.object_class_iri});
  else go({view:'feature',historical:currentRoute.historical,layer:layer.id,iri:feature.id});
}
async function featureView(token){
  const data=await getMap(currentRoute.historical==='1');if(token!==renderId)return;
  const layer=data.layers.find(item=>item.id===currentRoute.layer),feature=layer?.features.find(item=>item.id===currentRoute.iri);
  breadcrumbs();
  if(!feature){$('content').innerHTML=empty('没有找到来源图形','请返回地图选择一个对象。');return;}
  const props=feature.properties||{};
  $('content').innerHTML=`<section class="object-header"><div class="eyebrow">SOURCE SPATIAL OBJECT</div><h1>${esc(props.label||feature.id)}</h1><div class="object-meta">${badge(natureLabel(props.data_nature),'blue')}${badge(props.object_iri?'本体分片尚未就绪':'尚无本体对象绑定','amber')}</div></section><section class="panel"><div class="panel-heading"><h2>真实来源空间信息</h2></div><div class="panel-body"><dl class="property-list">${[['来源空间标识',props.source_spatial_id],['图层',layer.label],['对象类型',props.kind],['边界状态',props.boundary_status],['本体 IRI',props.object_iri],['来源证据',props.source_evidence],['来源尺寸',props.metrics]].map(([label,value])=>`<div class="property-row"><dt>${label}</dt><dd>${esc(formatValue(value))}</dd></div>`).join('')}</dl><p class="panel-note">此图形没有可用的完整本体跳转，不以合成样本对象替代。未提供的测量值保持为空。</p><a class="primary-action" href="${href({view:'map',layer:layer.id})}">返回来源地图</a></div></section>`;
}

async function networkView(token){
  breadcrumbs();
  if(!networkData){try{networkData=await json('/api/v1/network');}catch{try{networkData=await json('data/ontology-network.json');}catch{if(token===renderId)$('content').innerHTML=empty('当前版本尚未发布本体关系网','可继续从本体目录逐级查看类型与实例。关系网需要与当前页面同一发布的网络快照。');return;}}}
  if(token!==renderId)return;
  if(networkData.contract!=='lzo-ontology-network/1'||!networkData.nodes?.length){$('content').innerHTML=empty('当前版本尚未发布本体关系网','可以继续从本体目录查看类型与实例。关系网就绪后，将从同一发布读取真实关系。');return;}
  $('content').innerHTML='<section class="class-header"><div class="eyebrow">ONTOLOGY / CONNECTED KNOWLEDGE</div><h1>本体关系球</h1><p class="section-intro">旋转球面，发现类型之间的联系。由本体定义与已发布实例关系构成，选择节点后逐级探索。</p></section><div id="network-mount"></div>';
  const viewSession=createViewSession(releaseId,()=>token===renderId?releaseId:null);
  const sphere=mountOntologySphere($('network-mount'),networkData,{releaseId,onSelectClass:iri=>{if(token===renderId)go({view:'class',iri});},onSelectEdge:edge=>{const target=$('network-mount')?.querySelector('.network-edge-results');if(target&&token===renderId)networkRelations(edge,target,null,token,[],viewSession);}});
  mountedView={destroy(){sphere.destroy();viewSession.destroy();}};
}
async function networkRelations(edge,target,cursor,token,trail,viewSession){
  const current=()=>token===renderId&&target.isConnected&&viewSession.current();
  if(edge.kind==='schema'){
    target.innerHTML=`<p class="panel-note">此边为本体定义。进入端点类型查看下级与实例。</p>${[edge.source,edge.target].map(iri=>`<a class="side-action" href="${href({view:'class',iri})}">${esc(catalog.byId.get(iri)?.label||iri)} →</a>`).join('')}`;return;
  }
  target.innerHTML='<p class="loading-label">正在读取 12 条以内的实例关系…</p>';
  try{
    const params=new URLSearchParams({source:edge.source,target:edge.target,predicate:edge.predicate,limit:'12'});if(cursor)params.set('cursor',cursor);
    let result;const loaded=await viewSession.load(()=>json('/api/v1/network-relations?'+params),value=>result=value);if(!loaded||!current())return;
    const items=Array.isArray(result.items)?result.items.slice(0,12):[],offset=Number(result.offset)||0;
    target.innerHTML=`<h4 class="sphere-neighbor-title">实例关系 <span>${number(result.total??edge.count)}</span></h4>${items.map(row=>`<div class="network-instance-pair"><a href="${href({view:'instance',iri:row.source_iri,class:row.source_class_iri})}">${esc(row.source_label||row.source_iri)}</a><small>↓ ${esc(edge.label||row.predicate)}</small><a href="${href({view:'instance',iri:row.target_iri,class:row.target_class_iri})}">${esc(row.target_label||row.target_iri)}</a></div>`).join('')||'<p class="panel-note">当前没有可公开展开的实例关系。</p>'}<div class="pagination"><button data-network-page="previous" ${trail.length?'':'disabled'}>←</button><span>显示 ${items.length?offset+1:0}–${offset+items.length}</span><button data-network-page="next" ${result.next_cursor?'':'disabled'}>→</button></div><p class="panel-note">每次最多读取 12 条；仅显示当前发布的公开对象关联。</p>`;
    target.querySelector('[data-network-page="previous"]').onclick=()=>{if(current()&&trail.length)networkRelations(edge,target,trail.at(-1),token,trail.slice(0,-1),viewSession);};
    target.querySelector('[data-network-page="next"]').onclick=()=>{if(current()&&result.next_cursor)networkRelations(edge,target,result.next_cursor,token,[...trail,cursor],viewSession);};
  }catch(error){if(current())target.innerHTML=`<p class="panel-note">实例关系暂不可用：${esc(error.message)}。可先进入端点本体查看已发布对象。</p>`;}
}

async function render(){
  if(!catalog)return;
  mountedView?.destroy();mountedView=null;
  const token=++renderId;currentRoute=readRoute(location.hash);closeTree();tree();
  try{
    if(currentRoute.view==='home')home();
    else if(currentRoute.view==='class'){
      const concept=catalog.byId.get(currentRoute.iri);if(!concept)throw Error('没有找到该本体类型');
      await classView(concept,token);
    }else{
      $('content').innerHTML=loading();
      if(currentRoute.view==='instance'){
        const concept=catalog.byId.get(currentRoute.class);if(!concept)throw Error('没有找到该对象所属本体');
        await instanceView(concept,token);
      }else if(currentRoute.view==='map')await mapView(token);
      else if(currentRoute.view==='network')await networkView(token);
      else if(currentRoute.view==='feature')await featureView(token);
    }
    if(token===renderId)window.scrollTo({top:0,behavior:'instant'});
  }catch(error){if(token===renderId)$('content').innerHTML=empty('内容尚未就绪',error.message+'。请确认当前页面的 RDF 快照与来源图层已完整生成。');}
}
document.addEventListener('click',event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  const action=target.dataset.action;
  if(action==='tree'){const iri=target.dataset.iri;expanded.has(iri)?expanded.delete(iri):expanded.add(iri);tree();}
  if(action==='page')paintInstances($('instance-search').value,Number(target.dataset.page),true);
  if(action==='relation-page')go({...currentRoute,[target.dataset.direction+'Page']:Number(target.dataset.page)});
  if(action==='demo-page')go({...currentRoute,demoPage:Number(target.dataset.page)});
  if(action==='rdf-page')go({...currentRoute,[target.dataset.direction]:Number(target.dataset.offset)});
  if(action==='feature')openFeature(Number(target.dataset.feature));
});
document.addEventListener('keydown',event=>{if(event.target.matches('.map-feature')&&['Enter',' '].includes(event.key)){event.preventDefault();openFeature(Number(event.target.dataset.feature));}if(event.key==='Escape')closeTree();});
$('open-tree').onclick=()=>{$('sidebar').classList.add('open');$('tree-shade').hidden=false;};
$('close-tree').onclick=closeTree;$('tree-shade').onclick=closeTree;
$('go-back').onclick=()=>{if(routeHistory.length>1)history.back();else if(currentRoute.view==='instance')go({view:'class',iri:currentRoute.class});else if(currentRoute.view==='class'){const parent=catalog.byId.get(currentRoute.iri)?.parent_iri;go(parent?{view:'class',iri:parent}:{view:'home'});}else go({view:'home'});};
window.addEventListener('hashchange',()=>{const hash=location.hash||'#view=home';if(routeHistory.at(-2)===hash)routeHistory.pop();else if(routeHistory.at(-1)!==hash)routeHistory.push(hash);render();});

async function start(){
  try{manifest=await json('data/manifest.json');catalog=createCatalog(manifest);$('graph-status').textContent=manifest.jena_verified===true?'已验证 RDF 回读快照':'RDF 审阅快照';await render();}
  catch(error){$('content').innerHTML=empty('本体快照尚未就绪','当前没有完整可读的 RDF 概念数据。请先生成本体快照，再通过本地预览服务打开页面。');$('graph-status').textContent='快照未就绪';}
  try{const status=await json('/api/ontology/status');if(status.mode==='fuseki'&&status.available===true){live=status;$('graph-status').textContent='Fuseki / SPARQL 已连接';if(currentRoute.view==='instance')render();}}catch{}finally{liveChecked=true;}
}
start();

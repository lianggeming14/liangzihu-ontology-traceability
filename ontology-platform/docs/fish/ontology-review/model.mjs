export function createCatalog(manifest) {
  if(manifest?.contract!=='fish-rdf-review/1'||!Array.isArray(manifest.concepts)) throw Error('不支持的本体快照格式');
  const byId=new Map();
  for(const item of manifest.concepts){
    if(!item.iri||byId.has(item.iri)) throw Error('本体概念标识缺失或重复');
    if(item.instances_path&&!/^classes\/[a-z0-9_-]+\.json(?:\.gz)?$/i.test(item.instances_path)) throw Error('实例分片路径无效');
    byId.set(item.iri,item);
  }
  const path=id=>{
    const result=[],seen=new Set();
    for(let item=byId.get(id);item;item=item.parent_iri?byId.get(item.parent_iri):null){
      if(seen.has(item.iri)) throw Error('本体层级存在循环');
      seen.add(item.iri);result.unshift(item);
      if(item.parent_iri&&!byId.has(item.parent_iri)) throw Error('本体父类不存在');
    }
    return result;
  };
  const children=id=>(byId.get(id)?.children||[]).map(child=>{
    const item=byId.get(child);
    if(!item||item.parent_iri!==id) throw Error('本体父子关系不一致');
    return item;
  });
  for(const id of byId.keys()){path(id);children(id);}
  const roots=manifest.concepts.filter(item=>!item.parent_iri);
  return {byId,path,children,roots,top:roots.length===1&&children(roots[0].iri).length?children(roots[0].iri):roots};
}

export function pageInstances(rows,query='',page=1,pageSize=12){
  const term=query.trim().toLocaleLowerCase();
  const filtered=term?rows.filter(row=>`${row.label} ${row.id}`.toLocaleLowerCase().includes(term)):rows;
  const pages=Math.max(1,Math.ceil(filtered.length/pageSize));
  page=Math.max(1,Math.min(pages,Number(page)||1));
  return {items:filtered.slice((page-1)*pageSize,page*pageSize),page,pages,total:filtered.length};
}

export function routeHash(route){
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(route)) if(value!==undefined&&value!==null&&value!=='') params.set(key,String(value));
  return '#'+params.toString();
}
export function readRoute(hash){
  const route=Object.fromEntries(new URLSearchParams(hash.replace(/^#/,'')));
  if(!['home','class','instance','map','feature'].includes(route.view)) return {view:'home'};
  if(route.page) route.page=Math.max(1,Number.parseInt(route.page,10)||1);
  return route;
}
export function relationTarget(edge,direction){
  if(edge.resolution!=='resolved') return null;
  const prefix=direction==='incoming'?'source':'target';
  return edge[prefix+'_iri']&&edge[prefix+'_class_iri']?{iri:edge[prefix+'_iri'],class:edge[prefix+'_class_iri']}:null;
}
export function demoTarget(edge){
  if(edge.assignment_policy!=='balanced_demo_only'||edge.synthetic!==true)return null;
  const prefix=edge.direction==='incoming'?'source':'target';
  return edge[prefix+'_iri']&&edge[prefix+'_class_iri']?{iri:edge[prefix+'_iri'],class:edge[prefix+'_class_iri']}:null;
}
export function propertyUnit(property,properties){
  if(property.unit)return property.unit;
  const name=property.field||property.iri?.split(/[#:/]/).at(-1);
  const sibling=name==='numericValue'?'unitText':name==='siValue'?'siUnit':null;
  return sibling?properties.find(value=>(value.field||value.iri?.split(/[#:/]/).at(-1))===sibling)?.value||null:null;
}
export async function decodeSnapshot(response){
  const bytes=new Uint8Array(await response.arrayBuffer());
  if(bytes[0]===31&&bytes[1]===139)return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
  return JSON.parse(new TextDecoder().decode(bytes));
}
export function formatValue(value){
  if(value===null||value===undefined||value==='') return '未提供';
  if(typeof value==='boolean') return value?'是':'否';
  return typeof value==='object'?JSON.stringify(value):String(value);
}
export function natureLabel(value){
  return ({synthetic:'合成场景',test:'测试数据',imported_unverified:'外部来源 · 未核验',verified:'已核验来源',
    scenario_assumption:'场景设定',derived_simulation:'模拟边界计算值',derived_geometry:'几何计算值',
    source_annotation:'原图标注',measured:'来源实测',drawing_transcription:'图纸转录',
    image_traced:'图像轮廓提取',missing:'未提供'})[value]||value||'来源性质未标注';
}
export function instanceNature(row){
  if((row.properties||[]).some(p=>p.field==='reviewStatus'&&p.value==='scenario_only_not_adopted'))return '场景估算 · 未采用';
  if((row.properties||[]).some(p=>p.field==='reviewStatus'&&p.value==='computed_paper_geometry_not_ground_survey'))return '纸面几何计算 · 非实测';
  return natureLabel(row.nature);
}

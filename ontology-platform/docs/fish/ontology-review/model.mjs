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
function snapshotPath(path,kind){
  const pattern=kind==='details'?/^details\/[a-z0-9_-]+\/[a-z0-9_-]+\.json\.gz$/i:/^relations\/[a-z0-9_-]+\/[a-z0-9_-]+\/(?:incoming|outgoing)-[0-9]+\.json\.gz$/i;
  if(typeof path!=='string'||!pattern.test(path))throw Error('实例或关系分片路径无效');
  return path;
}
export function relationCount(row,direction){
  const count=row[direction+'_count'];
  return Number.isSafeInteger(count)&&count>=0?count:(row[direction]||[]).length;
}
export function createSnapshotLoader(read){
  const cache=new Map();
  const chunk=path=>{
    if(!cache.has(path)){
      const promise=Promise.resolve().then(()=>read(path));
      cache.set(path,promise);
      promise.catch(()=>{if(cache.get(path)===promise)cache.delete(path);});
    }
    return cache.get(path);
  };
  const checked=async(path,validate)=>{
    try{const value=await chunk(path);return validate(value);}
    catch(error){cache.delete(path);throw error;}
  };
  return {
    async detail(summary,classIri){
      if(!summary.detail_path)return summary;
      const path=snapshotPath(summary.detail_path,'details');
      return checked(path,value=>{
        if(value?.contract!=='fish-rdf-review/1'||value.class_iri!==classIri||summary.class_iri!==classIri||!Array.isArray(value.instances)||value.instances.length>500)throw Error('实例明细分片与本体类型或格式不一致');
        const matches=value.instances.filter(row=>row.iri===summary.iri);
        if(matches.length!==1||matches[0].class_iri!==classIri)throw Error('实例明细没有唯一匹配的对象或类型');
        return matches[0];
      });
    },
    async relations(row,direction,page=1,pageSize=12){
      if(!['incoming','outgoing'].includes(direction))throw Error('关系方向无效');
      const paths=row[direction+'_pages'];
      if(paths===undefined)return pageInstances(row[direction]||[],'',page,pageSize);
      const total=row[direction+'_count'],chunkSize=row[direction+'_page_size'];
      if(!Array.isArray(paths)||!Number.isSafeInteger(total)||total<0||!Number.isSafeInteger(chunkSize)||chunkSize<1||!Number.isSafeInteger(pageSize)||pageSize<1||paths.length!==Math.ceil(total/chunkSize))throw Error('关系分页元数据无效');
      paths.forEach(path=>snapshotPath(path,'relations'));
      const pages=Math.max(1,Math.ceil(total/pageSize));
      page=Math.max(1,Math.min(pages,Math.floor(Number(page)||1)));
      const start=(page-1)*pageSize,end=Math.min(start+pageSize,total),requests=[];
      for(let index=Math.floor(start/chunkSize);index*chunkSize<end;index++){
        requests.push(checked(paths[index],value=>{
          if(value?.contract!=='fish-rdf-relations/1'||value.instance_iri!==row.iri||value.direction!==direction||!Array.isArray(value.edges)||value.edges.length!==Math.min(chunkSize,total-index*chunkSize))throw Error('关系分片与当前对象、方向或数量不一致');
          return value.edges.slice(Math.max(0,start-index*chunkSize),Math.min(chunkSize,end-index*chunkSize));
        }));
      }
      return {items:(await Promise.all(requests)).flat(),page,pages,total};
    },
  };
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
export function instanceAdoption(row){
  return row.adoption_status==='csv_batch_not_formally_adopted'||row.provenance?.sample_reason==='full_csv_batch'?'完整 CSV 批次 · 未正式采用':'审阅样本 · 未正式采用';
}

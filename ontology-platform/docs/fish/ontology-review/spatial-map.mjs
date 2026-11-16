import {pointerGesture} from './sphere-math.mjs';
import {createViewSession} from './ontology-sphere.mjs';
import {formatValue,natureLabel} from './model.mjs';

const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={field:'图纸田块',pond:'塘口候选',facility:'设施文字锚点',camera:'摄像头候选',road:'道路',canal:'沟渠',region:'区域'};
const validPoint=p=>Array.isArray(p)&&p.length>=2&&typeof p[0]==='number'&&typeof p[1]==='number'&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90;
function validGeometry(g){
  const line=coords=>Array.isArray(coords)&&coords.length>=2&&coords.every(validPoint);
  const ring=coords=>line(coords)&&coords.length>=4&&coords[0][0]===coords.at(-1)[0]&&coords[0][1]===coords.at(-1)[1];
  const polygon=coords=>Array.isArray(coords)&&coords.length>0&&coords.every(ring);
  if(g?.type==='Point')return validPoint(g.coordinates);
  if(g?.type==='LineString')return line(g.coordinates);
  if(g?.type==='MultiLineString')return Array.isArray(g.coordinates)&&g.coordinates.length>0&&g.coordinates.every(line);
  if(g?.type==='Polygon')return polygon(g.coordinates);
  if(g?.type==='MultiPolygon')return Array.isArray(g.coordinates)&&g.coordinates.length>0&&g.coordinates.every(polygon);
  return false;
}
function points(geometry){const result=[];const walk=value=>{if(validPoint(value))result.push(value);else if(Array.isArray(value)&&Array.isArray(value[0]))value.forEach(walk);};walk(geometry?.coordinates);return result;}
export function geometryBounds(geometries){
  const coordinates=geometries.flatMap(points);if(!coordinates.length)return null;
  return coordinates.reduce((b,[x,y])=>[Math.min(b[0],x),Math.min(b[1],y),Math.max(b[2],x),Math.max(b[3],y)],[Infinity,Infinity,-Infinity,-Infinity]);
}
export function geometryPath(geometry,project){
  if(!validGeometry(geometry))return '';
  const line=(ring,close)=>{if(!Array.isArray(ring)||ring.length<2||!ring.every(validPoint))return '';return ring.map((p,i)=>(i?'L':'M')+project(p).join(',')).join('')+(close?'Z':'');};
  if(geometry?.type==='Polygon')return geometry.coordinates.map(ring=>line(ring,true)).join('');
  if(geometry?.type==='MultiPolygon')return geometry.coordinates.flatMap(poly=>poly.map(ring=>line(ring,true))).join('');
  if(geometry?.type==='LineString')return line(geometry.coordinates,false);
  if(geometry?.type==='MultiLineString')return geometry.coordinates.map(ring=>line(ring,false)).join('');
  return '';
}
export function prepareSpatialMap(data){
  if(data?.contract!=='lzo-spatial-map/2'||!Array.isArray(data.features)||!Array.isArray(data.display_features))throw Error('空间地图格式不匹配');
  const objects=new Map(data.features.filter(f=>f.iri).map(f=>[f.iri,f]));
  for(const f of data.unlocated||[])if(f.iri&&!objects.has(f.iri))objects.set(f.iri,f);
  // Canonical polygons are evidence/identity only. Only reviewed display pieces are drawn.
  const display=data.display_features.filter(f=>['Polygon','MultiPolygon'].includes(f.geometry?.type)&&validGeometry(f.geometry)).map(f=>({...f,object_iris:(f.object_iris||[]).filter(iri=>objects.has(iri))}));
  for(const f of objects.values())if(['Point','LineString','MultiLineString'].includes(f.geometry?.type)&&validGeometry(f.geometry))display.push({...f,object_iris:[f.iri]});
  const unlocated=[...objects.values()].filter(f=>!validGeometry(f.geometry));
  const fit=display.filter(f=>!['road','canal'].includes(f.kind)&&!f.attributes?.exclude_from_initial_fit);
  const bounds=geometryBounds(fit.map(f=>f.geometry))||geometryBounds(display.filter(f=>!f.attributes?.exclude_from_initial_fit).map(f=>f.geometry));
  return {objects,display,unlocated,bounds};
}
const attributeNames={area_m2:'计算面积（m²）',perimeter_m:'计算周长（m）',length_m:'计算长度（m）',depth:'水深',depth_m:'水深（m）',volume_m3:'体积（m³）',method:'计算方法',units:'单位',assumptions:'计算前提',source_values:'原来源数值',position_status:'位置依据',device_iri:'绑定设备 IRI',area_memberships:'空间范围命中',original_cad_crs_status:'原始 CAD 坐标参考',registration_status:'配准状态',position_basis:'位置依据',source_candidate_number:'来源候选序号'};
const positionLabels={candidate_approximate:'候选近似配准 · 待核实',candidate_text_anchor:'图纸文字锚点 · 非实物位置',candidate_cad_symbol:'CAD 图标候选位置',unlocated:'待定位 · 未提供坐标',invalid_geometry_quarantined:'几何无效 · 已隔离，未修复',derived_candidate_spatial_evidence:'候选坐标推导的空间证据',UNKNOWN:'未知 · 尚未确认'};
const methodLabels={'pyproj.Geod WGS84 ellipsoidal geodesic':'WGS 84 椭球测地线计算（pyproj.Geod）'};
const assumptionLabels={'Source-declared candidate longitude/latitude; original CAD CRS UNKNOWN; not field verified.':'采用来源提供的候选经纬度；原始 CAD 坐标参考未知，尚未经现场核实。'};
const unitNames={area:'面积',length:'长度',perimeter:'周长',depth:'深度',volume:'体积'},unitSymbols={m2:'m²',m3:'m³',m:'m'};
const measurementFields=new Set(['area_m2','perimeter_m','length_m','depth','depth_m','volume_m3']);
const knownText=(labels,value)=>typeof value==='string'&&Object.hasOwn(labels,value)?labels[value]:formatValue(value);
function detailValue(key,value){
  if(measurementFields.has(key)&&typeof value==='number'&&Number.isFinite(value))return value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(['position_status','registration_status','original_cad_crs_status'].includes(key))return knownText(positionLabels,value);
  if(key==='method')return knownText(methodLabels,value);
  if(key==='assumptions')return knownText(assumptionLabels,value);
  if(key==='units'&&value&&typeof value==='object'&&!Array.isArray(value))return Object.entries(value).map(([name,unit])=>`${knownText(unitNames,name)} ${knownText(unitSymbols,unit)}`).join(' · ')||formatValue(value);
  if(key==='position_basis'&&value==='No verified device location supplied')return '未提供经过核实的设备位置';
  return formatValue(value);
}
function detailValueMarkup(key,value){const raw=formatValue(value),display=detailValue(key,value);return `<dd${display!==raw?` title="原始值：${esc(raw)}"`:''}>${esc(display)}</dd>`;}
export function featureDetailMarkup(feature,quality={}){
  const attributes=feature.attributes||{},measurements=attributes.computed_measurements||{},hasDepth=Object.keys({...attributes,...measurements}).some(k=>/depth|水深|深度/.test(k));
  const originalNature=feature.nature||'imported_unverified',labelledNature=originalNature==='cad_candidate_unverified'?'CAD 候选资料 · 未核验':originalNature==='source_declared_unverified'?'来源声明 · 未核验':natureLabel(originalNature),nature=typeof labelledNature==='string'?labelledNature:formatValue(originalNature);
  const anomalies=(Array.isArray(quality?.anomalous_lengths)?quality.anomalous_lengths:[]).filter(row=>row?.iri===feature.iri);
  const excluded=attributes.exclude_from_initial_fit===true||(Array.isArray(quality?.initial_fit_exclusions)&&quality.initial_fit_exclusions.includes(feature.iri))||anomalies.some(row=>row.action==='retained_excluded_from_initial_fit');
  const metres=value=>value===null||value===undefined?'未提供':esc(formatValue(value))+' m';
  const warning=anomalies.length||excluded?`<div class="map-warning spatial-quality-warning" role="note"><strong>${anomalies.length?'来源标记：异常长度':'来源质量标记'}</strong>${anomalies.map(row=>`<p>来源记录长度：${metres(row.length_m)}；来源判定阈值：${metres(row.threshold_m)}。</p>${row.reason?`<p>来源原因：${esc(formatValue(row.reason))}</p>`:''}${row.action&&row.action!=='retained_excluded_from_initial_fit'?`<p>来源处置：${esc(row.action)}</p>`:''}`).join('')}${!anomalies.length?'<p>来源判定原因与阈值未提供。</p>':''}<p>${excluded?'已排除初始视野拟合，避免异常跨度缩小主图；':''}原几何保留，可通过对应图层查看并核对来源。</p></div>`:'';
  const rows=Object.entries({...measurements,...attributes}).filter(([key])=>!['computed_measurements','area_memberships','memberships','spatial_memberships','exclude_from_initial_fit'].includes(key));
  return `<div class="eyebrow">${esc(names[feature.kind]||'空间对象')}</div><h3>${esc(feature.label||feature.id)}</h3><div class="object-meta"><span class="badge blue" title="原始值：${esc(originalNature)}">${esc(nature)}</span><span class="badge amber">${feature.geometry?'候选位置 · 待核实':'待定位 · 无坐标'}</span></div>${warning}<dl class="source-list"><dt>位置依据</dt>${detailValueMarkup('position_status',feature.position_status||'来源未提供')}${feature.kind==='camera'?'<dt>设备身份</dt><dd>CAD 图标位置候选；未绑定正式设备，未提供在线状态或视频入口。</dd>':''}${feature.kind==='facility'?'<dt>锚点含义</dt><dd>图纸文字锚点，不代表设施实物插入点。</dd>':''}${rows.slice(0,18).map(([key,value])=>`<dt>${esc(attributeNames[key]||key)}</dt>${detailValueMarkup(key,value)}`).join('')}${!hasDepth?'<dt>水深 / 深度</dt><dd>未提供</dd>':''}</dl><p class="panel-note">几何测量为候选坐标上的派生计算，不能作为现场实测或正式业务归属。测量数值按两位小数显示，原始精度可在下方展开查看。</p><details class="spatial-evidence"><summary>查看原始属性与完整精度</summary><pre class="mono">${esc(JSON.stringify({nature:feature.nature,position_status:feature.position_status,attributes},null,2))}</pre></details><details class="spatial-evidence"><summary>查看公开来源证据</summary><pre class="mono">${esc(JSON.stringify(feature.source_refs||[],null,2))}</pre></details>`;
}

export function mountSpatialMap(container,data,{onSelect=()=>{},onLegacy=()=>{},releaseId='',selectedIri:initialIri=null}={}){
  const model=prepareSpatialMap(data),session=createViewSession(releaseId);
  let selectedIri=null,drag=null,box=null,initial=null,width=800,height=580,directoryPage=1,directoryMode='all';
  const bounds=model.bounds;
  if(!bounds){
    const initial=model.objects.get(initialIri),detail=initial?`<section class="panel"><div class="panel-body">${featureDetailMarkup(initial,data.quality)}<button class="primary-action" data-unlocated-open="${esc(initial.iri)}">打开本体属性与关系 →</button></div></section>`:'';
    container.innerHTML='<section class="empty-state"><h2>当前发布没有可定位的地图要素</h2><p>来源未提供可用坐标。待定位对象仍可从下方目录进入本体详情。</p></section>'+detail+'<section class="panel"><div class="panel-heading"><h2>待定位对象</h2></div><div class="panel-body">'+model.unlocated.slice(0,24).map(f=>`<button class="map-feature-button" data-unlocated-open="${esc(f.iri)}"><span>${esc(f.label||f.id)}</span><span>查看本体 →</span></button>`).join('')+`<p class="panel-note">显示 ${Math.min(24,model.unlocated.length)} / ${model.unlocated.length} 个对象；完整分类可从本体目录逐级查看。</p></div></section>`;
    session.listen(container,'click',event=>{const button=event.target.closest('[data-unlocated-open]'),f=model.objects.get(button?.dataset.unlocatedOpen);if(f?.class_iri)onSelect({iri:f.iri,class:f.class_iri});});
    return {destroy:()=>session.destroy()};
  }
  const center=[(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2],longitudeScale=111320*Math.cos(center[1]*Math.PI/180);
  const project=([x,y])=>[(x-center[0])*longitudeScale,-(y-center[1])*111320];
  const kinds=[...new Set(model.display.map(f=>f.kind))];
  const layers=(data.layers||[]).length?data.layers:kinds.map(kind=>({id:kind,label:names[kind]||kind,visible:!['road','canal'].includes(kind)}));
  const visibility=new Map(layers.map(layer=>[layer.id,layer.visible!==false]));
  const layerId=f=>f.layer_id||f.kind;
  const featureByIndex=index=>model.display[Number(index)];
  const getLabel=f=>model.objects.get(f.object_iris?.[0])?.label||f.label||f.id;
  const polygonCount=[...model.objects.values()].filter(f=>['field','pond'].includes(f.kind)&&['Polygon','MultiPolygon'].includes(f.geometry?.type)).length;
  const anchorCount=[...model.objects.values()].filter(f=>f.kind==='facility'&&f.geometry?.type==='Point').length;
  const cameraCount=[...model.objects.values()].filter(f=>f.kind==='camera'&&f.geometry?.type==='Point').length;
  container.innerHTML=`<div class="spatial-summary"><span><strong>${polygonCount}</strong>田塘对象</span><span><strong>${anchorCount}</strong>设施文字锚点</span><span><strong>${cameraCount}</strong>摄像头候选</span><span><strong>${model.unlocated.length}</strong>待定位对象</span><button class="text-button" data-spatial="legacy">查看历史图纸 →</button></div><div class="map-warning spatial-warning">候选规划位置 · 原始 CAD 坐标参考仍为 UNKNOWN。地图沿用来源转换的经纬度；候选点、文字锚点与合成设备均未核实为正式资产。</div><div class="viz-controls spatial-layers" role="group" aria-label="地图图层">${layers.map(layer=>`<label><input type="checkbox" data-layer="${esc(layer.id)}" ${visibility.get(layer.id)?'checked':''}><i class="layer-dot ${esc(kinds.find(kind=>kind===layer.id)||'field')}"></i>${esc(layer.label)}</label>`).join('')}<label class="spatial-label-toggle"><input type="checkbox" data-labels>名称</label></div><div class="spatial-layout"><section class="spatial-stage"><div class="spatial-stage-heading"><span>梁子湖 / CAD 平面</span><span class="spatial-coordinate">候选 WGS 84 · Z = 0</span></div><svg class="spatial-canvas" tabindex="0" role="img" aria-label="梁子湖候选平面地图，可拖动平移、滚轮缩放，选择田塘与点位"><defs><pattern id="spatial-grid" width="100" height="100" patternUnits="userSpaceOnUse"><path d="M100 0H0V100" fill="none" stroke="#a6bba1" stroke-width=".7" opacity=".16"/></pattern></defs><g class="spatial-features">${model.display.map((f,index)=>{const common=`class="spatial-feature ${esc(f.kind)} ${f.conflict?'conflict':''}" data-spatial-index="${index}" tabindex="0" role="button" aria-label="${esc(getLabel(f))}"`;if(f.geometry.type==='Point'){const p=project(f.geometry.coordinates);return `<circle ${common} cx="${p[0]}" cy="${p[1]}" r="5"><title>${esc(getLabel(f))}</title></circle>`;}return `<path ${common} d="${geometryPath(f.geometry,project)}" fill-rule="evenodd"><title>${esc(getLabel(f))}${f.conflict?' · 多对象重叠面片':''}</title></path>`;}).join('')}</g><g class="spatial-names" pointer-events="none" hidden>${model.display.map((f,index)=>{const pp=points(f.geometry).map(project),p=pp.reduce((s,p)=>[s[0]+p[0]/pp.length,s[1]+p[1]/pp.length],[0,0]);return `<text data-spatial-label="${index}" x="${p[0]}" y="${p[1]}">${esc(getLabel(f))}</text>`;}).join('')}</g></svg><div class="viz-zoom"><button data-spatial="in" aria-label="放大地图">+</button><button data-spatial="out" aria-label="缩小地图">−</button><button data-spatial="fit" aria-label="显示全部有效对象">⤢</button></div><div class="spatial-north" aria-label="北方朝上"><span>N</span>↑</div><div class="spatial-scale"><i></i><span></span></div><div class="spatial-stage-foot"><span>拖动平移 · 滚轮缩放 · 选择对象</span><span>面片只绘制一次</span></div></section><aside class="spatial-detail panel"><div class="panel-heading"><h2>图中对象</h2><span class="badge">候选资料</span></div><div class="panel-body spatial-selection" aria-live="polite"><div class="spatial-empty-icon">⌖</div><h3>选择一个区域或点位</h3><p class="section-intro">查看尺寸、位置依据、范围内对象与来源，再沿本体关系继续追溯。</p><div class="spatial-legend"><span><i class="layer-dot field"></i>图纸田块</span><span><i class="layer-dot pond"></i>塘口候选</span><span><i class="layer-dot facility"></i>文字锚点</span><span><i class="layer-dot camera"></i>摄像头候选</span></div></div></aside></div><section class="panel spatial-directory"><div class="panel-heading"><h2>空间对象目录</h2><label><input type="checkbox" data-unlocated-only> 只看待定位（${model.unlocated.length}）</label></div><div class="panel-body"><p class="panel-note">无坐标对象保留在目录中；合成设备不会被放置到塘口中心或摄像头候选点。</p><div class="spatial-directory-list"></div><div class="spatial-pagination pagination"></div></div></section>`;
  const find=selector=>container.querySelector(selector),svg=find('svg'),shapes=[...container.querySelectorAll('[data-spatial-index]')],labels=[...container.querySelectorAll('[data-spatial-label]')];
  function renderDirectory(){const rows=directoryMode==='unlocated'?model.unlocated:[...model.objects.values()],pages=Math.max(1,Math.ceil(rows.length/16));directoryPage=Math.max(1,Math.min(directoryPage,pages));find('.spatial-directory-list').innerHTML=rows.slice((directoryPage-1)*16,directoryPage*16).map(f=>`<button data-object="${esc(f.iri)}" class="spatial-object-row"><i class="layer-dot ${esc(f.kind)}"></i><span>${esc(f.label||f.id)}<small>${esc(names[f.kind]||f.kind)} · ${points(f.geometry).length?'候选位置':'待定位'}${f.nature==='synthetic'?' · 合成数据':''}</small></span><span>→</span></button>`).join('')||'<p class="data-empty">当前目录没有对象。</p>';find('.spatial-pagination').innerHTML=`<button data-directory-page="${directoryPage-1}" ${directoryPage===1?'disabled':''}>← 上一页</button><span>${directoryPage} / ${pages} · ${rows.length} 个对象</span><button data-directory-page="${directoryPage+1}" ${directoryPage===pages?'disabled':''}>下一页 →</button>`;}
  function memberships(f){return f.area_memberships||f.attributes?.area_memberships||f.attributes?.spatial_memberships||f.attributes?.memberships||[];}
  function relatedIris(f){const result=[];const memberId=m=>typeof m==='string'?m:m.area_iri||m.region_iri||m.object_iri||m.iri||m.target_iri;for(const m of memberships(f)){const id=memberId(m);if(model.objects.has(id))result.push(id);}if(['field','pond','region'].includes(f.kind))for(const other of model.objects.values())if(memberships(other).some(m=>memberId(m)===f.iri))result.push(other.iri);return [...new Set(result)];}
  function selectObject(iri,piece=null){const f=model.objects.get(iri);if(!f)return;selectedIri=iri;const related=relatedIris(f),members=(piece?.object_iris||[]).filter(id=>id!==iri);find('.spatial-selection').innerHTML=featureDetailMarkup(f,data.quality)+`${piece?.conflict?'<p class="map-warning">此面片存在真实重叠，显示一次并保留所有对象归属。</p>':''}${members.length?`<div class="spatial-related"><h4>同一显示面片的对象</h4>${members.map(id=>`<button data-object="${esc(id)}">${esc(model.objects.get(id)?.label||id)} →</button>`).join('')}</div>`:''}<button class="primary-action" data-open-object="${esc(iri)}">打开本体属性与关系 →</button><div class="spatial-related"><h4>派生空间关联 · ${related.length}</h4><p class="panel-note">范围命中不等于正式业务隶属；多重命中保留。</p>${related.slice(0,12).map(id=>`<button data-object="${esc(id)}">${esc(model.objects.get(id)?.label||id)} →</button>`).join('')||'<p class="panel-note">当前发布未提供已解析的空间范围关联。</p>'}${related.length>12?'<p class="panel-note">此处显示前 12 个，完整关系可在本体详情中逐页查看。</p>':''}</div>`;shapes.forEach((shape,i)=>shape.classList.toggle('selected',model.display[i].object_iris.includes(iri)));}
  function selectFeature(index){const f=featureByIndex(index);if(f?.object_iris?.length)selectObject(f.object_iris[0],f);}
  function applyBox(){if(!box)return;svg.setAttribute('viewBox',box.join(' '));svg.dataset.viewport=box.map(n=>n.toFixed(2)).join(',');const scale=box[2]/Math.max(width,1);shapes.forEach((shape,i)=>{if(model.display[i].geometry.type==='Point')shape.setAttribute('r',String(scale*(model.display[i].kind==='camera'?5.5:4.5)));});labels.forEach(label=>label.setAttribute('font-size',String(scale*10)));const desired=scale*90,base=10**Math.floor(Math.log10(desired)),distance=[1,2,5,10].map(n=>n*base).find(n=>n>=desired)||base*10;find('.spatial-scale i').style.width=(distance/scale)+'px';find('.spatial-scale span').textContent=distance>=1000?(distance/1000).toFixed(1)+' km':Math.round(distance)+' m';}
  function fit(){const a=project([bounds[0],bounds[3]]),b=project([bounds[2],bounds[1]]),w=Math.max(10,b[0]-a[0])*1.18,h=Math.max(10,b[1]-a[1])*1.18,ratio=width/height,bw=Math.max(w,h*ratio),bh=Math.max(h,w/ratio);initial=[-bw/2,-bh/2,bw,bh];box=[...initial];applyBox();}
  function resize(){const rect=svg.getBoundingClientRect();width=Math.max(1,rect.width);height=Math.max(1,rect.height);fit();}
  function zoomAt(factor,px=width/2,py=height/2){const ratio=Math.max(.02,Math.min(10,box[2]*factor/initial[2])),next=initial[2]*ratio/box[2];box=[box[0]+box[2]*(1-next)*px/width,box[1]+box[3]*(1-next)*py/height,box[2]*next,box[3]*next];applyBox();}
  function updateLayers(){shapes.forEach((shape,i)=>{shape.style.display=visibility.get(layerId(model.display[i]))===false?'none':'';labels[i].style.display=shape.style.display;});}
  session.listen(svg,'pointerdown',event=>{if(event.button!==0||drag)return;drag={id:event.pointerId,gesture:pointerGesture(event.clientX,event.clientY),feature:event.target.closest('[data-spatial-index]')?.dataset.spatialIndex};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging');});
  session.listen(svg,'pointermove',event=>{if(drag?.id!==event.pointerId)return;const delta=drag.gesture.move(event.clientX,event.clientY);box[0]-=delta.x*box[2]/width;box[1]-=delta.y*box[3]/height;applyBox();});
  session.listen(svg,'pointerup',event=>{if(drag?.id!==event.pointerId)return;drag.gesture.move(event.clientX,event.clientY);const current=drag;drag=null;svg.classList.remove('dragging');if(svg.hasPointerCapture(event.pointerId))svg.releasePointerCapture(event.pointerId);if(current.gesture.isClick()&&current.feature!==undefined)selectFeature(current.feature);});
  const cancel=()=>{drag=null;svg.classList.remove('dragging');};session.listen(svg,'pointercancel',cancel);session.listen(svg,'lostpointercapture',cancel);
  session.listen(svg,'wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect();zoomAt(Math.exp(event.deltaY*.001),event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
  session.listen(svg,'keydown',event=>{const shape=event.target.closest('[data-spatial-index]');if(shape&&['Enter',' '].includes(event.key)){event.preventDefault();selectFeature(shape.dataset.spatialIndex);}else if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();if(['+','='].includes(event.key))zoomAt(.8);else if(event.key==='-')zoomAt(1.25);else if(event.key==='0')fit();else{if(event.key==='ArrowLeft')box[0]-=box[2]*.08;if(event.key==='ArrowRight')box[0]+=box[2]*.08;if(event.key==='ArrowUp')box[1]-=box[3]*.08;if(event.key==='ArrowDown')box[1]+=box[3]*.08;applyBox();}}});
  session.listen(container,'click',event=>{const target=event.target.closest('button');if(!target)return;const d=target.dataset;if(d.object)selectObject(d.object);if(d.openObject){const f=model.objects.get(d.openObject);if(f?.iri&&f.class_iri)onSelect({iri:f.iri,class:f.class_iri});}if(d.directoryPage){directoryPage=Number(d.directoryPage);renderDirectory();}if(d.spatial==='legacy')onLegacy(data.legacy_map_path);if(d.spatial==='fit')fit();if(d.spatial==='in')zoomAt(.8);if(d.spatial==='out')zoomAt(1.25);});
  session.listen(container,'change',event=>{const d=event.target.dataset;if(d.layer){visibility.set(d.layer,event.target.checked);updateLayers();}if(d.labels!==undefined)find('.spatial-names').toggleAttribute('hidden',!event.target.checked);if(d.unlocatedOnly!==undefined){directoryMode=event.target.checked?'unlocated':'all';directoryPage=1;renderDirectory();}});
  if(globalThis.ResizeObserver){const observer=new ResizeObserver(resize);observer.observe(svg);session.cleanup(()=>observer.disconnect());}else session.listen(globalThis,'resize',resize);
  if(initialIri&&model.objects.has(initialIri)){
    const unlocatedIndex=model.unlocated.findIndex(f=>f.iri===initialIri);
    if(unlocatedIndex>=0){directoryMode='unlocated';directoryPage=Math.floor(unlocatedIndex/16)+1;find('[data-unlocated-only]').checked=true;}
    else{directoryPage=Math.floor([...model.objects.keys()].indexOf(initialIri)/16)+1;for(const feature of model.display.filter(f=>f.object_iris.includes(initialIri)))visibility.set(layerId(feature),true);for(const input of container.querySelectorAll('[data-layer]'))input.checked=visibility.get(input.dataset.layer)!==false;}
    selectObject(initialIri);
  }
  session.cleanup(cancel);renderDirectory();updateLayers();resize();return {destroy:()=>session.destroy()};
}

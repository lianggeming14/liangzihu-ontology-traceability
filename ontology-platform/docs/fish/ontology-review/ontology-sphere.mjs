import {spherePoints,rotatePoint,projectPoint,clampZoom,pointerGesture,pickTarget} from './sphere-math.mjs';

const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count=value=>Number(value||0).toLocaleString('zh-CN');
export function prepareNetwork(data){
  if(data?.contract!=='lzo-ontology-network/1'||!Array.isArray(data.nodes)||!Array.isArray(data.edges))throw Error('本体关系网络格式不匹配');
  const byId=new Map();
  for(const node of data.nodes){if(typeof node.iri!=='string'||byId.has(node.iri))throw Error('本体网络节点身份缺失或重复');byId.set(node.iri,node);}
  const edges=data.edges.filter(edge=>byId.has(edge.source)&&byId.has(edge.target)&&typeof edge.predicate==='string');
  return {nodes:data.nodes,edges,byId,counts:data.counts||{},omitted:data.edges.length-edges.length};
}
export function filterNetwork(network,{role='',predicate='',kind='',query=''}={}){
  const term=query.trim().toLocaleLowerCase();
  const nodes=network.nodes.filter(node=>(!role||node.role===role)&&(!term||`${node.label} ${node.iri}`.toLocaleLowerCase().includes(term)));
  const ids=new Set(nodes.map(node=>node.iri));
  return {nodes,edges:network.edges.filter(edge=>ids.has(edge.source)&&ids.has(edge.target)&&(!predicate||edge.predicate===predicate)&&(!kind||edge.kind===kind))};
}
// One owner per mounted view: listeners, redraw and in-flight selections are invalidated together.
export function createViewSession(releaseId,currentRelease=()=>releaseId,frame=globalThis){
  let alive=true,raf=null,sequence=0;const cleanups=[];
  const current=()=>alive&&currentRelease()===releaseId;
  return {
    current,
    listen(target,type,listener,options){const guarded=event=>{if(current())listener(event);};target.addEventListener(type,guarded,options);cleanups.push(()=>target.removeEventListener(type,guarded,options));},
    cleanup(fn){cleanups.push(fn);},
    schedule(draw){if(!current()||raf!==null)return;raf=frame.requestAnimationFrame(()=>{raf=null;if(current())draw();});},
    async load(read,apply){const token=++sequence;let result;try{result=await read();}catch(error){if(!current()||token!==sequence)return false;throw error;}if(!current()||token!==sequence)return false;if(releaseId&&result?.release_id&&result.release_id!==releaseId)throw Error('响应版本与当前发布不一致');apply(result);return true;},
    destroy(){if(!alive)return;alive=false;sequence++;if(raf!==null)frame.cancelAnimationFrame(raf);raf=null;cleanups.splice(0).forEach(fn=>fn());},
  };
}

const palette=['#c4df91','#84cac4','#d7b578','#a8bddc','#d5a5b1','#91bca0'];
const colorFor=node=>{let n=0;for(const c of String(node.role||node.parent_iri||node.iri))n=(n*31+c.charCodeAt(0))>>>0;return palette[n%palette.length];};
export function mountOntologySphere(container,data,{onSelectClass=()=>{},onSelectEdge=()=>{},releaseId=''}={}){
  const network=prepareNetwork(data),session=createViewSession(releaseId),doc=container.ownerDocument;
  let filtered=filterNetwork(network),yaw=-.35,pitch=.12,zoom=1,selected=null,selectedEdge=null,hover=null,drag=null,width=700,height=570,projected=[],projectedEdges=[],page=1,relationPage=1;
  const points=spherePoints(network.nodes.length),positions=new Map(network.nodes.map((node,i)=>[node.iri,points[i]]));
  const roles=[...new Set(network.nodes.map(n=>n.role).filter(Boolean))],predicates=[...new Map(network.edges.map(e=>[e.predicate,e.label||e.predicate.split(/[#:/]/).at(-1)])).entries()];
  container.innerHTML=`<div class="viz-controls"><label class="viz-search"><span>⌕</span><input type="search" data-filter="query" placeholder="查找本体类型" aria-label="查找本体类型"></label><select data-filter="role" aria-label="筛选类别"><option value="">全部类别</option>${roles.map(role=>`<option value="${esc(role)}">${esc(role)}</option>`).join('')}</select><select data-filter="predicate" aria-label="筛选关系谓词"><option value="">全部关系谓词</option>${predicates.map(([iri,label])=>`<option value="${esc(iri)}">${esc(label)}</option>`).join('')}</select><select data-filter="kind" aria-label="筛选关系来源"><option value="">全部关系来源</option><option value="schema">本体定义</option><option value="observed">实例聚合</option></select></div><div class="sphere-layout"><section class="sphere-stage" aria-label="可旋转的本体关系球"><div class="sphere-stage-title"><span class="status-light"></span><span>本体关系 / 3D 布局</span><span class="sphere-visible-count"></span></div><canvas class="sphere-canvas" tabindex="0" aria-label="本体关系球。拖动旋转、滚轮缩放；方向键旋转，加减键缩放。下方目录可用键盘选择。"></canvas><div class="viz-zoom"><button type="button" data-sphere="in" aria-label="放大关系球">+</button><button type="button" data-sphere="out" aria-label="缩小关系球">−</button><button type="button" data-sphere="reset" aria-label="重置关系球">⤢</button></div><div class="sphere-stage-foot"><span>拖动旋转 · 滚轮缩放 · 点击查看</span><span><i class="edge-key schema"></i>本体定义 <i class="edge-key observed"></i>实例聚合</span></div><div class="sphere-tooltip" hidden></div></section><aside class="sphere-detail panel"><div class="panel-heading"><h2>关系导航</h2><span class="badge">按需展开</span></div><div class="panel-body sphere-selection" aria-live="polite"></div></aside></div><div class="network-counts"></div><section class="panel sphere-directory"><div class="panel-heading"><h2>本体类型目录</h2><span class="muted">与球上节点一致 · 每页 24 个</span></div><div class="panel-body"><div class="sphere-node-list"></div><div class="sphere-list-pagination pagination"></div></div></section>`;
  const find=selector=>container.querySelector(selector),canvas=find('canvas'),ctx=canvas.getContext('2d'),tooltip=find('.sphere-tooltip');
  if(!ctx){session.destroy();container.textContent='当前浏览器未提供 Canvas 绘图能力，请从本体目录继续浏览。';return {destroy(){}};}
  function paintDirectory(){
    const pages=Math.max(1,Math.ceil(filtered.nodes.length/24));page=Math.max(1,Math.min(pages,page));
    find('.sphere-node-list').innerHTML=filtered.nodes.slice((page-1)*24,page*24).map(node=>`<button class="sphere-node-button ${selected===node.iri?'selected':''}" data-node="${esc(node.iri)}"><i style="background:${colorFor(node)}"></i><span>${esc(node.label||node.iri)}</span><small>${count(node.total_instance_count??node.instance_count)}</small></button>`).join('')||'<p class="data-empty">当前筛选没有匹配的本体。</p>';
    find('.sphere-list-pagination').innerHTML=`<button data-list-page="${page-1}" ${page===1?'disabled':''}>← 上一页</button><span>${page} / ${pages} · ${count(filtered.nodes.length)} 个类型</span><button data-list-page="${page+1}" ${page===pages?'disabled':''}>下一页 →</button>`;
  }
  function paintSelection(){
    const target=find('.sphere-selection');
    if(selectedEdge){const edge=selectedEdge;target.innerHTML=`<div class="eyebrow">${edge.kind==='schema'?'ONTOLOGY DEFINITION':'OBSERVED RELATION'}</div><h3>${esc(edge.label||edge.predicate)}</h3><p class="sphere-direction">${esc(network.byId.get(edge.source)?.label)} <strong>→</strong> ${esc(network.byId.get(edge.target)?.label)}</p><dl class="source-list"><dt>谓词</dt><dd class="mono">${esc(edge.predicate)}</dd><dt>关系来源</dt><dd>${edge.kind==='schema'?'本体结构 / 对象属性定义':'已发布实例关系聚合'}</dd><dt>${edge.kind==='schema'?'定义数量':'唯一三元组数'}</dt><dd>${count(edge.count)}</dd><dt>方向</dt><dd>来源本体 → 目标本体</dd></dl><button class="primary-action" data-open-edge>查看${edge.kind==='schema'?'定义端点':'实例关系'} →</button><div class="network-edge-results"></div>`;return;}
    const node=network.byId.get(selected);
    if(!node){target.innerHTML='<div class="sphere-empty-icon">◉</div><h3>从一个本体开始</h3><p class="section-intro">选择球上的节点，查看类型、实例数量与相连关系。再进入下一级或逐页查看实例。</p><p class="panel-note">球面只表达关系布局，不代表地理位置。每条边均来自当前发布的本体定义或已解析实例关系。</p>';return;}
    const neighbors=filtered.edges.filter(e=>e.source===selected||e.target===selected),pages=Math.max(1,Math.ceil(neighbors.length/8));relationPage=Math.min(pages,relationPage);
    target.innerHTML=`<div class="eyebrow">ONTOLOGY CLASS</div><h3>${esc(node.label||node.iri)}</h3><div class="sphere-node-stat"><strong>${count(node.total_instance_count??node.instance_count)}</strong><span>实例（含下级）</span></div><p class="mono muted">${esc(node.iri)}</p><button class="primary-action" data-open-class>进入下级与实例 →</button><h4 class="sphere-neighbor-title">相连关系 <span>${count(neighbors.length)}</span></h4><div class="sphere-neighbors">${neighbors.slice((relationPage-1)*8,relationPage*8).map(edge=>{const outgoing=edge.source===selected,target=network.byId.get(outgoing?edge.target:edge.source);return `<button data-edge="${esc(edge.id)}"><small>${outgoing?'出向 →':'入向 ←'} ${esc(edge.label||edge.predicate)} · ${count(edge.count)}</small><span>${esc(target?.label||target?.iri)}</span></button>`;}).join('')||'<p class="data-empty">当前筛选没有相连关系。</p>'}</div>${pages>1?`<div class="pagination"><button data-neighbor-page="${relationPage-1}" ${relationPage===1?'disabled':''}>←</button><span>${relationPage}/${pages}</span><button data-neighbor-page="${relationPage+1}" ${relationPage===pages?'disabled':''}>→</button></div>`:''}`;
  }
  function selectNode(iri){selected=iri;selectedEdge=null;relationPage=1;paintSelection();paintDirectory();requestDraw();}
  function selectEdge(edge){selectedEdge=edge;selected=null;paintSelection();paintDirectory();requestDraw();}
  function draw(){
    const dpr=Math.min(3,globalThis.devicePixelRatio||1);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    const radius=Math.min(width,height)*.4*zoom,glow=ctx.createRadialGradient(width/2,height/2,0,width/2,height/2,radius*1.2);
    glow.addColorStop(0,'rgba(108,154,116,.16)');glow.addColorStop(.75,'rgba(74,126,103,.10)');glow.addColorStop(1,'rgba(20,48,41,0)');ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);
    ctx.strokeStyle='rgba(174,206,173,.12)';ctx.lineWidth=1;ctx.beginPath();ctx.arc(width/2,height/2,radius,0,Math.PI*2);ctx.stroke();
    projected=filtered.nodes.map(node=>{const p=projectPoint(rotatePoint(positions.get(node.iri),yaw,pitch),{width,height,zoom});return {...p,node,id:node.iri,radius:(2.9+Math.min(2.8,Math.log10(1+(node.instance_count||0))*.55))*p.scale};}).sort((a,b)=>a.depth-b.depth);
    const byId=new Map(projected.map(p=>[p.id,p])),connected=new Set(selected?[selected]:[]);
    if(selected)filtered.edges.filter(e=>e.source===selected||e.target===selected).forEach(e=>{connected.add(e.source);connected.add(e.target);});
    projectedEdges=filtered.edges.map(edge=>{const a=byId.get(edge.source),b=byId.get(edge.target);return {edge,id:edge.id,a,b,...(edge.source===edge.target?{loop:{x:a.x,y:a.y-a.radius-8,radius:a.radius+8}}:{})};}).sort((a,b)=>(a.a.depth+a.b.depth)-(b.a.depth+b.b.depth));
    for(const path of projectedEdges){
      const {edge,a,b}=path,active=selectedEdge?.id===edge.id||selected&&(edge.source===selected||edge.target===selected),dim=(selected||selectedEdge)&&!active,depth=(a.depth+b.depth+2)/4;
      ctx.globalAlpha=dim?.035:active?.88:.10+depth*.20;ctx.strokeStyle=active?'#e5d18c':edge.kind==='schema'?'#82b9b8':'#b9d78d';ctx.lineWidth=active?1.7:edge.kind==='schema'?.8:.65;ctx.setLineDash(edge.kind==='schema'?[3,3]:[]);ctx.beginPath();if(path.loop)ctx.arc(path.loop.x,path.loop.y,path.loop.radius,0,Math.PI*2);else{ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);}ctx.stroke();ctx.setLineDash([]);
      if(active&&Math.hypot(b.x-a.x,b.y-a.y)>25){const angle=Math.atan2(b.y-a.y,b.x-a.x),x=b.x-Math.cos(angle)*(b.radius+5),y=b.y-Math.sin(angle)*(b.radius+5);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-7*Math.cos(angle-.5),y-7*Math.sin(angle-.5));ctx.moveTo(x,y);ctx.lineTo(x-7*Math.cos(angle+.5),y-7*Math.sin(angle+.5));ctx.stroke();}
    }
    for(const p of projected){
      const active=p.id===selected||p.id===hover,dim=selected&&!connected.has(p.id);ctx.globalAlpha=dim?.22:.45+(p.depth+1)*.275;
      if(active){ctx.fillStyle='rgba(232,214,146,.15)';ctx.beginPath();ctx.arc(p.x,p.y,p.radius+8,0,Math.PI*2);ctx.fill();}
      ctx.fillStyle=active?'#f3dfa0':colorFor(p.node);ctx.beginPath();ctx.arc(p.x,p.y,p.radius,0,Math.PI*2);ctx.fill();
      if(active||selected&&connected.has(p.id)||(!selected&&!selectedEdge&&p.depth>.72)){
        ctx.globalAlpha=active?1:.88;ctx.font=`${active?'600 ':''}${active?12:10}px "Microsoft YaHei",sans-serif`;ctx.textAlign='center';const label=p.node.label||p.id;ctx.lineWidth=4;ctx.strokeStyle='#15372f';ctx.strokeText(label,p.x,p.y-p.radius-7);ctx.fillStyle=active?'#fff2c9':'#d4e3cd';ctx.fillText(label,p.x,p.y-p.radius-7);
      }
    }
    ctx.globalAlpha=1;canvas.dataset.rotation=`${yaw.toFixed(3)},${pitch.toFixed(3)}`;canvas.dataset.zoom=zoom.toFixed(3);
  }
  function requestDraw(){session.schedule(draw);}
  function resize(){const rect=canvas.getBoundingClientRect();width=Math.max(1,rect.width);height=Math.max(1,rect.height);const dpr=Math.min(3,globalThis.devicePixelRatio||1);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);requestDraw();}
  function local(event){const rect=canvas.getBoundingClientRect();return {x:event.clientX-rect.left,y:event.clientY-rect.top};}
  session.listen(canvas,'pointerdown',event=>{if(event.button!==0||drag)return;const p=local(event);drag={id:event.pointerId,gesture:pointerGesture(p.x,p.y)};canvas.setPointerCapture(event.pointerId);canvas.classList.add('dragging');tooltip.hidden=true;});
  session.listen(canvas,'pointermove',event=>{const p=local(event);if(drag?.id===event.pointerId){const d=drag.gesture.move(p.x,p.y);yaw+=d.x*.007;pitch+=d.y*.007;requestDraw();return;}const picked=pickTarget(p.x,p.y,projected,[]);hover=picked?.item.id||null;tooltip.hidden=!picked;if(picked){tooltip.textContent=`${picked.item.node.label} · ${count(picked.item.node.total_instance_count??picked.item.node.instance_count)} 个实例`;tooltip.style.left=Math.min(width-190,Math.max(10,p.x+12))+'px';tooltip.style.top=Math.max(42,p.y-35)+'px';}requestDraw();});
  session.listen(canvas,'pointerup',event=>{if(drag?.id!==event.pointerId)return;const p=local(event);drag.gesture.move(p.x,p.y);const click=drag.gesture.isClick();drag=null;canvas.classList.remove('dragging');if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);if(click){const picked=pickTarget(p.x,p.y,projected,projectedEdges);if(picked?.kind==='node')selectNode(picked.item.id);else if(picked?.kind==='edge')selectEdge(picked.item.edge);}});
  const cancelDrag=()=>{drag=null;canvas.classList.remove('dragging');};session.listen(canvas,'pointercancel',cancelDrag);session.listen(canvas,'lostpointercapture',cancelDrag);
  session.listen(canvas,'pointerleave',()=>{if(!drag){hover=null;tooltip.hidden=true;requestDraw();}});
  session.listen(canvas,'wheel',event=>{event.preventDefault();zoom=clampZoom(zoom*Math.exp(-event.deltaY*.001));requestDraw();},{passive:false});
  session.listen(canvas,'keydown',event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','0'].includes(event.key)){event.preventDefault();if(event.key==='ArrowLeft')yaw-=.12;if(event.key==='ArrowRight')yaw+=.12;if(event.key==='ArrowUp')pitch-=.12;if(event.key==='ArrowDown')pitch+=.12;if(['+','='].includes(event.key))zoom=clampZoom(zoom*1.15);if(event.key==='-')zoom=clampZoom(zoom/1.15);if(event.key==='0'){zoom=1;yaw=-.35;pitch=.12;}requestDraw();}});
  session.listen(container,'click',event=>{const button=event.target.closest('button');if(!button||!container.contains(button))return;const d=button.dataset;if(d.node)selectNode(d.node);if(d.edge)selectEdge(network.edges.find(e=>e.id===d.edge));if(d.openClass!==undefined&&selected)onSelectClass(selected);if(d.openEdge!==undefined&&selectedEdge)onSelectEdge(selectedEdge);if(d.listPage){page=Number(d.listPage);paintDirectory();}if(d.neighborPage){relationPage=Number(d.neighborPage);paintSelection();}if(d.sphere){if(d.sphere==='reset'){yaw=-.35;pitch=.12;zoom=1;}else zoom=clampZoom(zoom*(d.sphere==='in'?1.15:1/1.15));requestDraw();}});
  function filter(){const options=Object.fromEntries([...container.querySelectorAll('[data-filter]')].map(input=>[input.dataset.filter,input.value]));filtered=filterNetwork(network,options);if(!filtered.nodes.some(n=>n.iri===selected))selected=null;selectedEdge=null;page=1;relationPage=1;find('.sphere-visible-count').textContent=`${count(filtered.nodes.length)} 节点 / ${count(filtered.edges.length)} 边`;paintDirectory();paintSelection();requestDraw();}
  for(const input of container.querySelectorAll('[data-filter]'))session.listen(input,input.tagName==='INPUT'?'input':'change',filter);
  const counts=network.counts;find('.network-counts').innerHTML=[['公开本体',counts.classes??network.nodes.length],['实例',counts.instances],['唯一三元组',counts.unique_triple_count],['关系记录',counts.unique_record_count],['未解析',counts.unresolved_count]].filter(([,n])=>n!==undefined).map(([label,n])=>`<span>${esc(label)} <strong>${count(n)}</strong></span>`).join('')+`<span class="network-release">${releaseId?'发布 '+esc(releaseId):'已发布快照'}</span>`;
  if(globalThis.ResizeObserver){const observer=new ResizeObserver(resize);observer.observe(canvas);session.cleanup(()=>observer.disconnect());}else session.listen(globalThis,'resize',resize);
  session.cleanup(()=>{drag=null;tooltip.hidden=true;});filter();resize();
  return {destroy(){session.destroy();}};
}

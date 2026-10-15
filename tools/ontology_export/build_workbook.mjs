import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=path.resolve(import.meta.dirname,'../..');
const out=path.join(root,'outputs/liangzihu-ontology-20261015');
const data=JSON.parse(await fs.readFile(path.join(out,'workbook_data.json'),'utf8'));
const schema=JSON.parse(await fs.readFile(path.join(out,'schema_catalog.json'),'utf8'));
const wb=Workbook.create();
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;};
const navy='#173F45',teal='#267A76',light='#E8F2EF',amber='#FFF2CC',muted='#56706F';
const guide=wb.worksheets.add('使用说明');guide.showGridLines=false;guide.tabColor=teal;
guide.getRange('A1:C24').format.font={name:'Arial',size:11,color:'#203B3D'};
guide.getRange('A1:C1').merge();guide.getRange('A1').values=[['梁子湖项目｜本体结构导出与接入准备']];guide.getRange('A1:C1').format.fill=navy;guide.getRange('A1:C1').format.font={bold:true,size:19,color:'#FFFFFF'};guide.getRange('A1:C1').format.rowHeight=42;
guide.getRange('A2:C2').merge();guide.getRange('A2').values=[['源码结构映射草案 · 2026-10-15 · 不含生产实例 · 未导入现有数据库']];guide.getRange('A2:C2').format.fill=light;guide.getRange('A2:C2').format.rowHeight=30;
const steps=[
['01','覆盖范围','44 份 SQL 迁移；190 张源表；2114 个字段；555 条显式外键；1118 项最终表约束；248 条表结构 DDL 全部解析，未解析或缺引用为 0。'],
['02','数据性质','导出的是源项目数据库结构与本体映射草案，不是项目自带的正式 OWL/RDF 本体，也不是 190 个现场对象。源码、约束和名称可追溯；中文名称与领域分类为本次编制。'],
['03','版本基线','8jdkds7nzz-hub/liangzihu-farm-platform；提交 9995fc20cd84093adcaa3fab954ffe9d08b9f45a。所有来源固定到该提交；不代表此后版本或部署库的实时结构。'],
['04','先看哪几张表','源表清单了解全貌；对象类型看概念边界；属性定义看类与字段；关系类型看明确外键；多维关系路径理解各部分怎样连起来。'],
['05','怎么改、怎么输入','第 1 行是机器列名，请勿改；第 2 行是中文解释；第 3 行起为数据；enabled 填 Excel 原生 TRUE/FALSE（不是文本）。筛选 enabled=TRUE 看默认试接入范围。黄色列供复核修改；技术与安全结构仍在目录中但默认停用。'],
['06','名称与稳定编码','可修改 label 和 description。package_id、type_id、property_id、predicate_id 已批量生成，首次试接入无需自己编写。定义标识在注册后应稳定，改结构需新版本。'],
['07','对象身份','本库创建对象时自动生成 UUID。源数据库 id/code/external_id 用于来源绑定或业务标识，不能填入本库系统主键；建议以“源系统 + 源表 + 原始主键”稳定定位并去重。'],
['08','映射规则','一张来源记录表先映射为一个来源记录类。它不等于最终农业通用概念。例：objects.kind 的 farm/pond/field/channel/facility 是枚举，尚未自动生成继承层次；production_batches.species 不限水稻和小龙虾。'],
['09','关系语义','555 条关系来自显式 FK；方向为引用表 → 被引用表。维度是本次便于查询的分类，不是自动推导的农业因果。桥接包使用精确身份类型端点；跨包语义类校验仍有限制。'],
['10','保留时空和事件','valid_from/to、occurred_at、sampled_at、received_at、recorded_at 等分别保留，不能合并成一个时间。事件/观测来源记录类用于保存外部记录，不会运行模型或控制设备。'],
['11','复杂字段怎么处理','JSON、空间、向量、二进制、UUID 数组及多态引用列已标记待映射。不要简单改 enabled=TRUE；需显式拆字段/证据引用/关系，并保留原文摘要与转换版本。'],
['12','约束边界','原 SQL 必填、唯一、CHECK 和复合键保留在约束及字段元数据中；本体属性默认 required=FALSE 便于逐步接入。注册 JSON 不自动执行全部 SQL 约束，不是数据库迁移文件。'],
['13','导出本体定义','无需修改即可使用随附 packages 内 JSON；修改 Excel 后，将本工作簿拖到 tools/ontology_export/导出本体JSON.cmd，或双击同目录便捷脚本。它只离线校验和生成 JSON，不写现有数据库。'],
['14','实际注册顺序','按照 packages/manifest.json 中的顺序，调用 POST /api/v1/ontology/packages，先领域包后关系桥接包。使用当前部署已有鉴权与管理员权限；Excel 不能直接上传到当前注册表单。'],
['15','真实实例怎么填','试录对象、试录属性、试录关系是空白暂存模板，未放演示数据。先填对象本地引用、源表和原始主键，再填属性与关系；通过原始主键映射返回 UUID。当前转换器只处理结构定义，不批量导入这三张实例表。'],
['16','尚需适配的实例接入','批量实体/属性/关系入口、源主键绑定和复杂字段映射仍需实现并联调。建议先登记类型，再取真实 objects、production_batches、devices、points、point_bindings 数据验证一条链。'],
['17','溯源与证据','source_url 可打开对应源码行；source_path、source_line、提取文本摘要用于复核（GitHub 查看器可能省略文件末尾换行，不是 Git blob 字节摘要）。业务数据接入还须保留来源系统、记录标识、采集时间、原始证据引用、内容摘要和映射版本。'],
['18','不要混用的能力','DDL 提取只证明结构定义存在；不证明现场设备在线、外部 API 可用、图像识别已部署，亦不执行自动决策、灌溉或财务动作。动作字段是事件内容，不是可执行服务授权。'],
['19','验证与复核','随附验证报告检查字段覆盖、引用及领域包注册契约；只在临时 SQLite 验证，无生产连接。PostgreSQL 实库、现场数据、应用层规则和触发器行为仍需专项验收。'],
['20','本次完整性的边界','覆盖固定版本全部 44 份迁移的最终表、字段、显式外键及声明约束；应用层接口、JSON 内部语义、种养知识及无 FK 的隐含关系未声称全量覆盖。README 表数与本次 DDL 表数不一致时以本次源清单为准。']
];
guide.getRange('A4:C23').values=steps;guide.getRange('A4:C23').format.wrapText=true;guide.getRange('A4:C23').format.verticalAlignment='center';guide.getRange('A4:C23').format.rowHeight=88;guide.getRange('A:A').format.columnWidth=8;guide.getRange('B:B').format.columnWidth=24;guide.getRange('C:C').format.columnWidth=110;guide.getRange('A4:B23').format.fill=light;guide.freezePanes.freezeRows(3);
const extras=JSON.parse(await fs.readFile(path.join(out,'extra_sheets.json'),'utf8'));
const priority={对象类型:['enabled','label','source_table','type_id','identity_type','package_id','version','description'],属性定义:['enabled','label','source_table','source_column','value_type','handling','property_id','applies_to'],关系类型:['enabled','label','source_table','target_table','dimension','predicate_id'],领域包:['enabled','label','package_id','version','namespace','description']};
const specs=[...data.sheets,...extras.sheets];
const pick=(name)=>data.sheets.find(s=>s.name===name).rows.filter(r=>r.enabled);
const ts=pick('对象类型'), ps=pick('属性定义'), rs=pick('关系类型');
const choiceRows=Array.from({length:Math.max(ts.length,ps.length,rs.length)},(_,i)=>({type_id:ts[i]?.type_id||null,type_label:ts[i]?.label||null,property_id:ps[i]?.property_id||null,property_class:ps[i]?.applies_to||null,predicate_id:rs[i]?.predicate_id||null,relation_label:rs[i]?.label||null}));
specs.push({name:'填写字典',columns:[{key:'type_id',label:'可用类型标识',width:40},{key:'type_label',label:'类型中文名',width:28},{key:'property_id',label:'可用属性标识',width:52},{key:'property_class',label:'属性适用类',width:48},{key:'predicate_id',label:'可用关系标识',width:65},{key:'relation_label',label:'关系中文名',width:50}],rows:choiceRows});
const review=[];
for(let idx=0;idx<specs.length;idx++){
 const spec=specs[idx]; let columns=spec.columns.map(c=>typeof c==='string'?{key:c,label:c}:c);
 if(spec.name==='源码覆盖')columns.find(c=>c.key==='sha256').label='提取文本SHA256';
 if(spec.name==='约束枚举')columns.find(c=>c.key==='source_columns').label='约束涉及列（JSON数组）';
 const p=priority[spec.name]||[];columns.sort((a,b)=>(p.includes(a.key)?p.indexOf(a.key):100)-(p.includes(b.key)?p.indexOf(b.key):100));
 const sh=wb.worksheets.add(spec.name);sh.showGridLines=false;sh.tabColor=spec.name.startsWith('试录')?'#C58C22':teal;
 const rows=spec.rows.length?spec.rows:Array.from({length:12},()=>({}));
 const matrix=[columns.map(c=>c.key),columns.map(c=>c.label),...rows.map(r=>columns.map(c=>{const v=r[c.key];return typeof v==='object'&&v!==null?JSON.stringify(v):v??null;}))];
 const used=sh.getRange('A1:'+col(columns.length-1)+matrix.length);used.values=matrix;used.format.font={name:'Arial',size:10,color:'#223B3C'};used.format.wrapText=true;used.format.verticalAlignment='center';used.format.rowHeight=60;
 sh.getRange('A1:'+col(columns.length-1)+'1').format.fill=navy;sh.getRange('A1:'+col(columns.length-1)+'1').format.font={name:'Arial',size:9,color:'#FFFFFF'};sh.getRange('A1:'+col(columns.length-1)+'1').format.rowHeight=32;
 const table=sh.tables.add('A2:'+col(columns.length-1)+matrix.length,true,'Catalog'+idx);table.showFilterButton=true;
 sh.getRange('A2:'+col(columns.length-1)+'2').format.fill=teal;sh.getRange('A2:'+col(columns.length-1)+'2').format.font={name:'Arial',size:11,bold:true,color:'#FFFFFF'};sh.getRange('A2:'+col(columns.length-1)+'2').format.rowHeight=36;
 for(let j=0;j<columns.length;j++){
  const k=columns[j].key;const full=sh.getRange(col(j)+':'+col(j));full.format.columnWidth=(k==='enabled'?12:k==='sql'?100:/^(description|notes|boundary|definition|expression|action)$/.test(k)?72:null)||columns[j].width||(/description|notes|boundary|expression|instruction|path_text|evidence_chain/.test(k)?62:/url/.test(k)?65:/label/.test(k)?25:/enabled|required|nullable|primary_key|irreflexive|acyclic|unique/.test(k)?12:27);
  const range=sh.getRange(col(j)+'3:'+col(j)+matrix.length);
  if(spec.name.startsWith('试录')||/(_id|_key|_url|_ref|^version$|^namespace$)/.test(k)) range.setNumberFormat('@');
  if(k==='enabled'||k==='label'||k==='description'||spec.name.startsWith('试录'))range.format.fill=amber;
  if(k==='value_type')range.dataValidation={rule:{type:'list',values:['string','integer','decimal','boolean','enum','datetime']}};
  if(k==='cardinality')range.dataValidation={rule:{type:'list',values:['single','many']}};
  if(k==='usage')range.dataValidation={rule:{type:'list',values:['attribute','observation','assertion']}};
 }
 sh.getRange('A3:'+col(columns.length-1)+matrix.length).format.autofitRows();
 sh.getRange('A3:'+col(columns.length-1)+matrix.length).format.verticalAlignment='top';
 for(let row=3;row<=matrix.length;row++){const rr=sh.getRange('A'+row+':'+col(columns.length-1)+row);const h=rr.format.rowHeight;if(typeof h==='number')rr.format.rowHeight=Math.max(24,h+6);}
 sh.freezePanes.freezeRows(2);sh.freezePanes.freezeColumns(spec.name.startsWith('试录')?1:2);
 review.push({sheet:spec.name,rows:spec.rows.length,columns:columns.length,first_columns:columns.slice(0,6).map(c=>c.key)});
}
wb.worksheets.getItem('试录对象').getRange('E3:E14').dataValidation={rule:{type:'list',formula1:"'填写字典'!$A$3:$A$"+(ts.length+2)}};
wb.worksheets.getItem('试录属性').getRange('B3:B14').dataValidation={rule:{type:'list',formula1:"'填写字典'!$C$3:$C$"+(ps.length+2)}};
wb.worksheets.getItem('试录关系').getRange('B3:B14').dataValidation={rule:{type:'list',formula1:"'填写字典'!$E$3:$E$"+(rs.length+2)}};
wb.recalculate();
await fs.writeFile(path.join(out,'workbook-inspection.ndjson'),(await wb.inspect({kind:'workbook,sheet,table',maxChars:16000,tableMaxRows:2,tableMaxCols:5})).ndjson||'');
const errors=await wb.inspect({kind:'formula',maxChars:5000,options:{maxResults:100}});
await fs.writeFile(path.join(out,'workbook-error-scan.json'),JSON.stringify(errors,null,2));
await fs.mkdir(path.join(out,'previews'),{recursive:true});
for(const name of ['使用说明',...specs.map(s=>s.name)]){
 const range=name==='使用说明'?'A1:C8':'A1:'+col(Math.min((specs.find(s=>s.name===name)?.columns.length||6)-1,5))+(name==='DDL审计'?'5':'10');
 const img=await wb.render({sheetName:name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(out,'previews',name+'.png'),new Uint8Array(await img.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'梁子湖项目_本体与关系全量结构导出.xlsx'));
await fs.writeFile(path.join(out,'workbook-build-report.json'),JSON.stringify({authoring_library:'@oai/artifact-tool',sheets:review,source_counts:schema.counts},null,2));
console.log(JSON.stringify({status:'exported',sheets:review.length+1},null,2));
process.exit(0);

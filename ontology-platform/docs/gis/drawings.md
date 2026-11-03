# 五份竣工图 GIS 数据与地图接口

2026-11-03：按用户反馈重新提取尺寸、数量、纸面周长、尺度依据及对象关系。**GIS查询库实际入库已验证，正式本体核心库/Jena尚未导入；尚未达到逐项无遗漏、地理配准或现场验收。** 未找到用户所说的 `upload` 目录，使用 farm 中五份竣工 PDF 及其已有派生文件，原件 SHA-256 见数据包的 `source_manifest`。

[田块与鱼塘完整周长清单](object-metrics.md)列出120个面对象。163份[对象档案](../../datasets/drawings/object-profiles.json)保留测量关系与尺度依据；[结构化覆盖统计](../../datasets/drawings/semantic-coverage.json)区分原文提取、纸面计算、尺度情景和重复印刷证据。

本轮补充：1,218条人工复核指标、表格合计和备注中的明确单位数量；全部120个面对象的纸面周长/面积；13个面对象的参考长度推算与范围；沟深1.1m/0.8m、渠底高程17.94m和工程平均清淤厚度1m分别建属性。当前语义包合计3,202条记录、6,297个节点、10,279条关系，其中包含来源陈述和测量节点，**不是6,297个实物或3,202次独立测量**。原文、数值、小数精度、单位、SI换算、适用对象、定位、推导方法和不累计政策均可追查。

新建生产路Ⅱ型-2图注已由误读100.36m更正为100.56m，并保留旧读数及工程表105.86m的冲突。各图同名区域不自动跨图合并。清5—清17工程组与13个对应塘面建立编号关系，总清淤量不分配到各塘。图上未见可可靠关联到单塘的水深；沟深、渠底高程、项目等效清淤厚度不能代用。

## 已保存的数据

| 数据 | 数量 | 含义 |
| --- | ---: | --- |
| 图纸 | 5 | 庙下流；新屋湾、毛家湾；张家湾；谭湾沈湾；A/B/C/D/E/F区 |
| 田块 | 100 | 保留 farm 持久 UUID、原始编号、纸面多边形和台账值 |
| 塘面 | 20 | 独立 UUID 和纸面多边形；不假定均已核验为养殖鱼塘 |
| 道路 / 沟渠 | 17 / 5 | 已有源线形；不把纸面长度当作米 |
| 设施标注 / 未决标签 | 20 / 1 | 表示文字或符号，不等于21个唯一实物设施 |
| 原生文字 | 714 | 全量保留已有 PDF 原生提取；其中乱码不静默修补 |
| OCR 候选 | 4,992 | 60个分块处理成功，保留位置、识别分数、原始候选与去重记录 |
| 图例 / 尺寸陈述 | 222 / 65 | 按图保存；同一图例或项目量在不同图出现时不合并计数 |
| 表 / 表行 | 9 / 632 | 包含工程量和面积表，原始字符串、小数、单位、空格和合并格上下文保留 |
| 背景类别 / 区域标签 | 23 / 56 | 类别与区域证据，尚不等于逐个背景对象矢量化 |

共163个空间表示、8,160条证据记录，其中包含本轮1,447条指标复核、尺度和缺口记录。证据数不能作为实物总数或独立工程量求和。

数据位于 [`datasets/drawings`](../../datasets/drawings/)：`package.json` 是带内容摘要的不可变导入包；`coverage.json` 是缺口清单；两份 `review-*.json` 是人工转录；`ocr-candidates.json` 保存完整OCR过程；`entity-proposals.jsonld` 是本体实例候选导出。田块/塘面使用现有 `Field`/`Pond` 类，其他图纸类使用独立词汇表。**这些 UUID 与候选声明尚未由本轮注册到生产治理主库或 Jena**；后续按现有受控摄取流程采纳，不绕过版本、证据和授权。

## 单位与冲突

五张图各有独立纸面坐标：`PDF_LANDSCAPE_LOCAL`，单位 `pt`，左上原点，x向右、y向下，PostGIS SRID=0。没有控制点或已知地理坐标系，不能拼成真实经纬度地图。`area_m2`、`length_m` 保持 null。RFC7946要求地理坐标，因此这里返回 `DrawingFeaturePage`，不伪装成可直接叠加底图的 GeoJSON。

带单位的图中尺寸和表格面积保存在证据中。田块台账的原面积没有单位，`ledger_area.unit=null`，不得自动换算成亩或平方米。表格的公顷、亩、m、m³原文与台账分别保存，不按相似名称强行绑定。

例如庙下流图中400波纹管两处各标42m，工程量表相近编号为133.00m和98.20m；排水沟图面编号与表格编号也存在差异。这些不是已解决的同一对象配对。重复项目总量不能在五图间累加。面积表合计和逐行显示的小数精度差异保留原值，空白不改为0。

## 数据库及部署

由 `lzo.storage.migrate` 接续应用 `005_drawings.sql` 和 `006_drawing_semantics.sql`，GIS schema升级至6。原四张图纸表之外增加语义数据集、当前版本、节点、关系、对象档案和指标六张查询表。它们是GIS查询模型，正式本体仍使用已有semantic core与Jena。导入使用owner账号、事务和数据集锁；同版本同摘要重放不改数据，同版本异内容拒绝。应用账号只有这些表的SELECT权限。

以下命令从 `ontology-platform` 执行，使用项目Python 3.12环境；凭据仅通过既有私有环境配置，不写入命令或Git：

```powershell
python scripts/import_drawing_gis.py
# 校验通过后，使用已配置的 LZO_GIS_MIGRATION_DATABASE_URL：
python scripts/import_drawing_gis.py --apply
python scripts/import_drawing_semantics.py --apply
# 真实PostGIS核验还需 LZO_GIS_DATABASE_URL（应用角色）：
python scripts/verify_drawing_postgis.py
python scripts/verify_drawing_semantics_postgis.py
```

旧部署必须先升级；本轮就绪检查要求GIS schema6。本地独立、仅loopback的PostgreSQL/PostGIS实例已导入并回读真实派生资料，验证分页、类型筛选、对象关系、SRID、有效性、重放、事务回滚和应用角色权限。见 [`postgis-import.json`](postgis-import.json)、[`semantics-postgis-verification.json`](semantics-postgis-verification.json) 与 [`postgis-tests.xml`](postgis-tests.xml)。这不是生产部署、现场测量或完整平台登录链路验收。

正式本体导入器 `scripts/import_drawing_ontology.py` 使用现有注册对象、修订、事实支持、原图证据和Jena投影服务，保留farm UUID，不使用旁路SQL写语义表。可审模型见 [`proposed-drawing-schema.json`](proposed-drawing-schema.json)，校验结果见 [`ontology-import-validation.json`](ontology-import-validation.json)。当前core空库已迁移，但没有真实管理员、授权或已发布模型，详见 [`ontology-runtime-readiness.json`](ontology-runtime-readiness.json)。需要真实授权操作人及owner scope；新模型发布由现有 `schema.publish` 规则要求独立审核。不能虚构两个人或伪造审核完成正式入库。

```powershell
python scripts/import_drawing_ontology.py --schema-document docs/gis/proposed-drawing-schema.json
# 具备真实身份/范围授权后，首次运行创建实际模型草稿与审核单：
python scripts/import_drawing_ontology.py --apply --actor <UUID> --owner-scope <UUID> --source-root <farm目录> --drain-jobs 50000 --report .runtime/ontology-import.json
# 模型经平台独立审核后，把 --apply 换为 --resume，其余参数相同，最终回读PG和Jena。
```

## 前端接口

生产接口使用原有会话与当前全局 `internal view` 权限，只在split模式读取GIS库；没有权限不会返回整图。响应禁用共享缓存，无公开写入端点。

| GET 路径 | 返回 |
| --- | --- |
| `/api/v1/drawing-gis/drawings` | 5张图、坐标政策、版本及摘要 |
| `/api/v1/drawing-gis/features` | 空间表示；`drawing_id`、`kind`、`bbox`、`limit`、`cursor` |
| `/api/v1/drawing-gis/features/{identifier}` | 表示ID或唯一实体UUID详情 |
| `/api/v1/drawing-gis/annotations` | 所有证据；按图分页，不能只取第一页 |
| `/api/v1/drawing-gis/coverage` | 覆盖情况、未解决项、版本及摘要 |
| `/api/v1/drawing-gis/profiles/{identifier}` | 田/塘及其他表示的周长、面积、尺度情景、深度缺项及测量关联 |
| `/api/v1/drawing-gis/entities/{UUID}` | 空间或非空间对象的类别、名称和属性 |
| `/api/v1/drawing-gis/measurements` | `kind`、`subject_id`、`drawing_id`筛选；完整分页 |
| `/api/v1/drawing-gis/relationships` | `subject_id`的出向关系；完整分页 |

`bbox=min_x,min_y,max_x,max_y` 是纸面外包框相交筛选，非精确几何相交。每页最多1000项。游标绑定筛选和摘要，版本变化时必须重新读取。图纸、要素、证据和coverage须使用同一摘要；示例适配器用 `expectedDigest` 检查跨接口一致性。

对象档案、指标、关系使用语义包摘要，其 `source_package_sha256` 必须等于当前图纸包摘要，版本不匹配返回409。`formal_core_imported=null`表示GIS接口未查询正式本体状态，不等于已入本体或已采纳。`kind=channel_depth`、`bottom_elevation`、`project_mean_dredging_thickness`分别查询三种概念；数量记录中的 `numericValue` 支持原单位数值，SI换算不可用时仍保留原值。

[`examples/drawing-map/adapter.mjs`](../../examples/drawing-map/adapter.mjs) 提供完整分页、UUID/表示ID映射及纸面到Three.js本地X/Z平面转换；`scale`是显示缩放，不是米/pt。已对照farm的 `twin-adapter.js`、`ontology-contracts.js` 身份契约；**本轮没有修改farm的前端样式、切换其生产数据源或发布farm仓库**。接入时复用 `entityId`/`spatialId`，按图展示，不把demo场景或任意拼接布局标为真实GIS。

离线预览只用于复核公开证据，独立于生产鉴权，绑定127.0.0.1：

```powershell
python scripts/import_drawing_gis.py --offline .runtime/drawing-gis.sqlite3 --apply
python scripts/import_drawing_semantics.py --offline .runtime/drawing-gis.sqlite3 --apply
python scripts/preview_drawing_gis.py --offline .runtime/drawing-gis.sqlite3
# 浏览器打开 http://127.0.0.1:8791
```

预览支持5图切换、类别筛选、平移缩放、点选周长/面积/深度缺项与身份、全文证据搜索和完整分页。SQLite不是PostGIS替代品；活动数据库不提交Git。

## 重建与未完成项

```powershell
# 可选OCR环境：rapidocr_onnxruntime==1.4.4、Pillow、numpy及其运行依赖
python scripts/extract_drawing_text.py --farm-root <farm目录> --output datasets/drawings/ocr-candidates.json
python scripts/build_drawing_gis.py --farm-root <farm目录> --version 4
python scripts/build_drawing_semantics.py --version 2
python scripts/report_drawing_metrics.py
```

原始farm目录需包含五份PDF、`data/spatial/drawing-entities.json`、`native-annotations.json`、5张landscape PNG及 `data/audit/entity-mapping.json`。生成器校验固定原图SHA-256，未知来源必须先复核映射；任何已入库内容变化必须升版本。已有独立人工复核文件需保留。原PDF和运行资产不在本次公开复制范围。

仍缺：用户所述upload来源最终确认；背景建筑、其他水面、地物和高程点的逐对象矢量化；4992条OCR候选逐条校核及实物关联；工程表与图面冲突解释；台账面积单位；坐标系、测量控制点和高程基准；生产主库采纳及现场验收。因此 `semantic_complete=false`、`georeferencing_complete=false` 是当前真实状态。获得原CAD/测量控制资料后才能继续可靠配准，不能以测试通过宣称“全部数据无遗漏”。

坐标依据：[RFC7946](https://www.rfc-editor.org/rfc/rfc7946.html)；[PostGIS ST_SetSRID](https://www.postgis.net/docs/manual-3.4/en/ST_SetSRID.html)只设置坐标参考标识，不做坐标变换。

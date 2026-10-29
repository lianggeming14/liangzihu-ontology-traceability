# 五份竣工图 GIS 数据与地图接口

2026-10-29：已完成图纸证据入库与读取接口；**尚未达到逐项无遗漏、地理配准或现场验收**。本轮未找到用户所说的 `upload` 目录，使用 farm 中五份竣工 PDF 及其已有派生文件，原件 SHA-256 见数据包的 `source_manifest`。此来源假设需要最终核实。

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

共163个空间表示、6,713条证据记录。证据数不能作为实物总数或独立工程量求和。

数据位于 [`datasets/drawings`](../../datasets/drawings/)：`package.json` 是带内容摘要的不可变导入包；`coverage.json` 是缺口清单；两份 `review-*.json` 是人工转录；`ocr-candidates.json` 保存完整OCR过程；`entity-proposals.jsonld` 是本体实例候选导出。田块/塘面使用现有 `Field`/`Pond` 类，其他图纸类使用独立词汇表。**这些 UUID 与候选声明尚未由本轮注册到生产治理主库或 Jena**；后续按现有受控摄取流程采纳，不绕过版本、证据和授权。

## 单位与冲突

五张图各有独立纸面坐标：`PDF_LANDSCAPE_LOCAL`，单位 `pt`，左上原点，x向右、y向下，PostGIS SRID=0。没有控制点或已知地理坐标系，不能拼成真实经纬度地图。`area_m2`、`length_m` 保持 null。RFC7946要求地理坐标，因此这里返回 `DrawingFeaturePage`，不伪装成可直接叠加底图的 GeoJSON。

带单位的图中尺寸和表格面积保存在证据中。田块台账的原面积没有单位，`ledger_area.unit=null`，不得自动换算成亩或平方米。表格的公顷、亩、m、m³原文与台账分别保存，不按相似名称强行绑定。

例如庙下流图中400波纹管两处各标42m，工程量表相近编号为133.00m和98.20m；排水沟图面编号与表格编号也存在差异。这些不是已解决的同一对象配对。重复项目总量不能在五图间累加。面积表合计和逐行显示的小数精度差异保留原值，空白不改为0。

## 数据库及部署

在已有多存储平台应用 `database/gis/005_drawings.sql`（由 `lzo.storage.migrate` 接续迁移），GIS schema升级至5。增加 `gis_drawing_datasets`、`gis_drawings`、`gis_drawing_features`、`gis_drawing_annotations` 四表。导入使用owner账号、事务和数据集锁；同版本同摘要重放不改数据，同版本异内容拒绝。应用账号只有新表SELECT权限。

以下命令从 `ontology-platform` 执行，使用项目Python 3.12环境；凭据仅通过既有私有环境配置，不写入命令或Git：

```powershell
python scripts/import_drawing_gis.py
# 校验通过后，使用已配置的 LZO_GIS_MIGRATION_DATABASE_URL：
python scripts/import_drawing_gis.py --apply
# 真实PostGIS核验还需 LZO_GIS_DATABASE_URL（应用角色）：
python scripts/verify_drawing_postgis.py
```

已有schema4部署必须先升级；本轮新平台就绪检查要求schema5。本地已在独立、仅loopback的PostgreSQL/PostGIS实例导入真实派生资料，并验证分页、SRID、有效性、重放、事务回滚和应用角色权限。见 [`postgis-import.json`](postgis-import.json) 与 [`postgis-tests.xml`](postgis-tests.xml)。这不是生产部署、现场测量或完整平台登录链路验收。

## 前端接口

生产接口使用原有会话与当前全局 `internal view` 权限，只在split模式读取GIS库；没有权限不会返回整图。响应禁用共享缓存，无公开写入端点。

| GET 路径 | 返回 |
| --- | --- |
| `/api/v1/drawing-gis/drawings` | 5张图、坐标政策、版本及摘要 |
| `/api/v1/drawing-gis/features` | 空间表示；`drawing_id`、`kind`、`bbox`、`limit`、`cursor` |
| `/api/v1/drawing-gis/features/{identifier}` | 表示ID或唯一实体UUID详情 |
| `/api/v1/drawing-gis/annotations` | 所有证据；按图分页，不能只取第一页 |
| `/api/v1/drawing-gis/coverage` | 覆盖情况、未解决项、版本及摘要 |

`bbox=min_x,min_y,max_x,max_y` 是纸面外包框相交筛选，非精确几何相交。每页最多1000项。游标绑定筛选和摘要，版本变化时必须重新读取。图纸、要素、证据和coverage须使用同一摘要；示例适配器用 `expectedDigest` 检查跨接口一致性。

[`examples/drawing-map/adapter.mjs`](../../examples/drawing-map/adapter.mjs) 提供完整分页、UUID/表示ID映射及纸面到Three.js本地X/Z平面转换；`scale`是显示缩放，不是米/pt。已对照farm的 `twin-adapter.js`、`ontology-contracts.js` 身份契约；**本轮没有修改farm的前端样式、切换其生产数据源或发布farm仓库**。接入时复用 `entityId`/`spatialId`，按图展示，不把demo场景或任意拼接布局标为真实GIS。

离线预览只用于复核公开证据，独立于生产鉴权，绑定127.0.0.1：

```powershell
python scripts/import_drawing_gis.py --offline .runtime/drawing-gis.sqlite3 --apply
python scripts/preview_drawing_gis.py --offline .runtime/drawing-gis.sqlite3
# 浏览器打开 http://127.0.0.1:8791
```

预览支持5图切换、类别筛选、平移缩放、点选身份、全文证据搜索和完整分页。SQLite不是PostGIS替代品；活动数据库不提交Git。

## 重建与未完成项

```powershell
# 可选OCR环境：rapidocr_onnxruntime==1.4.4、Pillow、numpy及其运行依赖
python scripts/extract_drawing_text.py --farm-root <farm目录> --output datasets/drawings/ocr-candidates.json
python scripts/build_drawing_gis.py --farm-root <farm目录> --version 4
```

原始farm目录需包含五份PDF、`data/spatial/drawing-entities.json`、`native-annotations.json`、5张landscape PNG及 `data/audit/entity-mapping.json`。生成器校验固定原图SHA-256，未知来源必须先复核映射；任何已入库内容变化必须升版本。已有独立人工复核文件需保留。原PDF和运行资产不在本次公开复制范围。

仍缺：用户所述upload来源最终确认；背景建筑、其他水面、地物和高程点的逐对象矢量化；4992条OCR候选逐条校核及实物关联；工程表与图面冲突解释；台账面积单位；坐标系、测量控制点和高程基准；生产主库采纳及现场验收。因此 `semantic_complete=false`、`georeferencing_complete=false` 是当前真实状态。获得原CAD/测量控制资料后才能继续可靠配准，不能以测试通过宣称“全部数据无遗漏”。

坐标依据：[RFC7946](https://www.rfc-editor.org/rfc/rfc7946.html)；[PostGIS ST_SetSRID](https://www.postgis.net/docs/manual-3.4/en/ST_SetSRID.html)只设置坐标参考标识，不做坐标变换。

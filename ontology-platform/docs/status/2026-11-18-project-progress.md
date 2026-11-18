# 梁子湖本体数据库：当前进度与已完成任务

整理日期：2026-11-18。本文依据已提交的代码、数据清单和验收记录整理；最近一次 GIS/本体关系球实库与浏览器验收日期为 2026-11-16。本次工作是进度汇总，没有重新执行整套测试，也不将此前运行状态表述为今日实时巡检结果。

成果主仓库：[lianggeming14/liangzihu-ontology-traceability](https://github.com/lianggeming14/liangzihu-ontology-traceability)。本报告对应的功能交付提交为 [`fc32aee`](https://github.com/lianggeming14/liangzihu-ontology-traceability/commit/fc32aee2ddfca90ca47765e759befb1eb0cb73b8)，数据库发布版本为 `16c6ce16-e28c-5e9c-a766-874fca309c5f`。

## 一、目前做到哪一步

项目已完成本地数据库服务、CSV 批次入库、RDF 本体关系、按类型逐级浏览、候选平面 GIS、地图与本体双向跳转，以及可拖动的本体关系球。当前已有可操作、可查询、可导出的工程版本。

下一阶段主要是补齐真实现场数据与定位证据、处理未解析关系、完成最新数据备份与实际换机验证。当前工程交付不等于全部五张图已经逐项无遗漏，也不等于真实设备联网、现场测绘和完整生产平台验收已经完成。

| 工作模块 | 当前状态 | 已完成内容 |
| --- | --- | --- |
| SQL、GIS 与 RDF 存储 | 已实施并有原生实库验收 | PostgreSQL/PostGIS 保存业务、空间与来源记录；Jena Fuseki 保存 RDF，本体对象共用稳定 IRI。 |
| 五份竣工图资料 | 已完成阶段提取、关系整理和审查展示 | 图形、文字、表格、尺寸、纸面周长、单位、冲突与来源证据已结构化；仍保留 OCR、配准及覆盖缺口。 |
| CSV 完整批次 | 已导入并全量回读 | 66 个业务 CSV、153,862 条记录、1,397 个字段；已建立实例和关系账本。 |
| 本体浏览 | 已实现并验收 | 按分类、下级类型、实例逐级点击；查看属性、正向/反向关系，并继续追溯关联对象。 |
| 新 CAD 平面 GIS | 已发布候选数据版本 | 采用固定来源几何、消除重复绘制、显示区域与点位、保留无位置对象目录。 |
| 本体关系球 | 已实现并验收 | 支持鼠标拖动、缩放、节点选择、关系筛选及分页查看实例。 |
| 本地服务器与 API | 已部署并完成阶段验收 | 统一启停、导入任务、版本发布、查询、导出、状态与日志。 |
| 备份与换机机制 | 已实现，部分环境已验收 | 已完成本机全量恢复及换目录重启；第二台物理机、跨系统及 Docker 尚未实测。 |
| GitHub 交付 | 功能版本已同步并核对 | 代码、公开派生数据、测试、截图和指南位于本体仓库；本总结另存 upload-files。 |

## 二、已经完成的数据工作

### 1. 五份图纸与历史空间资料

已整理 5 份竣工图，保留 100 个田块、20 个塘面等共 163 个空间表示，以及文字、OCR 候选、工程表、图例和尺寸证据。这里的塘面是图纸表示，不能直接当作已现场核实的养殖资产。

图纸语义资料含 3,202 条测量/指标等记录、6,297 个节点、10,279 条关系，并通过 163 条来源证据桥关联已有地图。节点包含测量与来源陈述，不代表 6,297 个实物；记录数也不等于独立测量次数。所有 120 个田块/塘面已有纸面周长和面积记录；部分对象有参考长度推算。纸面坐标、计算值、来源单位与真实地面米制尺寸分开保存，不能混用。

已区分沟深、渠底高程、工程平均清淤厚度和单塘水深。原图不能可靠归属到单塘的水深继续保留未知，不把高程或工程平均值当作塘深。

旧文档中的“尚未进入 Jena”属于当时阶段记录；后续发布统计已经保留上述图纸实例及关系。仍未完成的是逐项无遗漏复核、现场配准及完整生产治理流程下的正式采纳，不能据后续入库反推这些项目也已通过。

证据：[图纸提取与缺口记录（历史阶段）](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/gis/drawings.md)、[最新发布及历史保留核验](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/gis-sphere-native.json)。

### 2. CSV 完整批次与本体关系

| 项目 | 已核对规模 |
| --- | ---: |
| 业务 CSV | 66 个 |
| 来源记录及新批次实例 | 153,862 条 |
| 来源字段 | 1,397 个 |
| 原文单元格 | 3,539,134 个 |
| 关系账本记录 | 810,934 条 |
| 该批次新增 RDF 三元组 | 21,333,891 条 |

原始记录、类型化单元格、规范实例及关系账本已通过 PostgreSQL 全量回读；RDF 完整词项集合与 Jena 回读一致，SHACL 检查通过。历史图、旧实例和旧导航继续保留。

数据性质按来源保留：主体为规则模拟数据，天气为再分析数据，资产为复用目录。完成清洗、入库和关联不代表这些记录全部成为真实现场观测。缺值、未知字段、未解析外键以及历史均分演示关系均有相应标记。

证据：[CSV 批次说明与全量验收](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/csv-batch/README.md)。

### 3. 新 CAD/GIS 来源完整接收

从 `litt1eloser/liangzihu-farm-platform` 的固定提交接收 11 个文件，全部 86 张来源表、32,464 条来源记录已保存。86 表包含 GPKG 元数据与 RTree 表，32,464 条记录不能当作独立实物数量。固定提交、文件摘要、来源行、字段、原始几何、坐标声明和单位均保留。

| 新增本体候选对象 | 数量 | 定位情况 |
| --- | ---: | --- |
| 田块 | 67 | CAD 范围 |
| 塘口 | 5 | CAD 范围 |
| 设施 | 35 | 28 个文字锚点，7 个无位置 |
| 摄像头图纸符号 | 39 | 候选点位，未绑定真实设备 |
| 道路 | 37 | 来源线或面 |
| 沟渠 | 70 | 来源线或面 |
| 图纸分组 | 5 | 来源分组，不是行政区域边界 |
| 合计 | **258** | **246 个有显示几何、12 个无几何** |

同时新增 232 条对象关系，其中 18 条为点与区域的派生空间关系；完整入库图新增 69,740 条 RDF 陈述。空间落入关系带算法证据，不自动等同于业务所有权。

15,084 条未经确认的空间来源记录保留在质量隔离目录，没有删除原始记录。GIS 保存原始及候选几何，重要对象及其关联同步进入 RDF，能够从本体访问对象信息。

证据：[来源清单](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/gis-source-audit-2026-11-16.json)、[CAD 公开派生数据](https://github.com/lianggeming14/liangzihu-ontology-traceability/tree/main/ontology-platform/datasets/cad-gis)。

## 三、已经完成的地图与本体交互

### 平面地图

- 已将新 CAD 数据接入现有本体浏览器主地图入口，使用一个平面显示。
- 67 个重复农田来源引用全部保留，图形只绘制一份。
- 75 个规范多边形切分为 81 个不重复叠盖的显示面片；其中 7 个冲突面片保留全部相关对象，原始边界不被覆盖。
- 田块、塘口、设施锚点、摄像头候选可点击进入本体；本体实例可返回同一地图对象。
- 面积、周长、长度保留算法、单位及计算前提；页面用中文说明和适当小数显示，原始精度仍可展开查看。
- 道路、沟渠可通过图层开关显示；旧图纸坐标视图仍可访问。
- 无坐标对象保留在待定位目录。加上原有 24 条合成设备，当前地图目录为 282 个对象，其中 36 个待定位。

摄像头标记来自 39 个 CAD 符号，不能宣称是 39 台已联网实物设备。设施位置来自文字锚点，也不能直接等同于安装位置。

### 球状本体关系网

球体首层显示 186 个本体类型和 1,941 条类间边，其中 1,311 条为本体定义边、630 条为实例关系聚合边。边来自已发布本体与实例关系；类间边数不等于全库 RDF 三元组数。

已支持拖动旋转、滚轮缩放、节点选择、关系筛选、下级类型与实例浏览；实例关系每页最多 12 对。地图、关系球和对象详情使用相同 IRI，并通过 `release_id` 固定同一版本。

证据：[地图与球体验收及截图](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/gis-sphere-acceptance.md)、[关系网公开数据](https://github.com/lianggeming14/liangzihu-ontology-traceability/tree/main/ontology-platform/datasets/ontology-network)。

## 四、当前发布数据总量

以下为 2026-11-16 已验收发布的公开导航口径，包含既有数据和新增 CAD 数据，不应再与前述批次数量重复相加。

| 项目 | 数量 |
| --- | ---: |
| 公开发布 RDF 图 | 6 个 |
| 公开发布图 RDF 三元组 | 24,124,600 条 |
| 本体类型 | 186 个 |
| 实例 | 181,255 个 |
| 规范关系记录 | 890,235 条 |
| 已解析规范关系 | 890,125 条 |
| 历史未解析关系 | 110 条 |
| 球网聚合输入的唯一实例三元组 | 900,620 条 |

规范关系统计、包含独立演示关系的球网统计和 RDF 图总量是不同口径。完整 Fuseki 数据集还含私有来源图，不能拿全数据集图数替换上述 6 个公开发布图。

GitHub 中 CAD 小包的 `business.nt` 为 3,449 条公开业务 RDF 投影；它不等于完整来源入库图的 69,740 条陈述，更不等于全库备份。

## 五、本地服务器、接口与迁移

已提供受管 PostgreSQL/PostGIS、Fuseki、HTTP 与后台导入任务服务，以及启动、停止、状态、日志和发布版本管理。已实现完整批次导入、JSON/CSV/RDF 导出，查询与分页固定发布版本。GIS 有独立组合发布入口，保留完整历史本体数据后再切换新版本。

主要接口包括：

```text
GET /api/v1/status
GET /api/v1/manifest
GET /api/v1/children
GET /api/v1/instances
GET /api/v1/resource
GET /api/v1/maps
GET /api/v1/network
GET /api/v1/network-relations
GET /api/v1/export
GET /api/v1/releases
```

已完成本机四个 SQL 数据库与完整 RDF 数据集的备份恢复核验，以及同机换目录、冷迁移和原生重启验收。最新 CAD 原件与导入证明目录 `cad-imports` 已加入私有备份选项及未来恢复示例，并限制恢复到正确的数据根目录。

当前未安装开机自启。电脑重启后按启动入口启动服务。本机入口为 `http://127.0.0.1:8792/`，本体浏览器为 `http://127.0.0.1:8792/ontology/`；`127.0.0.1` 只指当前电脑，不是公网服务器地址。

GitHub 保存代码、公开派生数据、脚本、截图和指南；活动数据库、原始运行资产、完整私有备份及凭据保留在本机。换机需要安装匹配环境并恢复完整备份，不能只复制 GitHub 文件。

证据与操作：[快速上手](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/快速上手.md)、[使用指南](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/使用指南.md)、[部署与换机](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/部署与换机.md)、[服务器验收记录](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/server-readback.json)。

## 六、已经通过的核验

| 核验项 | 已记录结果 |
| --- | --- |
| 新 CAD SQL/PostGIS | 7 张新增表；全行、字段和几何回读一致，8,453 条几何记录含原始隔离及显示候选几何。 |
| 新 CAD RDF | 69,740 条完整词项集合一致，零缺失或多余。 |
| 新 CAD SHACL | 258 个实例通过。 |
| 历史数据保护 | 旧 678 个导航文件摘要不变；旧 498 张表行数除发布登记新增一条外不变；978 个旧 RDF 图计数不变。此项不冒充对全部旧库再次逐单元格回读。 |
| 重复导入 | 相同批次返回相同发布 ID，验证无重复发布。 |
| Python 回归 | 233 通过、15 跳过；跳过不计为通过。 |
| 原生 PostgreSQL Store | 独立测试库 24 通过。 |
| 前端模块测试 | 46 通过。 |
| 真实 Chrome | 地图与本体往返、测量显示、球体拖动/缩放、关系分页、历史版本及手机布局通过，零 JavaScript 错误。 |
| GitHub 同步 | 功能提交 `fc32aee` 已正常推送至指定本体仓库 main，并核对远端提交及文件摘要。 |

这些结果对应各自阶段与测试范围；没有用 SQLite 测试替代原生 PostgreSQL 或现场验收。本次汇总未重跑上述测试。

## 七、尚未完成与需要继续完善的事项

1. **五张图逐项无遗漏复核**：OCR 仍需人工核对，背景对象未全部矢量化，图注与表格的对象绑定及冲突仍有缺口。
2. **现场定位与真实尺寸确认**：新地图经纬度是来源转换的候选位置，原始 CAD 坐标参考仍为 `UNKNOWN`；原始未知坐标和高程不自动升级为已核实测量。
3. **单塘水深及真实设备绑定**：缺失水深继续为空，需要实测或可靠记录；摄像头/设施候选需要真实 ID、安装位置和业务归属证据后再绑定。尚未接入设备在线状态、视频或实时采集链路。
4. **未解析关系与数据治理**：继续处理 110 条历史未解析关系；合成、再分析、候选和现场数据保持区分，不能把演示分配当作真实资产归属。
5. **最新全量备份与实际换机**：CAD 导入后的全库备份尚未生成；第二台物理机器、跨 OS 和 Docker 恢复尚未实际验收，开机自启也未安装。
6. **完整平台与生产性能**：当前交付以轻量本地服务器和本体浏览为主；不能据此声称原完整生产平台全部完工。此前完整平台 10 用户负载中的 Graph/SPARQL 超时问题尚未取得通过验收，最新地图/球体通过不覆盖该性能缺口。

以上是后续待处理项，本报告没有启动新的开发、数据库修改或部署操作。后续工作的优先顺序可围绕现场数据补齐、来源关系核实、最新备份与真实换机验收安排。

## 八、查看成果

- 功能代码和数据：[本体项目仓库](https://github.com/lianggeming14/liangzihu-ontology-traceability)。
- 新版功能和测试截图：[GIS 与关系球交付报告](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/local-server/gis-sphere-acceptance.md)。
- 地图、对象、测量和 RDF：[CAD 公开派生数据](https://github.com/lianggeming14/liangzihu-ontology-traceability/tree/main/ontology-platform/datasets/cad-gis)。
- 球体类型节点与关系：[本体关系网数据](https://github.com/lianggeming14/liangzihu-ontology-traceability/tree/main/ontology-platform/datasets/ontology-network)。
- 本报告保存位置：`lianggeming14/upload-files` 根目录的 `项目进度与已完成任务总结_2026-11-18.md`；本体仓库保留同内容副本 `ontology-platform/docs/status/2026-11-18-project-progress.md`。

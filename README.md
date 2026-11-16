# 梁子湖农业本体数据库

本地服务器入口见[快速上手](ontology-platform/docs/local-server/快速上手.md)、[使用指南](ontology-platform/docs/local-server/使用指南.md)和[部署与换机](ontology-platform/docs/local-server/部署与换机.md)。服务使用 PostgreSQL/PostGIS、Jena RDF、统一导入/查询 API 与本体浏览器，默认地址 `http://127.0.0.1:8792/`；运行数据、备份和凭据留在本机私有目录。

主仓库：[lianggeming14/liangzihu-ontology-traceability](https://github.com/lianggeming14/liangzihu-ontology-traceability)，保持 Public、默认分支 `main`。

2026-11-16：本地服务器已发布 **[平面 GIS 与本体关系球](ontology-platform/docs/local-server/gis-sphere-acceptance.md)**。完整接收 11 个固定来源文件、86 张来源表、32,464 条来源记录，新增 258 个候选空间对象和 232 条关系；6 个公开 RDF 图合计 24,124,600 条三元组，186 个类型、181,255 个实例。地图按真实来源轮廓显示并支持进入本体；关系球可拖动、缩放和逐级查看实例。地图、测量和公开 RDF 可下载：[CAD 派生数据包](ontology-platform/datasets/cad-gis/README.md)。原有 CSV 与历史导航均保留。

2026-11-10：新批次的 **66 个业务 CSV、153,862 条记录、1,397 个来源字段**已全部录入隔离 PostgreSQL schema；原始记录、规范实例、3,539,134 个原文单元格及对应类型化单元格、810,934 条关系账本均已完成实库逐项回读。新 Jena 图的 **21,333,891 条三元组**通过完整术语集合等值核验；实际 SHACL 检查 153,862 个实例、1,397 个字段约束，零违规。新导航已经激活：**5 图、24,054,860 条三元组、178 个概念、150 个叶类、180,997 个实例**。全导航检查零悬空、零错类，实际 Chrome 与独立实时 HTTP → SPARQL 验收均通过，详见[批次验收说明](ontology-platform/docs/csv-batch/README.md)。

批次的 `source_registry` 将主体标为规则模拟数据，天气为再分析数据，资产为复用目录；数据性质随实例和来源保留，记录数不能视为现场实物资产数量或正式采纳。未知字段和无法确认的外键保留来源原文与未解析状态，缺值不编造成数值。

| 查看内容 | 入口 |
| --- | --- |
| 新版 GIS、关系球与实库验收 | **[本次验收与截图](ontology-platform/docs/local-server/gis-sphere-acceptance.md)**、[操作指南](ontology-platform/docs/local-server/使用指南.md) |
| 新增候选对象、测量、关系与 RDF | [CAD 公开派生数据](ontology-platform/datasets/cad-gis/README.md)、[关系球公开聚合](ontology-platform/datasets/ontology-network/README.md) |
| 完整 CSV 批次、数据性质、复现前提与验收进度 | **[CSV 批次说明](ontology-platform/docs/csv-batch/README.md)** |
| PostgreSQL 结构和已通过的全量核对 | [DDL](ontology-platform/docs/csv-batch/schema.sql)、[结构清单](ontology-platform/docs/csv-batch/schema-structure.json)、[PG 回读](ontology-platform/docs/csv-batch/pg-readback.json) |
| 来源字节清单与清洗核验 | [来源清单](ontology-platform/docs/csv-batch/source-manifest.json)、[质量审计](ontology-platform/docs/csv-batch/quality-audit.json)、[规范模型](ontology-platform/docs/csv-batch/model-readback.json) |
| 新图 RDF、SHACL 与导航激活报告 | [完整 RDF 术语回读](ontology-platform/docs/csv-batch/rdf-readback.json)、[SHACL](ontology-platform/docs/csv-batch/shacl-readback.json)、[导航激活](ontology-platform/docs/csv-batch/activation-readback.json) |
| 全部导航与公开分片 | [双向关系核验](ontology-platform/docs/fish/ontology-review/navigation-readback.json)、[CSV 分片清单及摘要](ontology-platform/docs/csv-batch/navigation-files.json) |
| 实时 API 与实际浏览器验收 | [五图 HTTP → SPARQL](ontology-platform/docs/csv-batch/live-api-readback.json)、[Chrome 报告](ontology-platform/docs/fish/ontology-review/csv-browser-report.json)；零 JavaScript 错误 |
| 新批次实际截图 | [CSV 首页](ontology-platform/docs/fish/ontology-review/screenshots/desktop-csv-overview.png)、[桌面关系分页](ontology-platform/docs/fish/ontology-review/screenshots/desktop-csv-relations.png)、[手机关系分页](ontology-platform/docs/fish/ontology-review/screenshots/mobile-csv-relations.png) |
| 旧四图保护核验 | [完整回读对比](ontology-platform/docs/csv-batch/prior-graphs-readback.json)，保留原四图 2,720,969 条三元组 |
| 本体浏览、运行方式和地图来源 | **[本体审查说明](ontology-platform/docs/fish/ontology-review/README.md)**、[交互页面源码](ontology-platform/docs/fish/ontology-review/index.html) |
| 本体词汇和约束 | [OWL/Turtle](ontology-platform/docs/fish/ontology-review/vocabulary.ttl)、[SHACL/Turtle](ontology-platform/docs/fish/ontology-review/shapes.ttl) |
| 已有地图与图纸证据 | [6 个来源图层](ontology-platform/datasets/farm-map/README.md)、[图纸信息及 GIS 接口](ontology-platform/docs/gis/drawings.md) |
| 历史 10%＋依赖来源审计 | [辅助样本说明](ontology-platform/docs/fish/review-sample/README.md)，保留为独立旧批次 |

从仓库根目录运行：

```sh
cd ontology-platform
python scripts/serve_ontology_review.py --offline --port 0
```

当前本地服务器的本体浏览入口为 [http://127.0.0.1:8792/ontology/](http://127.0.0.1:8792/ontology/)，新版 GIS 与关系球请使用这个服务入口。上述独立审查命令读取仓库中的历史 CSV 分片，不代表已连接当前服务器发布。离线浏览规范化分片仅需 Python 标准库；GitHub 文件页显示 HTML 源码，不能直接运行交互页面。实时证据模式需要已启动的本地 Jena，去掉 `--offline` 后使用 manifest 中的图白名单查询。完整数据库重建另外需要固定来源 ZIP、私有连接、PostgreSQL/Fuseki 和旧四图基线，详见[复现步骤](ontology-platform/docs/csv-batch/README.md#复现与保护旧图)。

浏览器按所选类加载摘要，实例详情每块 500 条，高关联对象使用每块 4,800 条的独立关系文件，界面每页显示 12 条关系。新 CSV 分片在完整 RDF 术语集合证明与 Jena 相等并通过 SHACL 后，由同一投影模型分片序列化；旧 84 个叶类保留原先直接来自 Jena 回读值的路径。CSV 共发布 592 个压缩数据文件（66 个类摘要、362 个详情块、164 个关系块），共 70,148,120 字节，最大文件 1,865,203 字节。当前图清单及合计见 [manifest.json](ontology-platform/docs/fish/ontology-review/data/manifest.json)。

地图使用 No1dry/farm 固定提交中的真实来源轮廓，包括全域及五个图纸图层、284 个空间表示。局部图像／图纸坐标尚未地理配准；五图的 3,202 条测量通过 163 条源 UUID 证据桥关联地图，缺失的实测水深与周长继续保留未知。原有 10,495 条均分演示关系单独保留，原始来源归属不被覆盖。No1dry 仓库只作为只读来源。

代码、DDL、OWL/SHACL、全部规范化导航分片及验收报告随成果同步。原始 ZIP、Mac 元数据原件、`.runtime`、活动数据库、凭据、依赖和原始运行资产不进入仓库；Mac 元数据只公开字节摘要清单。当前工程位于 [ontology-platform](ontology-platform/README.md)，存储说明见[数据库文档](ontology-platform/database/README.md)；`implementation` 为历史 v0.4 工程。同步规则见 [GITHUB_SYNC.txt](GITHUB_SYNC.txt)。

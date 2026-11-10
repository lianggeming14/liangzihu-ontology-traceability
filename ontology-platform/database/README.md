# 数据库与语义存储

当前完整批次入口为 **[66 CSV 数据库与 RDF 验收](../docs/csv-batch/README.md)**。153,862 条记录已经写入 `lzo_gis.csv_batch_a4d78be79a83`：共 72 张表，其中 66 张类型化业务表；1,397 个来源字段、153,862 条原始记录及规范实例、3,539,134 个原文单元格及对应类型化单元格、810,934 条关系账本通过 PostgreSQL 全量回读。结构见 [schema.sql](../docs/csv-batch/schema.sql) 和[机器可读清单](../docs/csv-batch/schema-structure.json)，实际结果见 [pg-readback.json](../docs/csv-batch/pg-readback.json)。810,891 条关系解析到批次内实例；43 条外部／未解析引用保留原目标标识和空目标，不编造对象。

新 CSV 采用独立 Jena 命名空间和内容寻址图，21,333,891 条三元组通过[完整 RDF 术语回读](../docs/csv-batch/rdf-readback.json)，[SHACL](../docs/csv-batch/shacl-readback.json)检查 66 类、153,862 个实例及 1,397 个字段约束，零违规；[新导航已激活](../docs/csv-batch/activation-readback.json)，合计 5 图、24,054,860 条三元组和 180,997 个实例。旧 **[Jena 四图及地图证据](../docs/fish/ontology-review/README.md)**保留原身份，保护核验见 [prior-graphs-readback.json](../docs/csv-batch/prior-graphs-readback.json)：四图完整术语摘要不变，977 个原有非空图的清单计数受保护，其余图的保护范围为计数。OWL/RDFS 领域层级共享，来源表叶类、实例、属性、关系及 provenance 随批次隔离。新分片使用完整术语集合等值证明后的投影模型序列化；旧分片仍沿用直接 Jena 回读路径。完整规范化导航通过[全关系核验](../docs/fish/ontology-review/navigation-readback.json)，[独立实时 API](../docs/csv-batch/live-api-readback.json)和[实际 Chrome 浏览器](../docs/fish/ontology-review/csv-browser-report.json)验收均通过；API 使用实际 Fuseki SPARQL，SQL 连接和数据库变更均为 0。

复现工具为 `scripts/prepare_csv_batch.py`、`scripts/build_csv_database.py --apply`／`--verify`、`scripts/capture_csv_prior_graphs.py`、`scripts/build_csv_rdf.py --apply`、`scripts/verify_csv_prior_graphs.py` 和 `scripts/activate_csv_batch.py`，顺序和前提见[批次说明](../docs/csv-batch/README.md#复现与保护旧图)。只沿用 [config/fish-review.example.json](../config/fish-review.example.json) 指向的私有环境文件来读取连接 URL，不复用该配置的旧来源包或旧 schema。首次完整复现需要已准备的本地 PostgreSQL、Fuseki 和旧四图，在写入 CSV 图前捕获基线；原正式 importer／worker 不需重启。仅离线浏览规范化分片可运行 `python scripts/serve_ontology_review.py --offline --port 0`，不需要数据库或额外依赖。

[fish_review_10pct_v1](../docs/fish/review-sample/README.md) 是辅助 PostgreSQL/PostGIS 来源审计样本，保留 [SQL](../docs/fish/review-sample/schema.sql) 和[无凭据配置](../config/fish-review.example.json)。其中六个合成边界不作为新的来源地图。该审查样本与原正式采纳流程分别管理。

这里保存可复现的数据库定义和服务配置，不保存运行数据或密码。

| 路径 | 内容 |
| --- | --- |
| migrations/ | 实际 Alembic `env.py`、模板与版本迁移脚本 |
| alembic.ini | 迁移路径配置，自动将 `../backend/src` 加入 Python 模块路径 |
| postgres/init-databases.sh | Compose 首次初始化时创建平台及 Keycloak 数据库与角色 |
| fuseki/ | Jena Fuseki/TDB2 Dockerfile 和 RDF 数据集配置 |

治理库 `lzo` 保存身份、权限、不可变修订、审批、任务和 outbox；独立 `lzo_gis` 保存 PostGIS 空间索引，`lzo_timeseries` 保存按 UTC 月分区的观测和媒体索引，`lzo_catalog` 保存资料版本索引。Fuseki/TDB2 保存 RDF/OWL/SHACL 和受控语义投影；私有 S3 保存原件字节。外部 PostgreSQL/MySQL 仅是只读摄取来源，不由平台迁移管理。初始化脚本只对新 PostgreSQL 数据目录生效。

从仓库根目录离线查看迁移链：

```sh
python -m alembic -c database/alembic.ini heads
python -m alembic -c database/alembic.ini history
```

当前核心头为 `0406_storage_backups`；GIS 领域版本 4，时序与资料领域版本 3。历史迁移保留，新增变更追加。升级须提供四个独立 owner URL 和显式 `LZO_STORAGE_MODE=split`，以 `backend/src` 为 `PYTHONPATH` 执行 `python -m lzo.migrate`。普通 API/worker 只使用应用账号。迁移入口不从 Alembic 配置读取密码。

实际结构见[数据库关系与数据流](../docs/database/schema-guide.md)及[机器可读原生结构清单](../docs/database/schema-inventory.json)。升级、审批切换、备份、全新目标恢复及回滚见[迁移恢复手册](../docs/database/migration-recovery.md)；本机与容器边界见[可复现验收](../docs/database/acceptance.md)。运行数据、TDB2、原件、备份和凭据均排除在源码外。

[Word 报告](../docs/database/multi-store-architecture-report.docx)汇总结构、输入策略、实测结果与真实资料清单；[报告源数据](../docs/database/multi-store-report.source.json)和[原生 Word 构建脚本](../scripts/build_multistore_report.ps1)一并保留。构建脚本要求 Windows、已安装的 Microsoft Word 与 Noto Sans SC 字体，从仓库根目录运行；PDF 是排版检查的中间产物，交付文件为 DOCX。

# 本体农场 · 当前源码快照

本地服务器：[快速上手](docs/local-server/快速上手.md) · [使用指南](docs/local-server/使用指南.md) · [部署与换机](docs/local-server/部署与换机.md)。在本目录使用 `infra/local-server/local-server.cmd` 管理启动、停止与状态；默认访问 `http://127.0.0.1:8792/`。首次准备环境、恢复数据与配置要求以指南为准。

2026-11-16：已部署[新版平面 GIS 与本体关系球](docs/local-server/gis-sphere-acceptance.md)，当前发布保留全部旧实例并新增 258 个 CAD 候选对象、232 条关系，合计 181,255 个实例。打开本地 `/ontology/` 使用地图与球体；[公开 GIS/对象/测量/RDF](datasets/cad-gis/README.md)和[球网聚合](datasets/ontology-network/README.md)随代码上传。下文独立 `--offline` 命令仍用于历史 CSV 审查快照。

2026-11-10：当前入口为 **[66 CSV 完整批次](docs/csv-batch/README.md)** 和 **[本体、实例与来源地图](docs/fish/ontology-review/README.md)**。新批次 153,862 条记录已录入隔离 PostgreSQL schema，72 张表（66 张业务表）及 1,397 个来源字段通过实库全量回读；3,539,134 个原文单元格和对应类型化单元格、810,934 条关系账本均已核对。新 Jena 图 21,333,891 条三元组通过完整术语回读，SHACL 检查 153,862 个实例、1,397 个字段约束且零违规。新导航已激活，合计 5 图、24,054,860 条三元组、178 个概念、150 个叶类、180,997 个实例，完整双向导航零悬空／错类。旧四图 2,720,969 条三元组及 10,495 条独立演示关系继续保留；新批次采用独立身份。实际 Chrome 与独立实时 HTTP → SPARQL 验收均已通过。

新批次主体为规则模拟、天气为再分析、资产为复用目录，数据性质来自 `source_registry`。缺值、未知字段及未解析外键按来源保留，完整录入不构成正式采纳或现场验收。结构和证据见 [schema.sql](docs/csv-batch/schema.sql)、[字段字典](docs/csv-batch/field-dictionary.json)、[质量核验](docs/csv-batch/quality-audit.json)、[PostgreSQL 回读](docs/csv-batch/pg-readback.json)、[旧图保护回读](docs/csv-batch/prior-graphs-readback.json)、[RDF 回读](docs/csv-batch/rdf-readback.json)、[SHACL](docs/csv-batch/shacl-readback.json)、[激活报告](docs/csv-batch/activation-readback.json)、[全导航核验](docs/fish/ontology-review/navigation-readback.json)、[五图实时 API](docs/csv-batch/live-api-readback.json)和[Chrome 报告](docs/fish/ontology-review/csv-browser-report.json)。[CSV 首页截图](docs/fish/ontology-review/screenshots/desktop-csv-overview.png)及报告内其余四张截图来自实际浏览器，零 JavaScript 错误。

仅浏览公开分片时，从本目录运行 `python scripts/serve_ontology_review.py --offline --port 0`，打开终端给出的地址，无需安装依赖或连接数据库。GitHub 的 HTML 文件页显示源码。摘要按类加载，详情每块 500 条，高关联关系每块 4,800 条，界面每页 12 条；新 CSV 分片在完整 RDF 术语集合与 Jena 精确等值核验、SHACL 均通过后，由同一投影模型序列化，旧 84 类直接回读路径保留。CSV 592 个压缩分片共 70,148,120 字节，最大 1,865,203 字节，见[分片摘要](docs/csv-batch/navigation-files.json)。完整库复现需要固定来源、私有连接、本地 PostgreSQL/Fuseki 和旧四图，见[批次复现步骤](docs/csv-batch/README.md#复现与保护旧图)。

2026-10-29 更新：已增加[五份竣工图 GIS 数据与地图接口](docs/gis/drawings.md)，保存田块、塘面、路渠、标注及工程表证据，提供版本化读取API和核对预览。当前仍有OCR逐条校验、背景矢量化和地理配准缺口，不构成无遗漏提取或现场验收。

本仓库保存农业 Operational Ontology Platform 的当前源码，包含语义后端、React Studio 原型、数据库迁移和部署工具。已按确认方案实施语义主库与专业存储拆分；前端视觉重做仍暂停。工程证据与现场验收分别记录。

历史快照前里程碑为 **15/29**，见[历史快照状态](docs/status/2026-10-21-source-snapshot.md)。新增多存储的实际结构、原生验证、恢复证据、性能边界及未执行的容器/现场维度见[当前数据库验收](docs/database/acceptance.md)；这些工程结果不构成整个原 P0+P1 产品或生产迁移完成声明。

本次拆分的完整说明见 [Word 架构与数据准备报告](docs/database/multi-store-architecture-report.docx)，包含各库职责、统一身份、静态与动态输入路径、真实资料问题及实测结果。[阶段实施与审查记录](docs/database/implementation-record.json)保留各轮证据和决定。初始负载已完整保存并投影 1 万实例、10 万关系，但 10 用户测量中的图谱和 SPARQL 请求全部超时；当前性能验收不通过，不能把测量脚本成功退出解释为性能达标。

| 目录 | 职责 |
| --- | --- |
| [backend/](backend/README.md) | Python API、worker、权限治理、语义逻辑、摄取、地图服务、模型及测试 |
| [frontend/](frontend/README.md) | React 工作台与 Studio 原型、静态资源、单元测试及独立 npm 锁文件 |
| [database/](database/README.md) | Alembic 迁移、PostgreSQL 初始化和 Fuseki/TDB2 配置 |
| infra/ | Compose 编排、HTTPS 代理、Keycloak 身份配置及测试镜像 |
| contracts/、packages/ | 共享 API 快照与契约；前端类型由后端 OpenAPI 生成 |
| scripts/、tests/ | 启动与维护入口、共享浏览器测试和可分发测试样本 |
| docs/ | 当前操作文档、状态说明，以及保留原路径的历史设计和验证记录 |

平台使用四个独立 PostgreSQL 数据库和应用角色：治理、PostGIS、月分区时序、资料。Jena Fuseki/TDB2 保存受控 RDF/OWL/SHACL；S3 保存私有原件。UUID、稳定 IRI、不可变事件和后端当前授权连接各域。外部 PostgreSQL/MySQL 是只读来源。Keycloak 的生产编排使用独立身份数据库；原生验收身份服务的隔离方式另有明确记录。

从仓库根目录执行以下已有入口。Python 使用 3.12.7，Node 使用 24.22.0；依赖和服务版本分别锁定在 `backend/requirements.lock`、两个 npm 锁文件和 `infra/versions.lock.json`。

```sh
python -m venv .venv
# Windows 下将 .venv/bin/python 替换为 .venv/Scripts/python.exe
.venv/bin/python -m pip install -r backend/requirements.lock
npm ci
npm ci --prefix frontend
.venv/bin/python scripts/export_openapi.py --check
npm run api:check
npm --prefix frontend run typecheck
npm run web:test
npm run web:build
```

修改后端契约后运行 `python scripts/export_openapi.py`、`npm run api:generate`，提交生成文件。迁移配置在 `database/alembic.ini`；`python -m alembic -c database/alembic.ini heads` 可离线检查迁移头。

具备 Docker Compose 环境时，`python scripts/dev.py prepare` 生成本地环境文件和证书，`python scripts/dev.py up` 启动服务，`python scripts/dev.py test` 使用独立测试项目。默认仅代理公开本机 HTTPS 端口；持久卷与外部数据库均不是源码。迁移需要独立 owner 凭据，详见[数据库说明](database/README.md)及[环境运行手册](docs/operations/environment.md)。当前主机没有 Docker 引擎；配置验证与原生服务测试不能替代容器运行及实际断网部署验收。

环境文件、密钥、运行数据库、日志和依赖不应提交。仓库保留字体和地图样本的许可证；`tests/fixtures/maps` 中的 MBTiles/PMTiles 是有意分发的合成测试样本。历史文档中的 `apps/api`、`apps/web` 路径分别对应现在的 `backend`、`frontend`；完整路径映射见快照状态文档。

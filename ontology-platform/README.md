# 梁子湖本体数据库：工程与开发指南

本目录是当前维护工程。项目能力、界面截图和最新数据规模见[仓库首页](../README.md)；日常使用见[快速上手](docs/local-server/快速上手.md)与[使用指南](docs/local-server/使用指南.md)。

当前已验收的交互入口是 `local_server/` 提供的本地 HTTP 服务，以及 `docs/fish/ontology-review/` 中的本体目录、平面地图和关系球。`backend/`、`frontend/` 保留完整业务平台的后端及 React 工作台开发模块，使用独立依赖与部署配置。

## 选择运行入口

| 目的 | 入口 | 前提 |
| --- | --- | --- |
| 使用当前本体库、CAD 地图和关系球 | `infra/local-server/local-server.cmd` | 已准备私有配置、PostgreSQL/PostGIS、Java/Fuseki 和发布数据。 |
| 查看历史公开 CSV 审查快照 | `scripts/serve_ontology_review.py --offline` | Python 标准库；读取仓库中保留的历史导航。 |
| 开发语义治理、OIDC、React Studio 或完整平台 | `backend/`、`frontend/`、`scripts/dev.py` | 对应开发依赖、服务环境、账户与权限配置。 |

下面命令均从 **`ontology-platform` 目录**执行；从仓库根目录开始时，先运行 `cd ontology-platform`。

## 轻量本地服务器

### 版本与环境准备

| 组件 | 锁定/验收版本 |
| --- | --- |
| Python | 3.12；当前验收解释器 3.12.7 |
| PostgreSQL / PostGIS | 17.11 / 3.6.2 |
| Apache Jena Fuseki | 6.2.0 |
| Java | 21；原生 runner 需要包含 `jdk.compiler` 的 JDK/JBR |
| 前端 | 原生 JavaScript、SVG 平面地图、Canvas 球面投影 |

版本与镜像信息见 [versions.lock.json](infra/local-server/versions.lock.json)，Python 依赖见 [requirements.lock](infra/local-server/requirements.lock)。这套轻量入口不要求启动完整平台的身份服务、S3 或 React 构建链。

Windows 首次准备 Python 环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File infra/local-server/setup.ps1
# 若 Python 不在 PATH 中，使用 -Python 指定 Python 3.12 可执行文件。
```

Linux 提供对应入口：

```sh
sh infra/local-server/setup.sh
```

安装脚本只创建 `.venv-local-server` 并安装依赖。数据库工具、新部署身份、私有配置、空库初始化或已有数据恢复仍需按[部署与换机](docs/local-server/部署与换机.md)完成。新机器使用 `scripts/provision_local_server.py` 准备全新空环境：新空服务走 `init → start`；恢复备份走 `restore → place-restored-assets → start`，恢复前不先执行 `init`。不能对已有数据目录重新初始化。

### 日常管理

```powershell
.\infra\local-server\local-server.cmd start
.\infra\local-server\local-server.cmd status
.\infra\local-server\local-server.cmd restart
.\infra\local-server\local-server.cmd stop
```

CMD 无参数运行会启动并打开首页；PowerShell 和 Linux 入口无参数默认 `status`。Linux 启动命令为 `sh infra/local-server/local-server.sh start`。

默认首页为 `http://127.0.0.1:8792/`，本体浏览器为 `/ontology/`。只有已恢复或导入数据并激活发布后，才能读取对应实例与地图；空库启动不会自动生成已验收数据。当前未安装开机自启。

默认私有配置为 `.runtime/local-server/config.json`；入口可通过 `LZO_LOCAL_CONFIG` 指向另一份配置。私有环境文件由配置加载，连接与写入令牌不应写进 README、命令参数或 Git。修改位置和端口时遵循配置验证与部署归属检查。

## 数据接收、校验与发布

### CSV 完整批次

服务器首页支持提交 UTF-8 CSV 或 ZIP 并跟踪后台任务。原始记录、规范实例、属性与关联分别保存；导入过程完成 SQL/RDF 回读及约束核验后，才发布可浏览版本。

普通 CSV 流程按完整独立批次发布。仅上传一张新的 GIS 表不等于自动补充当前全量本体；更新已审查 CAD 资料请使用下面的组合发布入口。既有完整 CSV 的字段、数据性质和关系核验见 [CSV 批次说明](docs/csv-batch/README.md)。

### 固定来源 CAD/GIS 组合发布

以下示例需要已准备好的私有配置与受支持的目标环境。批次目录应与已有批次分开：

```powershell
.\.venv-local-server\Scripts\python.exe scripts\download_cad_sources.py --manifest docs\local-server\gis-source-audit-2026-11-16.json --destination .runtime\cad-gis\inputs
.\.venv-local-server\Scripts\python.exe scripts\prepare_cad_gis.py --inputs-dir .runtime\cad-gis\inputs --output-dir .runtime\cad-gis\prepared
.\.venv-local-server\Scripts\python.exe scripts\import_cad_gis.py --config .runtime\local-server\config.json --bundle .runtime\cad-gis\prepared\bundle.json
```

1. 下载固定提交文件，校验 Git blob、大小与 SHA256。
2. 保存完整来源表/行/几何，生成候选对象、测量、空间关系及不重复绘制的显示面片。
3. 写入独立 SQL schema 与 RDF 图，核对完整字段、几何与 RDF 词项并执行 SHACL。
4. 保留当前完整历史导航，生成新地图和球网，最后切换 active 发布。相同已发布批次重跑验证幂等性。

当前 CAD 写入保护针对已审查本机目标 PostgreSQL 25459、Fuseki 23059；换机或更换端口后必须同时审查目标保护，不能把示例命令直接指向任意环境。详细限制与失败处理见[使用指南](docs/local-server/使用指南.md)。

公开导出使用 `scripts/export_cad_gis_public.py`，只输出明确允许公开的字段。完整原件和来源记录保留在私有批次，不能将公开小包当作全库恢复包。

## 身份、RDF 与空间数据契约

| 内容 | 规则 |
| --- | --- |
| 实例身份 | 稳定 IRI 同时用于对象详情、地图选择和关系导航；按明确来源证据关联，不按名称相似就合并。 |
| 本体结构 | OWL/RDFS 类型层级、`rdf:type`、类型化属性及对象关系；SHACL 验证约束。 |
| 地图 | `lzo-spatial-map/2`；面从 `display_features` 绘制，点/线使用 `features`；无位置对象在 `unlocated`。 |
| 旧地图 | 保留 `farm-local-map/1` 的历史图纸坐标视图，与当前候选经纬度视图区分。 |
| 球网 | `lzo-ontology-network/1`；类型节点、本体定义边、实例聚合边与独立计数，实例关系按需分页。 |
| 发布一致性 | 读取固定 `release_id`，分页游标绑定该发布；切版本清除旧选择与迟到请求。 |
| 数据性质 | 保留合成、再分析、候选和未核实标记；来源值与几何派生计算值分开，未知深度不补造。 |

新 CAD 数据的原始坐标参考仍标为 `UNKNOWN`，候选显示为 `display_srid=4326`；这不构成现场精度认可。摄像头图纸符号、设施文字锚点和真实设备身份也分别保存。来源与计数说明见 [CAD 数据包](datasets/cad-gis/README.md)。

## 本地 API 接入

下面为轻量服务器 `/api/v1` 接口；完整平台 `backend/` 的会话与权限接口是另一套运行配置。

| 路径 | 参数与结果 |
| --- | --- |
| `/api/v1/status`、`/ready` | 服务、发布和依赖就绪状态；不代替完整验收。 |
| `/api/v1/releases` | 当前及历史发布，使用 `limit`、`offset` 与返回的 `next_offset`。 |
| `/api/v1/manifest` | 类型、统计与发布信息。 |
| `/api/v1/children` | `parent`：本体 IRI，返回直接下级。 |
| `/api/v1/instances` | `class`、`limit`、`cursor`：类型及其下级实例分页。 |
| `/api/v1/resource` | `iri`：实例属性及关系；正/反向分别用 `cursor`、`incoming_cursor`。 |
| `/api/v1/maps` | 当前地图、图层、候选及待定位对象。 |
| `/api/v1/network` | 本体类节点和关系聚合。 |
| `/api/v1/network-relations` | `source`、`predicate`、`target`、`limit`、`cursor`：具体实例关系分页。 |
| `/api/v1/export` | `class`、`format=json\|csv\|rdf`、`limit`、`cursor`：公开规范三元组分页。 |
| `/api/v1/jobs/<任务ID>` | 导入任务状态。 |

读取业务数据时显式传入 `release_id`，IRI 使用 URL 编码。JSON 导出读取 `next_cursor`，CSV/RDF 读取响应头 `X-Next-Cursor`，直到没有下一页；RDF 格式为 Turtle。CSV 对可能执行公式的起始字符做转义，需要精确 RDF 词法值时使用 JSON/RDF。

查询是公开业务视图；服务还提供受写入令牌保护的批次导入。请求方式、上限和认证说明见[使用指南](docs/local-server/使用指南.md)。只读接口不开放任意 SQL/SPARQL 管理命令或完整原始载荷。

## 工程目录与修改入口

| 目录/文件 | 作用 |
| --- | --- |
| `local_server/` | 轻量 HTTP、任务处理、配置、版本发布、备份恢复及公开查询。 |
| `local_server/spatial_source.py`、`spatial_geometry.py` | 来源完整接收、空间计算、质量处理和显示几何。 |
| `local_server/spatial_rdf.py`、`spatial_publish.py` | CAD RDF、约束、实库回读和完整组合发布。 |
| `local_server/network.py` | 本体定义和实例关系聚合为球网读模型。 |
| `docs/fish/ontology-review/` | 本体浏览器 UI；`spatial-map.mjs`、`ontology-sphere.mjs`、`sphere-math.mjs` 为地图、球网和交互数学模块。 |
| `datasets/` | 图纸、CAD、旧地图和关系网公开数据及摘要。 |
| `infra/local-server/` | 启停入口、依赖锁定、配置示例和轻量 Compose。 |
| `tests/local_server/` | 来源、发布、读取、版本、恢复与路径约束测试。 |
| `backend/`、`frontend/` | 完整业务后端和 React 工作台开发模块，详见各目录 README。 |
| `database/` | PostgreSQL 迁移和 Jena 配置；[数据库文档](database/README.md)。 |
| `contracts/`、`packages/` | OpenAPI、类型与共享契约。 |
| `docs/` | 当前指南、来源说明、设计、历史状态和验收证据。 |

实际服务读取私有配置指定的 `review_dir` 和发布目录。修改仓库 UI 后，部署时需要核对实际使用的文件位置，并验证所选发布；不能只修改仓库副本就宣称运行服务已更新。

## 开发检查

### 轻量服务与本体浏览器

在专用开发/测试环境中，使用当前 CI 的依赖组合准备 Python 测试工具；运行依赖锁文件本身不包含 `pytest`：

```powershell
.\.venv-local-server\Scripts\python.exe -m pip install -r scripts/requirements-ontology-review.txt -r infra/local-server/requirements.lock pytest==8.4.2
.\.venv-local-server\Scripts\python.exe -m pytest -q --tb=short tests/local_server
node --test docs/fish/ontology-review/model.test.mjs docs/fish/ontology-review/spatial-map.test.mjs docs/fish/ontology-review/ontology-sphere.test.mjs docs/fish/ontology-review/sphere-math.test.mjs
```

Store 等原生用例需要显式配置的隔离测试库；缺少条件时可能跳过，应查看测试结果，不能把跳过算作实库通过。测试不得指向实际业务数据库。Node 版本沿用项目锁定的 24.22.0。

2026-11-24 已补跑真实 SQL/RDF 回归和视频解码，汇总为 1546 通过、0 失败、4 跳过；跳过项需要 Windows 符号链接创建权限，完整平台 integration 尚需专用 OIDC/S3/多库环境。原生夹具现在要求 `LZO_NATIVE_TEST_MANIFEST` 和显式测试 DSN，拒绝正式端口及不一致目标，不再回退读取业务配置。各范围、跳过原因、修复和四阶段实测见[回归与性能报告](docs/local-server/python-regression-performance-20261124.md)，重测方法见[性能测试指南](docs/local-server/性能测试指南.md)。

真实浏览器检查由 `scripts/check_gis_sphere_browser.mjs` 执行，需要已发布的本地服务、Playwright 模块及可用 Chromium；它会验证交互并生成报告/截图。仓库布局与公开分片验证入口为 `scripts/check_repository_layout.py`，其既有统计针对历史 CSV 快照，不能代替新 GIS 实库验收。

### 完整平台开发模块

使用 Python 3.12.7 和 Node 24.22.0，分别安装独立依赖。下面为已提供的开发入口，不是本机轻量数据库的一键部署流程：

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

修改完整后端契约后，用 `scripts/export_openapi.py` 和 `npm run api:generate` 更新快照与前端类型。`api:check` 检查完整平台 OpenAPI 派生类型，不覆盖轻量 `local_server` HTTP 接口。部分检查还需要相应私有环境或测试配置，详见[后端指南](backend/README.md)、[前端指南](frontend/README.md)和[环境运行手册](docs/operations/environment.md)。

## 备份、恢复与换机

备份必须包括所有必要 SQL 数据库、完整 RDF 数据集、发布导航和私有来源资产。CAD 批次的 `cad-imports` 目录已经加入备份/恢复约定；恢复位置应保持在新数据根的同名目录，保证来源引用可解析。

目前有同机完整恢复和换目录重启证据；第二台物理机、跨 OS 和 Docker 恢复未完成实际验收。最新 CAD 导入后的全库备份还需要实际生成并校验。操作必须使用私有配置和新空恢复目标，具体步骤见[部署与换机](docs/local-server/部署与换机.md)。

## 状态与证据

- [当前进度总结](docs/status/2026-11-18-project-progress.md)：已完成工作及剩余事项。
- [GIS/本体关系球交付](docs/local-server/gis-sphere-acceptance.md)：真实 PostgreSQL/PostGIS、RDF、SHACL、历史保护及浏览器验证。
- [本机服务器恢复记录](docs/local-server/server-readback.json)：备份、恢复、迁移和实际运行边界。
- [完整 CSV 批次](docs/csv-batch/README.md)：字段、关系、数据性质及完整回读。
- [历史本体审查入口](docs/fish/ontology-review/README.md)：仓库内五图快照与来源证据。
- [多存储验收与性能边界](docs/database/acceptance.md)：完整平台原生验证及尚未通过的性能范围。

最新地图功能验收日期为 2026-11-16，Python 补测和 README 更新日期为 2026-11-24。各报告仅证明其明确执行的范围，不代表已完成正式生产采纳、现场测绘、真实设备接入或完整产品验收。项目成果按[GitHub 同步约定](../GITHUB_SYNC.txt)同步；私有配置、原件、活动库、日志、备份和依赖不进入仓库。

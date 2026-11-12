# Local Ontology Server Implementation Plan

> **For agentic workers:** 使用并行独立模块实施、测试先行与最终独立审查；用户已批准方案并要求开始搭建和编写指南。

**Goal:** 将现有本体数据整理为本机真实运行、可配置、可备份恢复和可迁移的轻量服务器。

**Architecture:** 独立 local_server 包管理配置、持久化任务/发布、导入投影、HTTP 和备份；保留旧原生来源环境，在独立新环境验收。复用现有纯 CSV/RDF 模型及公开浏览器，避免夹带正式平台 WIP。

**Tech Stack:** Python 3.12、psycopg、httpx、RDFLib/pySHACL、PostgreSQL/PostGIS、Fuseki/TDB2、HTML/JS、可选 Docker Compose。

**Spec:** ../specs/2026-11-12-local-server-design.md

## Global Constraints

- 发布基线 b93659aaa1b6075a40296400ff9f74332f062439；GitHub 目标 Public lianggeming14/liangzihu-ontology-traceability/main。
- 原 PG25449/Fuseki23049 保留，不接管其 PID；新实际目标建议 PG25459、Fuseki23059、HTTP8792，以实际端口检查为准。
- 默认 127.0.0.1、单导入并发、64MiB 上传上限；配置可调整。无凭据、数据库、备份和原始运行资产进入 Git。
- 仅新 local_server/、tests/local_server/、config/local-server*、infra/local-server/、scripts/run_local_server.py 与相关文档/CI/入口属于本轮。
- 先测试观察失败再实现；通过/失败/跳过及真实库/fixture 性质分别记录。

## Review Focus

1. 路径/ZIP/Host/Origin 或任意 IRI 越界不能泄露源文件与 raw 记录。
2. 重复提交、worker 失联/抢占、SQL 成功但 RDF 失败不能误发布或重复数据。
3. 多次读取与翻页必须固定发布版本，不能混合 SQL/RDF/导航版本。
4. 备份必须包含独立 CSV schema、所有 RDF 图和私有原件；恢复错地址或缺件要拒绝。
5. 大数据导出与恢复必须限内存/检查磁盘，换路径后不依赖旧 worktree/PID。

## Task 1: configuration and persistent control plane

Files: local_server/{__init__,config,store}.py; tests/local_server/test_{config,store}.py; config/local-server.example.json.

Interfaces: Config.load(path) 提供 root/data_dir/review_dir/mapping_file/host/port、SQL admin/api/worker连接、fuseki_url、limit/backup/runtime 字典。Store(config, role='api') 管理 ensure_schema(), submit_job(source_path,source_sha256,mapping_sha256), get_job/list_jobs, claim_job(worker_id), heartbeat/check_lease, fail_job, finish_job、register_release/get_release/active_release/publish_release。ID 使用 UUID，记录 JSONB，返回 dict；阻止过期租约发布。配置与方法契约允许实施者对清晰命名作统一补全并及时通知依赖方。

- [x] 写配置和任务状态/幂等/租约/原子发布测试，观察缺失功能失败。
- [x] 实现配置校验、受限连接、控制表与固定版本状态；测试通过。
- [x] 在新隔离实库核对权限、重复入队和抢占边界，记录证据。

## Task 2: generic batch importer and worker

Files: local_server/{importer,rdf,worker}.py; tests/local_server/test_{importer,rdf,worker}.py; config/local-server-mapping.json.

Consumes: Config、Store 上述契约；复用 scripts/csv_batch_model.py、fish_rdf_sample.py/validation.py。Produces: process_job(config,store,job,worker_id) 分阶段完成独立 SQL schema、新 RDF 图、校验、公开导航及 release；run_worker(config,once=False)。ingest API 只登记任务，worker 执行写入。

- [x] 写 ZIP/CSV、类型、未解析关系、命名空间与精度测试，观察失败。
- [x] 实现版本化 mapping、幂等输入、事务暂存及可重入阶段；实现有界 RDF 投影/回读验证和导航。
- [x] 写 SQL/RDF 失败及租约失效不激活测试，红绿后验证真实新小批次、重复和错误批次。

## Task 3: complete portable backup and restore

Files: local_server/{backup,integrity}.py; tests/local_server/test_{backup,integrity}.py.

Interfaces: create_backup(config,destination,*,source_options=None)->manifest path；verify_backup(manifest)->dict；restore_backup(config,manifest,*,target_options=None)->dict。显式来源/目标多库连接与工具路径，不打印 URL；恢复前拒绝源目标相同、非空目标和错误 hash。备份清单结构自描述包含数据库、schema、RDF、资产、软件版本与文件摘要；任务/发布元数据包含在其控制 schema 中。

- [x] 写全 schema 范围、压缩完整性、错目标/缺件/空白节点与类型化词法测试，观察失败。
- [x] 实现压缩逻辑 SQL 备份、完整 RDF 流式校验、资产清单和新目标恢复。
- [x] 对实际来源全量捕获；新目标恢复并完整比对，资源限额/失败状态记录清楚。

## Task 4: HTTP service, lifecycle, packaging and simple guide

Files: local_server/{http,query,lifecycle,cli}.py; local_server/web/*; scripts/run_local_server.py; tests/local_server/test_{http,query,lifecycle}.py; infra/local-server/*; docs/local-server/*; root/平台 README；.github/workflows/repository-check.yml.

Consumes: Tasks1-3 的 Config、Store、worker 与 backup。Produces: `python scripts/run_local_server.py --config PATH init|start|stop|restart|status|serve|worker|backup|verify-backup|restore|bootstrap-release`，Windows .cmd/PowerShell 与 Linux shell 操作入口；HTTP健康/任务/导入/查询/导出，中文控制台、旧浏览器兼容入口，轻量 Compose。

- [x] 写 HTTP输入、游标/发布、IRI范围/权限、生命周期归属、配置与日志测试，观察失败。
- [x] 实现 API、后台启动/监管、查询和导出；默认本机、写 token、专用账号，日志轮转。
- [x] 完成真实后台服务、导入查询/导出、停止重启、真实 Chrome验收及中文简单指南。
- [x] Compose配置/构建环境能执行则验证；不能执行则如实保留未执行状态，实际原生服务仍须可用。

## Task 5: final independent review and publication

- [x] 新服务全部测试、旧发布范围测试、实库数据保护/备份恢复/输入输出证据及指南步骤核验。
- [x] 独立审查并修复阻断问题；扫描精确交付文件（包括压缩文件解包扫描）和凭据。
- [ ] 同步目标 main，不 force push；核对全部远端文件及 Actions；交付实际运行地址与指南。

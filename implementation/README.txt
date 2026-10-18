梁子湖农业本体数据库 · 本地工程版 v0.4.0
更新：2026-10-19

当前实现
--------
数据库负责本体定义、来源记录分类与映射、约束校验、身份与关系存储、证据历史、检索和对外输出。
v0.4.0 按已接受的梁子湖结构映射表，实现了来源记录到本体实体、属性和显式外键关系的接入后端。
目录覆盖 190 表、2114 字段、555 外键；启用 122 个业务来源记录类、979 个属性、409 个外键映射。
使用当前模型实施，运行无需 Kimi。图像识别、农业判断、模型执行和设备控制交给外部服务。

先看这两份文档（路径相对项目根目录）
----------------------------------
交付文档/梁子湖本体数据库后端操作说明书_v0.4.docx
  后端调用链、代码阅读顺序、本体与映射修改、接口、批量导入、测试、备份和生产验收边界。
交付文档/原梁子湖项目数据库分析与本体库比较报告.docx
  原平台数据库结构、源码逻辑、特点、来源证据与本体库比较。
适配器详细操作与命令：integrations/liangzihu/README.txt。
本轮权威验证：../outputs/backend-integration-20261019/final-tests.xml 与 verification.json。

启动与现有数据
--------------
在 implementation 目录安装 requirements.txt 后运行：
  python -B -X utf8 run_server.py --no-seed --open-browser
地址：http://127.0.0.1:8787/ 。--no-seed 避免再次加载演示数据，--no-demo-login 禁用本机演示登录。
“启动系统.cmd”为本地便捷入口；需要严格不加载演示数据时使用上面的显式命令。
这是 Flask 本地开发入口；生产部署、TLS、身份集成和容量验收仍需单独完成。

本次实际升级沿用 data/agri.db，新增 005，保留原 001—004 迁移历史和已有行。
已完成升级前在线备份与预检，应用 v0.4.0 已启动。当前共 23 个包，其中新增 18 个来源领域包；
登记 1 个覆盖 122 表的来源映射。原 17 个实体完整保留，没有把新合成样例或生产记录导入活动库。
这些是本机升级结果，不表示全新安装启动时自动生成 23 个包；新环境需显式安装适配器定义。

梁子湖来源接入
--------------
来源结构固定为公开原项目提交 9995fc20cd84093adcaa3fab954ffe9d08b9f45a。
来源身份使用“租户 + source_id + 来源表 + 规范主键”，对应的本体 UUID 由系统生成。
SQL 导出自动带出源主键，管理员不需要手编本库 UUID；名称可改，身份不按名称猜测或合并。
objects.kind 保留农场、田块、水塘、渠道、设施类别；其他作物和水产种类可沿来源 species 字段扩展。
这些是来源记录类，不自动宣称与其他本体的同名类等价。

主要文件：
- integrations/liangzihu/source-profile.json：122 表类/属性/外键映射。
- integrations/liangzihu/package-bundle.json：18 个已验证领域包，支持 implementation 独立部署。
- integrations/liangzihu/coverage-manifest.json：各表、字段与关系的支持/延期/拒收原因。
- integrations/liangzihu/readonly-export-core.sql 与 readonly-export.sql：源库只读白名单 JSONL 导出。
- ops/import_liangzihu.py：通过认证 HTTP API 预检、安装、分批和应用，不直接写活动数据库。

首次使用合成样例预检（不会留存对象）：
  python ops/import_liangzihu.py preview --source-id synthetic-liangzihu --input integrations/liangzihu/synthetic-core-example.json --install-definitions
需通过安全的终端环境提供 AGRI_API_TOKEN，账号需具有相应管理员权限；令牌不放在命令或项目文件中。
--install-definitions 将领域包、映射和当前批次一起预检；只有显式增加 --apply 才提交。
单批 1—100 条，请求不超过 2 MiB。大文件用 plan 按外键依赖和强连通分量分批，
再用 apply-plan 检查计划；正式应用需 --apply，顺序预检和提交，失败立即停止并保留回执。
整个计划不是一个事务；保留原批次和幂等键可重放已提交请求，修订需当前 expected_revision。
真实导出、计划、绑定快照和回执放 runtime/source-imports/；该专用目录被 Git 忽略。
SQL 使用 psql --output 写 UTF-8 文件，避免旧 PowerShell 重定向编码变化；详见适配器说明。

本体与数据约束
--------------
领域包按精确版本登记；显示名、说明与稳定 package_id/type_id/property_id/predicate_id 分离。
显示名可经标签接口修订并保留审计；结构变化要发布新版本，不能原地替换已发行定义。
属性定义适用类、用途、类型、单位、枚举、范围和数量。API、人工表单与接入共用约束层。
来源适配器严格处理 UUID、十进制数、日期、带时区时间及文本数组；不执行任意转换代码。
缺字段表示部分更新，null 按明确规则清除属性或可空关系；未知和敏感字段拒收，复杂字段显式延期。
HTTP 严格 JSON 解析拒绝顶层/嵌套重复键、NaN/Infinity 及指数溢出产生的非有限值；
这些无效请求不会写库或占用幂等键，防止静默覆盖与非有限数传播。
来源属性留存为可追溯快照，不自动成为原生观测或已采纳断言；生产、测试与合成数据性质分开。
原 SQL 的所有 CHECK/触发器/唯一约束并未全部复制；删除来源记录也不会自动删除本体实体。

关系、证据和对外取数
------------------
FK 形成有方向和来源证据的 candidate 关系。外键不是空间包含、因果、质量合格或执行成功证明。
修订保留绑定历史、实体快照与关系变化；证据包暴露 source_snapshots，明确未作为推理前提采纳。
/ontology/relations 默认查 accepted 且按 valid_at 筛选；核对来源关系时可用 status=candidate/all。
HTTP /ontology/graph 由网络视图构建，可能展示不同状态，必须检查边的 status；显示不代表已采纳。
图、历史和证据查询都有预算或分页，消费者须处理 has_more、truncated、gaps 与有效时间。

GET /api/v1/openapi.json 是最新接口契约，共 73 项 API 操作；31 份 JSON Schema 定义输入。
新增 integration/profiles、bundles、bundles/preview、preview、batches、bindings。
bindings 的 projection=identity 仅返回身份与修订元数据，便于增量计划，不下载完整来源载荷。
保留 ontology/packages、package-labels、properties、entities、relations、object-sets、graph、export，
以及 ingestion/mappings、preview、receipts、manual、assets 和 evidence、observations、assertions。
/trace/changes 提供租户有序 outbox，消费方按事件 ID 去重并保存游标；当前没有 webhook/ACK 运营服务。
JSON-LD/Turtle 仅支持本项目交换配置，不是通用 OWL/RDF 推理或任意互转。

原件、人工表单及兼容功能
----------------------
原有本体管理、按类输入属性的对象/人工记录表单、对象集与结构化接入回执继续使用。
结构化记录与来源表批量适配器是不同契约：前者接收已定义的观测/断言/事件，后者保留源表身份与 FK。
新上传仅做原件完整性、载体格式及大小检查，不执行图像指标、视频抽帧或模型识别。
外部模型结果经候选断言记录模型版本与输入证据，数据库不判断农业结论真假。
设备网关、采集计划、物料库存、消费者溯源码/发布页面和旧媒体代码保留为兼容扩展，不默认启动网关。

验证、维护与当前边界
------------------
本轮权威结果：378 passed、0 failed/error、180 skipped。
跳过包括 178 项 PostgreSQL、1 项旧 FFMPEG 解码、1 项 Windows 符号链接权限；不能将跳过计为通过。
实际 loopback HTTP 预检 11 条 synthetic 记录、22 条关系，回滚后活动库仍为原 17 个实体。
旧浏览器 38 项检查仅标记 historical_v0.3，本轮没有重新执行；详细记录见验证结果.txt。

数据库来源身份绑定已 implemented_locally；认证主体/生产令牌到 source_id 的服务端强绑定尚未完成。
目前有基于已核对结构的确定映射，没有真实生产数据导入、PostgreSQL 或现场验收，也未验证生产 TLS、
对象级授权、容量与完整恢复。SQLite 本地验证不能替代这些门槛；database-gate.json 的生产结论仍未通过。
使用 ops/backup_sqlite.py 备份/验证/恢复到新文件；完整恢复还需私有原件、契约/迁移/代码版本及受控配置。
没有通用 OWL/SHACL、类继承、自动实体合并、完整双时态重建、因果判断或设备控制。

本轮 Word 已制作，ReportLab 测量布局预览已检查；原生渲染不可用，未宣称 Word 原生分页验证通过。
DATA_INTAKE_GUIDE.txt 保留结构化接入指南；DATABASE_CORE_V0.3.txt、v0.3 ZIP 和总体 Word v1.1 为历史资料。
当前状态以 v0.4.0 手册、IMPLEMENTATION_STATUS.json 和 outputs/backend-integration-20261019 为准。

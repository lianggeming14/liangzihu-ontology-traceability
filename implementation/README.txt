梁子湖农业本体数据库 · 本地工程版 v0.3
更新：2026-10-14

本次改版将主流程收敛到数据库本职：本体定义、信息分类、来源映射、约束校验、原件和血缘存储、检索及对外数据输出。识别模型、农业判断、视频分析和设备执行交由外部服务；数据库接收其有版本、有来源的结果，保留候选状态与证据。

启动
在 implementation 目录安装 requirements.txt 后执行：
  python -B -X utf8 run_server.py --open-browser
本机地址：http://127.0.0.1:8787/
现有电脑也可双击“启动系统.cmd”。--no-demo-login 禁用本机演示登录，--no-seed 不加载合成数据，--port 改端口。当前为 Flask 本地开发入口。

升级沿用 data/agri.db，新增003、004迁移，保留001/002校验及历史记录。不删除数据库、不替换旧本体包定义。幂等演示加载保留旧示例，另加“农业基础数据本体（合成示例）”与“映射试用田块（合成示例）”。Kimi已退出运行流程。

本体管理
1. 创建本体：名称、说明、稳定package_id、namespace、版本，结构化定义类、属性和关系。
2. 对象分类：为已有UUID赋语义类及有效区间；身份类型和语义类分别管理。
3. 关联对象：指定谓词、方向、端点、有效时间、证据；检查适用类与身份类型。
4. 对象分组：动态条件集合或固定成员快照；登记集合不会创建新实体。
卡片显示可读名称和说明，详情展示类/属性/关系表；JSON保留为高级入口。可改本体、类、属性和关系显示名，expected_revision检查并发并保留审计；标识、定义hash和语义结构不随改名变化。结构变化发布新版本。

属性字典与统一校验
属性定义适用类、用途(attribute/observation/assertion)、值类型、单位、枚举、范围、数量及对象属性必填。通过对象有效类查询可用属性；观测不再任意填写未登记指标。直接API、人工表单和兼容批量入口调用同一约束层。歧义用package_id/version/property_id精确引用解决，不按名字猜测。旧记录保留并标legacy_unvalidated，不冒充已验证数据。

数据接入
登记来源映射 → 预览样本 → 接收信封 → 查看回执 → 修订映射版本并重试失败回执。
四个维度分别声明来源类别、载体格式、记录类型和本体身份。字段路径、单位缩放、枚举和时区采用显式转换。映射绑定source_id/source_category/content_type/schema_version/record_kind，不执行任意代码。
合法信封生成不可变原文及SHA-256；status为needs_mapping、validation_failed或stored，HTTP 200不代表目标数据入库成功。预览回滚全部临时记录；重试保留原文和各次attempt，已stored回执不重复生成业务行。来源记录ID冲突拒绝，写请求需要稳定Idempotency-Key。

原件与外部结果
新上传只做文件签名、图片结构和大小约束检查；不生成缩略图、亮度指标或视频抽帧。原件完整性、载体分类、外部处理状态分别表达。原件可下载不等于内容真实或分析完成。载体与明确声明冲突标待映射；损坏、缺失或撤回不能作为当前可用资料。撤回原件拒绝下载。
外部模型经新接入流程只能生成候选断言，并记录producer名称/版本与输入证据。无已登记属性映射的自由陈述可保留候选，不能直接采纳。数据库不判断农业结论真假。

对外接口
GET /api/v1/openapi.json 为最新接口契约。
核心：ontology/packages、package-labels、properties、entities、type-assignments、relations、object-sets、graph、export；ingestion/mappings、preview、receipts、receipts/{id}/retry；ingestion/manual、assets；evidence、observations、assertions、inference/bundles/{id}。
原有 /trace/changes 提供租户有序outbox，供溯源系统及其他代码增量读取。消费方按事件ID去重并保留游标，当前没有webhook/ACK投递服务。
图提供身份、空间、生产、物料、事件、观测、断言、证据、设备等维度；调用方必须处理truncated/gaps。JSON-LD/Turtle仅支持本项目交换配置，不是任意OWL/RDF通用互转。

兼容扩展
原有摄像头/闸门网关、采集计划、物料批次库存、消费者溯源码与发布页面保留在“兼容扩展”，供已有演示和接口继续使用。本轮不扩展这些业务，也不默认启动网关。旧媒体分析代码及预览读取仅为兼容，不在新上传主流程中执行。扩展配置参考 DEVICE_PLATFORM_MAPPING.txt；数据库新版流程以 DATA_INTAKE_GUIDE.txt 为准。

备份与验证
使用 ops/backup_sqlite.py 的backup/verify/restore命令，恢复到新文件。完整恢复还须备份私有assets、匹配契约/迁移/应用版本及受控配置。公开源代码包不含运行数据库、原件或凭据。
  python -m pytest tests -q
  python ops/export_contract.py
验证结果.txt、IMPLEMENTATION_STATUS.json记录本轮实际通过/跳过结果。浏览器桥接真实Flask与隔离SQLite的验证同本机HTTP验证分别说明，不替代生产验收。

现有边界
SQLite为已验证本地后端；PostgreSQL迁移和测试入口已提供，实库未验收。未连接真实梁子湖现场或外部溯源平台；没有生产身份、TLS及对象级授权。source_id与映射匹配不证明发送方真实性，生产需由服务端身份绑定来源。
没有类继承/通用OWL推理、完整双时态快照、自动实体合并、因果判断或设备控制。required仅约束对象属性；同一对象/包版本/类仅一个连续有效区间。图是有界当前视图。原件与数据库尚无分布式事务、自动孤儿文件清理或生产生命周期管理。

DATA_INTAKE_GUIDE.txt：管理员和接入人员操作步骤及JSON示例。
DATABASE_CORE_V0.3.txt：职责边界、五大重点、架构与验收约束。
总体Word v1.1为历史完整规划，本版范围和实现状态以上述v0.3资料为准。

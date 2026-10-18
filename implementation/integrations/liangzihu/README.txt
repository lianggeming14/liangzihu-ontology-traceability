梁子湖来源记录接入适配器 v1.0.0
==============================

用途与边界
----------
依据用户已接受的《梁子湖项目_本体与关系全量结构导出.xlsx》接入原项目来源记录。
固定源码提交：9995fc20cd84093adcaa3fab954ffe9d08b9f45a。
全量目录：190 张表、2114 个字段、555 条显式外键。
本次启用：122 个业务来源记录类、979 个属性、409 个显式外键映射；另有 2 个关系包辅助类型。
一条来源记录对应一个独立、本库生成 UUID 的本体实体。来源主键不替代本库 UUID。
objects.kind 保留 farm/field/pond/channel/facility，devices.kind 保留 physical/gateway/camera_channel；
生产批次 species 是来源自由文本，其他作物、水产种类不被限定为水稻、小龙虾。
来源记录类并不自动等同于现有 core 的 farm/field/pond；跨本体等价关系需另行审核。
observations 来源表可以形成可追溯的来源记录实体，但不会自动成为本库原生 Observation；
指标、单位、事件时间和证据语义需采用已有结构化接入契约显式配置，不能把每个值当成可信结论。
本适配器不识别图像、不判断病害、不调用外部模型、不操作闸门，不把原系统用户角色转成本库权限。

文件导航
--------
source-profile.json：可安装、不可变版本的类/属性/FK 映射。source_id 在运行时显式设置。
package-bundle.json：18 个经过原导出 SHA256 验证的领域包，供 implementation 独立部署使用。
coverage-manifest.json：190 表、2114 字段、555 关系逐项状态、原因、固定提交源码位置。
artifact-manifest.json：产物和输入 SHA256；变更结构后应重新生成并审查。
readonly-export.sql：122 张启用表的只读白名单 JSONL 导出，使用数据库内一致快照。
readonly-export-core.sql：users、objects、production_batches、data_sources、devices、points、point_bindings。
synthetic-core-example.json：11 条明确标记 synthetic 的演示记录，不是现场数据。
input-template.json：空结构模板，填入真实导出记录、快照时间；空模板不能导入。
__init__.py：校验产物、读取记录、规范来源身份、计算强连通分量和分批依赖计划。
../../ops/import_liangzihu.py：通过认证 HTTP API 预检、安装、导入、分批和重放，不直写活动数据库。

来源身份和人工录入
------------------
绑定键由当前授权租户 + source_id + 来源表 + 规范化来源主键组成。
source_id 标识同一个上游安装实例，首次确定后保持不变，例如 liangzihu-production。
同名、同编码并不意味着同一实体；不同 source_id 的相同源主键不合并。
SQL 导出自动带出源 UUID，管理员无需自己编写本库主键。
如果本来没有上游记录，使用本库对象登记入口，让本库生成 UUID；不要伪造源库主键来冒充来源记录。
3 个复合主键表：observation_receipts(observation_id,raw_ref)、record_attachments(record_id,asset_id)、
terrain_resources(scene_id,path)。两个字段都必须完整，path 的空格和大小写不自动修正。

如何获得真实记录
----------------
以下命令在 implementation 目录运行。请使用授权的只读源库账号。
连接信息通过 PostgreSQL 正常认证配置或环境提供，不写入 SQL、计划、项目仓库或公开日志。
先把实际导出和回执放入 runtime/source-imports/ 目录；仅该专用目录被 Git 忽略。

  psql --no-psqlrc --quiet --tuples-only --no-align --set ON_ERROR_STOP=1 --file integrations/liangzihu/readonly-export-core.sql --output runtime/source-imports/liangzihu-core.jsonl

先建立 runtime/source-imports/ 目录。SQL 显式设置客户端 UTF-8；使用 psql 的 --output 直接写文件，
避免旧版 Windows PowerShell 的 > 重定向把 JSONL 改成 UTF-16。

导出 SQL 不使用 SELECT *；仅显式选择已映射属性、源 PK 和启用 FK 列。
不导出密码/令牌/身份核验材料、复杂 JSON、几何、向量、二进制、未映射标识数组。
需要其他业务表时改用 readonly-export.sql。全量业务表可能包含人员信息，应只在授权内部处理。
只读导出遇到表结构变化或权限不足会停在错误处，不会静默继续。不要导入失败后产生的半份文件。
JSONL 不携带快照元信息，运行接入命令时必须明确填写真实导出快照的 observed_at 和 data_nature。
observed_at 是见证来源快照的时间；它不替代 sampled_at、valid_from、started_at 等业务时间。
源库不能访问时，只能验证合成样例，不得报告“现场实物已导入”。

首次小批接入：先预检，再应用
--------------------------
AGRI_API_TOKEN 应通过当前终端环境安全提供，其账号需 admin 或 ontology_admin。
本工具不会读取浏览器凭据，也不会在输出中打印令牌；非本机 HTTP 被拒绝，远程需 HTTPS。
以下示例先使用独立 synthetic 来源，避免污染正式来源命名空间。

  python ops/import_liangzihu.py preview --source-id synthetic-liangzihu --input integrations/liangzihu/synthetic-core-example.json --install-definitions

默认预检会把 18 个领域包、来源映射和 11 个对象及关系一起放入事务校验，然后完整回滚。
预检不返回可复用的新 UUID，不占用真实身份；检查回执中的错误、未映射字段和计数后再运行：

  python ops/import_liangzihu.py preview --source-id synthetic-liangzihu --input integrations/liangzihu/synthetic-core-example.json --install-definitions --apply

--apply 才写数据库；首次“定义安装 + 当前批次”在一个事务内完成。
也可单独安装定义（省略 --apply 为只读预检）：

  python ops/import_liangzihu.py install-definitions --source-id liangzihu-production --apply

真实 JSONL 小批示例，时间必须换成实际快照时间：

  python ops/import_liangzihu.py preview --source-id liangzihu-production --input runtime/source-imports/liangzihu-core.jsonl --observed-at 2026-10-19T09:30:00+08:00 --data-nature production

不声明 data_nature 的裸数组或 JSONL 会被拒绝。synthetic/test 会保留数据性质，不能冒充生产证据。
命令只显示计数和回执位置，完整来源记录和回执保存在 runtime/source-imports/ 中，不能公开上传。

超过 100 条：依赖分批，不用手工拆表
----------------------------------
每个 API 批次 1–100 条，整个请求不超过 2 MiB；一个输入计划最多 100000 条、64 MiB。
先生成计划，工具按规范来源主键构图，把外键父记录安排在依赖记录之前。
循环关系的强连通分量会放在同一个批次，最大 100 条；超过时直接报错，不拆坏关系。
未在输入或既有绑定中找到的 FK 会明确报错，不能凭名称猜测或默默跳过。

首次来源完全在本文件中的情况：

  python ops/import_liangzihu.py plan --source-id liangzihu-production --input runtime/source-imports/liangzihu-core.jsonl --observed-at 2026-10-19T09:30:00+08:00 --data-nature production --output-dir runtime/source-imports/liangzihu-plan-001

已导入过一些对象或此次是增量修订：增加 --fetch-bindings，从当前认证租户读取现有绑定和修订号。
此查询采用 projection=identity、每页 100 条，仅取身份与修订元数据，不下载完整来源载荷。
离线情况下可用 --bindings runtime/source-imports/source-bindings.json 传入此前授权查询得到的 items 数组。
生成计划不写数据库，属于依赖检查；值域、当前修订、权限及本体契约还需后端实际预检。
计划保存每个 batch JSON 和 SHA256。修改计划内容后必须重新生成，不能只改文件绕过复核。

  python ops/import_liangzihu.py apply-plan --plan-dir runtime/source-imports/liangzihu-plan-001

以上只检查计划文件和摘要，不连接或写后端，不声称逐批远端预检已经通过。
确认之后：

  python ops/import_liangzihu.py apply-plan --plan-dir runtime/source-imports/liangzihu-plan-001 --install-definitions --apply

工具顺序运行每批“远端预检 -> 正式提交”，遇错立即停止；首批可同时原子安装全部定义。
整个计划不是一个事务：较早批次可能已经提交，progress.json 与 receipt-*.json 保留进展。
网络异常时保留原计划，重放相同请求，源 batch_id/幂等键识别已提交内容；不要重新生成随机批次 ID。
修正数据后生成新的计划、使用更晚的 observed_at，并获取最新 bindings 修订号。
如果首批因为定义 + 数据合计超过 2 MiB，先单独安装定义，再去掉 --install-definitions 应用计划。

值转换、空值和复杂数据
--------------------
UUID：规范化大小写和连字符，只接受字符串。内部本体 UUID 由服务生成。
integer：安全 JSON 整数或十进制整数字符串；过大的整数不能先转 JavaScript Number。
白名单导出 SQL 将整数字段也转为十进制字符串，避免 bigint 超过安全整数范围后被拒绝或损失精度。
decimal：接受十进制字符串或整数，拒绝 JSON 浮点，避免虚假精度。导出 SQL 自动 cast 为 text。
datetime：必须有时区。timestamptz 在 SQL 导出中明确转成 UTC；无时区值不能猜成 UTC。
date：严格 YYYY-MM-DD 并检查日期存在；不会擅自补零点和时区。
text[]：逐元素验证；1–100 项，空数组明确表示该属性缺省/删除。不会把它拼成逗号字符串。
缺少字段：部分更新，保留以前该字段的值及关系。null：清除提供的属性或可空关系。
非空 FK 不能用 null 清除；复合 FK 要同时提供全部字段，不能提供一半。
deferred 字段：提供时保留来源证据并在回执说明原因，不进入已映射属性或关系。
rejected 字段：整批拒绝，包括密码哈希、认证状态、身份核验资料。未知字段也拒绝。
source SQL 的 CHECK、NOT NULL、索引、触发器不全部在本体库重建；目录保留来源约束供审查。
源记录删除不会自动删除本体实体，不能把记录缺席解释为实物消失。正式删除/撤回需单独业务协议。

如何改映射和代码
----------------
先看 coverage-manifest.json 的 table/field/constraint 和固定 source 位置，再看接受的 Excel。
映射生成逻辑位于 tools/ontology_export/build_source_profile.py；不要只手改生成 JSON。
修改当前发行内容会触发摘要失败；结构变更应更新 profile 版本，必要时升级对应领域包版本。
运行项目根目录命令重新构建：

  python tools/ontology_export/build_source_profile.py

构建程序强制核对 190/2114/555 和 122/979/409 计数。若确实扩大范围，先评审来源覆盖和敏感字段，
再修改计数门禁与测试；不能仅为“让测试通过”删除检查。
构建时需要根目录的原 Excel 导出目录；运行时的 profile、bundle、manifest 已自包含在 implementation 中。
名称显示变更使用已有标签修订接口；稳定 type_id、property_id、predicate_id 不随中文显示名改变。
跨本体新分类或身份合并需独立迁移方案。已绑定实体改 type_ref 会拒绝，避免静默重新解释历史身份。
后端核心在 agri/source_mapping.py；不应在 CLI 中绕过 _guard、mutate、租户锁、幂等、审计或事务。
修改之后运行 tests/test_source_mapping.py 和 tests/test_liangzihu_adapter.py，以及项目完整测试。
SQLite 只能验证本地行为；PostgreSQL 测试必须使用隔离测试库/随机 schema，另做现场数据验收。

当前交付性质
------------
这是已接受结构映射的可运行接入组件与合成测试，不包含原项目生产数据库、真实摄像头或闸门资产。
普通 FK 只表示来源系统的引用关系，不证明空间包含、因果关系、质量合格或操作已执行。
导入边默认是 candidate 候选关系。HTTP /ontology/relations 默认只返回 accepted，核对时用
status=candidate 或 status=all；仍按 valid_at（默认当前时刻）筛选有效关系，历史需明确时间。
HTTP /ontology/graph 目前由 network.build_network 构建，默认可包含不同状态，不能将图上显示等同采纳；
须检查边的 status。Service 内部 _graph 路径与此 HTTP 网络接口不同，调用方不要混用语义。
业务采纳走已有关系评审接口，绑定历史用于查看源修订和关系变化。
源数据经本库处理后可沿实体、关系、证据、绑定历史和变更流供内部溯源服务读取；公开发布仍需现有发布审核。

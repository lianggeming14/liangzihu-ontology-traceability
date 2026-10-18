# 梁子湖农业本体数据库

当前版本 **v0.4.0**。已依据核对后的梁子湖来源结构，完成来源记录到本体实体、属性与外键关系的确定映射，并提供预检、批量导入、修订历史和证据输出。数据库保持本体管理、约束存储、血缘与取数的职责；图像识别、农业判断、模型执行和设备控制由外部服务承担。

## 本轮交付

- 来源目录覆盖 **190 表、2114 字段、555 外键**；启用 **122 个业务来源记录类、979 个属性、409 个外键映射**，延期和拒收项逐一说明。
- 来源身份按租户、来源实例、表和规范主键绑定到系统生成的本体 UUID，支持复合主键、重复请求、乐观修订和候选关系历史。
- 18 个领域包与映射可原子安装；整批预检完整回滚。大文件按依赖关系分批，失败停止，保留回执并支持相同请求重放。
- HTTP 严格解析拒绝重复 JSON 键、NaN/Infinity 及指数溢出的非有限值，无效请求不写库、不占幂等键。
- 本机已应用 **005 迁移并启动 v0.4.0**：新增 18 包，当前共 23 包；原有 **17 个实体完整保留**。本轮没有持久导入新合成样例或真实生产记录。

## 操作与文档

优先阅读两份新 Word：

- [后端操作说明书 v0.4](交付文档/梁子湖本体数据库后端操作说明书_v0.4.docx)：阅读和修改代码、本体与映射维护、API、批量接入、测试和运维。
- [原项目数据库分析与本体库比较报告](交付文档/原梁子湖项目数据库分析与本体库比较报告.docx)：底层结构、代码逻辑、特点、证据和比较。

在 implementation 目录安装 requirements.txt 后，运行 **python -B -X utf8 run_server.py --no-seed --open-browser**。默认地址为 http://127.0.0.1:8787/；--no-seed 避免重新加载演示数据。该入口是本地工程服务。

- [梁子湖适配器与 CLI 操作](implementation/integrations/liangzihu/README.txt)
- [来源导入 CLI](implementation/ops/import_liangzihu.py)：默认预检，明确 --apply 才写入；支持 plan 与 apply-plan。
- [逐表、字段与关系覆盖目录](implementation/integrations/liangzihu/coverage-manifest.json)
- [运行与能力说明](implementation/README.txt)
- [结构化记录接入指南](implementation/DATA_INTAKE_GUIDE.txt)
- [API 契约](implementation/contracts/openapi.json)
- [验证结果](implementation/验证结果.txt) · [实现状态](implementation/IMPLEMENTATION_STATUS.json) · [生产门禁](implementation/database-gate.json)
- [本轮证据与文档预览](outputs/backend-integration-20261019)
- [GitHub 同步约定](GITHUB_SYNC.txt)

真实来源导出、计划和回执应放在 implementation/runtime/source-imports/，该专用目录被 Git 忽略。原始源主键由导出带入，本库 UUID 由系统生成，无需逐条手编。

## 验证与实施边界

本轮权威测试为 **378 passed、0 failed/error、180 skipped**，见 [final-tests.xml](outputs/backend-integration-20261019/final-tests.xml)。跳过包括 178 项 PostgreSQL、1 项旧 FFMPEG 扩展、1 项 Windows 符号链接权限测试。实际 loopback HTTP 已预检 11 条合成记录和 22 条关系，完整回滚后实体数仍为 17；旧 38 项浏览器检查仅为 **historical_v0.3**，本轮没有重跑。

**基于来源结构的数据库身份绑定已实现；认证主体到 source_id 的强绑定尚未实现。** 目前没有真实梁子湖生产数据导入、PostgreSQL 实库或现场验收，也未验证生产 TLS、容量与完整恢复。来源快照和候选 FK 关系不自动成为已采纳事实，哈希也不证明内容真实。

Word 文件已生成并检查 ReportLab 测量布局预览；当前环境缺少可用的 Word/LibreOffice 原生渲染，未宣称原生分页与字体验证通过。

旧 [v0.3 源代码包](交付文档/梁子湖农业本体数据库_本地工程版_v0.3.zip)、[v0.3 职责说明](implementation/DATABASE_CORE_V0.3.txt) 和 [总体方案 Word v1.1](交付文档/梁子湖智慧农业本体库与溯源系统总体方案_v1.1.docx) 保留作历史资料；当前状态以 v0.4.0 和本轮证据为准。公开仓库保存经排除检查的项目成果，不上传运行数据库、现场原始资产、令牌或依赖。

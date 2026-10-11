# 梁子湖农业本体数据库与产品溯源系统

智慧农业本体库与产品溯源系统的方案、源码和验证资料。项目由当前模型实施，Kimi 已退出工作流。

## 快速入口

- [总体方案 Word v1.1](交付文档/梁子湖智慧农业本体库与溯源系统总体方案_v1.1.docx)
- [运行与能力说明](implementation/README.txt)
- [原平台对接说明](implementation/PLATFORM_INTEGRATION.txt)
- [接口契约](implementation/contracts/openapi.json)
- [测试结果](implementation/验证结果.txt)
- [后续 GitHub 同步约定](GITHUB_SYNC.txt)

在本机运行 implementation/启动系统.cmd，或安装 requirements.txt 的依赖后，在 implementation 目录执行 python run_server.py --open-browser。默认地址为 http://127.0.0.1:8787。首次运行会重建合成演示数据。

## 已实现的本地工程能力

稳定对象身份与可扩展领域包；多维关系网络；观测、断言与原始证据分离；数据接入和结构化推理包；批次投入产出谱系；审核发布、公开二维码、证据撤回、召回及发布后新冲突失效。包含虾稻、蔬菜和禽蛋示例。

自动测试：92 项通过，38 项 PostgreSQL 测试因缺少独立实库环境跳过。浏览器使用真实 Flask 请求和独立持久化 SQLite 联调通过。TCP 监听、真实平台、现场设备、生产模型及 PostgreSQL 实库尚未验收。

## 目录

| 目录 | 内容 |
|---|---|
| implementation/ | 应用、数据库迁移、接口、测试和启动入口 |
| 交付文档/ | Word 方案、源码包及校验文件 |
| 设计草案/ | 设计资料和来源核对 |
| .document-build/、.document-build-v1.1/ | 文档源数据、生成程序、图及预览验证 |
| tools/ | GitHub 同步、快照生成与还原工具 |

本仓库保留项目成果及版本历史，不存放令牌、密码、认证缓存、运行数据库或未经审核的现场原始资产。它是私有项目库，并非生产部署或农产品质量认证。

后续本项目新增或修改的成果，在每次交付时同步到此仓库；不会未经说明启用后台自动上传服务。

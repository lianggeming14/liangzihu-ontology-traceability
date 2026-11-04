# 十分之一数据结构审查

> 当前本体浏览已迁至 **[本体、实例与来源地图](../ontology-review/README.md)**。本页保留 SQL 字段、抽样和合成场景审计，六个合成塘口图不作为实际来源地图。

打开 [交互预览](index.html)，检查业务表、完整字段、规范化样例、关联示例与六口塘尺寸。页面可离线打开。

这次建设的是独立 PostgreSQL / PostGIS 样本结构 `lzo_gis.fish_review_10pct_v1`，不是原平台正式采纳记录的替代品。原平台全量导入保持暂停，等待本次结构审查。

## 实际建设结果

- 基础样本 **11,652 / 116,519** 条，约 10%；按表和异常状态确定性分层抽样。
- 为避免外键断链补充 **8,954** 条依赖；最终 **20,606** 条原始记录。最终比例约 17.7%，没有把依赖数量隐瞒为 10%。
- **64** 张完整业务结构表、**1,346** 个来源字段。`record_provenance` 仅保留结构，属于基准参考，不重复导入参考答案。
- 原始层保存字符串、规范值、状态、问题及抽样原因；58 条重复或隔离记录保留原始层。
- 规范层 **20,548** 条：其中 **6,334** 个本体实体、**13,047** 个观测记录、**1,167** 个事件索引。索引和观察没有冒充独立业务事件。
- 关系层 **68,343** 条边，保留字段、目标表/主键、状态和列表序号。只有 resolved 边绑定目标节点。
- **238** 条业务外键及 **3** 条图/GIS 外键已由 PostgreSQL 实际验证；源数据本来不可用的目标另记在报告，不伪造目标。
- **126** 个 GIS 要素，包括 6 口塘、辅助设施、线面图层及明确标注的栅格覆盖范围。PostGIS 几何有效性检查 0 个失败。

## 已运行的验证

独立回读 20,606 条原始记录，原文/规范值/状态/问题 **0 差异**；核对规范表 **458,665** 个字段值，全部一致。Decimal 使用 PostgreSQL 无固定小数位的 numeric；原始文本仍单独保存。导出的 SQL 已在单独事务重新创建 70 张物理表及循环外键，再回滚验证事务。

页面用 Chrome/Playwright 检查了 64 张表、6 口塘、关系示例和塘口切换，JavaScript 错误为 0。

## 尺寸与数据性质

ZIP 中是合成养殖场数据；ERA5 天气维持 imported_unverified。塘口面积、平均/最大深度和有效体积保留包内场景值。GIS 几何面积和周长通过 PostGIS geography 计算，明确标为模拟边界计算；实测周长和实测深度保持空值。与原有五张真实工程图的实体没有自动合并。

## 文件

- [schema.sql](schema.sql)：完整关系库 DDL，包含循环关联的后置外键及 GIS geometry 索引。
- [readback.json](readback.json)：抽样计数、全部字段字典、每表少量规范样例、关联样例和实库回读结果。
- [preview.png](preview.png)：交互页面截图。
- 生成：`scripts/build_fish_review_sample.py`；独立核验：`scripts/verify_fish_review_sample.py`。

生成器要求经过 SHA-256 / Git blob / 557 成员验证的本地来源包。重复创建已有预览 schema 会拒绝覆盖。活动数据库、凭据和完整原始样本不上传 GitHub；通过固定来源与脚本重建。

## 配置与运行入口（2026-11-04）

从仓库根目录进入 `ontology-platform`，所有配置内的相对路径都以该工程目录为基准，和命令行当前目录无关。无凭据模板在 [config/fish-review.example.json](../../../config/fish-review.example.json)。

1. 下载[固定版本的来源 ZIP](https://github.com/lianggeming14/upload-files/blob/1eb0bab8f86fab00d6ebf62b18e609446957fc9d/%E6%AD%A6%E6%98%8C%E9%B1%BCL1_2025_01_%E6%95%B0%E6%8D%AE%E5%8F%8A%E7%94%9F%E6%88%90%E5%99%A8.zip)，保存为模板 `source_archive` 指定的 `.runtime/source-imports/wuchangfish-l1-2025-01/1eb0bab8f86f/source.zip`。如需改路径，复制模板为 `config/fish-review.local.json` 后修改，该本机配置被 Git 忽略。
2. 执行来源准备命令。它先校验 ZIP 摘要、大小及全部成员，再在 `.runtime` 安全解包并准备清单；不会执行包内生成器，已有不一致文件会拒绝覆盖。
3. 安装已锁定的平台依赖，再离线预检抽样。预检不要求环境文件、数据库、Keycloak、Fuseki 或 worker。

```sh
cd ontology-platform
python scripts/prepare_fish_review_source.py --config config/fish-review.example.json
python -m pip install -r scripts/requirements-fish-review.txt
python scripts/check_fish_review_config.py
python scripts/build_fish_review_sample.py --config config/fish-review.example.json --plan
```

真正建库或回读时，使用已经准备好的本地 PostgreSQL 16+ / PostGIS。数据库名为 `lzo_gis`，owner 为 `lzo_gis_owner`，连接必须是 `127.0.0.1` 上显式端口。把下面两个键写入模板指定的私有 `env_file`；连接 URL 中的密码需正确 URL 编码，不提交该文件。

```text
APP_ENV=test
LZO_GIS_MIGRATION_DATABASE_URL=postgresql+psycopg://lzo_gis_owner:<URL编码的本机密码>@127.0.0.1:25449/lzo_gis
```

```sh
# 仅创建新的固定样本 schema，存在时会拒绝；不会自动删除或重建
python scripts/build_fish_review_sample.py --config config/fish-review.example.json
# 对已经建好的样本只读回验，更新本地审查报告
python scripts/build_fish_review_sample.py --config config/fish-review.example.json --verify
```

上述命令不自动启动数据库服务，不执行平台正式迁移、不启动原来的全量导入。`--verify` 不能使用 Python `-O`，防止跳过核验断言。建库与只读核验共用同一份配置，不再依赖另一台机器的 ownership 文件或未上传的 GIS 身份清单。

仅查看本次已经生成的页面，无需安装数据库或 Python 依赖：

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory docs/fish/review-sample
```

浏览器打开 `http://127.0.0.1:8765/`。需要数据库写入的操作仍限于结构样本；全量导入等待本次审查。

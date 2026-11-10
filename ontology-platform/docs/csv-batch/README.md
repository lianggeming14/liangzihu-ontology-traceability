# 66 CSV 完整批次：来源、数据库与本体验收

本批次将固定来源包的 **66 个业务 CSV、153,862 条记录、1,397 个来源字段**全部纳入独立审查批次。2026-11-10：PostgreSQL 写入与全量回读、新 Jena 图的 **21,333,891 条三元组**完整术语等值核验、实际 SHACL、旧四图保护、全导航核验、独立实时 API 与实际 Chrome 验收均已通过，导航已经激活。当前为 **5 图、24,054,860 条三元组、180,997 个实例、178 个概念、150 个叶类**；GitHub 发布结果以目标 main 的提交及对应 Actions 为准。各项状态以实际报告为准。`formal_adoption=false`，本批次不构成现场测量或生产采纳声明。

## 固定来源与数据性质

来源为 [lianggeming14/upload-files 固定提交](https://github.com/lianggeming14/upload-files/tree/cb9353499b6ede33fa60b3c67e18a983e362ab16) 中的 `csv.zip`，不运行上游生成器。

| 身份／范围 | 固定值 |
| --- | --- |
| 源提交 | `cb9353499b6ede33fa60b3c67e18a983e362ab16` |
| ZIP SHA-256／批次身份 | `a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524` |
| Git blob SHA-1 | `af355c9199304fc7dd37634cdf5d5984feed08be` |
| ZIP 大小 | 2,578,429 字节 |
| 归档内容 | 134 个条目、133 个文件：66 个业务 CSV、67 个 Mac 元数据文件；总解压大小 42,054,862 字节 |
| CSV 检查 | 全部 UTF-8 BOM；153,862 条数据行，坏行 0，空行 0 |
| PostgreSQL schema | `lzo_gis.csv_batch_a4d78be79a83` |
| RDF 命名空间 | `urn:lzo:csv-batch:v1:a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524:` |
| 新 RDF 图 | `urn:lzo:csv-batch:v1:a4d78be79a83ac2516ac2742a17222589940c85e3dd9190134c3e0ff799b4524:graph:b1fd6a293a08c41990a328c7dc92489396cad7dc9f9388f03885a316b54d1008` |

[source-manifest.json](source-manifest.json) 保留逐文件字节数、压缩信息、CRC 与 SHA-256。67 个 Mac 元数据文件只进入摘要清单，不作为业务表或记录入库；原始 ZIP、CSV 字节和元数据原件留在私有 `.runtime`。

`source_registry` 明确区分主体规则模拟、天气再分析与复用资产目录。记录自身的来源、批次身份、数据性质、时间精度及质量标记随规范实例保留。模拟生长、经营、观测等数值不能解释为梁子湖现场测量；再分析天气也不能冒充现场传感器读数。新批次与历史 10%＋依赖样本拥有独立实例身份，不作同一对象合并。

## 核验与保存方式

清洗在保留原文的基础上核对主键、重复／冲突身份、字段类型、外键、数值与日期，以及分级 `grade`、数量 `count` 和重量 `weight` 的约束。质量报告覆盖 711,285 个数值单元格、491,594 个日期单元格、41,031 条个体分级归属和 50 条起捕分级汇总。当前报告的重复、冲突、隔离行和非法类型化单元格均为 0。

不把文本 `none` 等值一概转成 NULL；按照字段声明和来源语义处理缺值。未声明字段保留来源名称与原值，不猜业务含义；无法确认的外键保留原目标标识与关系账本，不生成虚构目标实例。新字段、关系定义和结构分别见[字段字典](field-dictionary.json)、[关系映射](relation-map.json)、[结构清单](schema-structure.json)和[质量审计](quality-audit.json)。

PostgreSQL 共 **72 张表：66 张类型化业务表和 6 张来源／字典／本体支持表**。完整保存 153,862 条原始记录和 153,862 个规范实例；逐项比对 3,539,134 个原文单元格，并另核对对应的 3,539,134 个类型化业务单元格。关系账本共 810,934 条，其中 810,891 条解析到本批次实例，43 条为外部／未解析引用，目标列继续为空。计数、类型、schema 和实际值均在 [PG 回读报告](pg-readback.json)中核对，SQLite 测试不替代这份实库证据。

RDF 复用共享领域层级 `https://w3id.org/lzo/ontology/`，来源表作为批次专属叶类；类型化值采用 XSD datatype，对象关系与逆关系均显式表达。原始记录与关系账本保留 PROV 来源、源表、源行、源主键、关系位置及未解析状态。批次状态为 `csv_batch_not_formally_adopted`，不将来源外键修补为演示关系。

## 本体浏览与分片边界

从 `ontology-platform` 目录执行：

```sh
python scripts/serve_ontology_review.py --offline --port 0
```

打开终端给出的 `127.0.0.1` 地址。离线浏览只依赖 Python 标准库，使用仓库内已发布的规范化导航分片；GitHub HTML 文件页显示源码，不能直接运行交互页面。实时 RDF 证据需要本地 Jena，去掉 `--offline` 并安装 [requirements-ontology-review.txt](../../scripts/requirements-ontology-review.txt) 中的依赖。页面入口与历史地图来源见[本体审查说明](../fish/ontology-review/README.md)。

CSV 摘要按所选类加载，详情每块 500 条；高关联对象的关系保存在每块 4,800 条的外部文件，界面每页展示 12 条并继续加载后页。已完整发布规范化的属性和关系，公开导航不包含原始来源 payload。新批次先对 Jena 返回的完整 RDF 术语集合与投影集合做精确等值核验，再对等值规范视图运行 SHACL；两项均通过后，由同一投影模型分片序列化，不将 Jena 全部返回值转为 DTO 后一次缓存。旧 84 个叶类分片保留原来直接由 Jena 回读值生成的路径，两种构建路径分别记录。

[分片清单](navigation-files.json)和[激活报告](activation-readback.json)核对了 592 个 CSV 压缩文件：66 个类摘要、362 个详情块和 164 个关系块，总计 **70,148,120 字节**，最大单文件 **1,865,203 字节**。激活前逐文件验证大小与 SHA-256，最后切换根 manifest；旧类分片未重写。

旧四图保持 **2,720,969 条三元组、27,135 个实例、112 个概念、84 个叶类**。当前合计 **5 图、24,054,860 条三元组、180,997 个实例、178 个概念、150 个叶类**；来源关系账本合计 890,003 条，其中 889,893 条解析、110 条未解析，原有演示关系仍为 10,495 条。[全导航核验](../fish/ontology-review/navigation-readback.json)完整检查了实例、概念、双向关系与未解析记录，悬空和类型不匹配均为 0。该导航核验读取规范化文件，未再次查询 Jena；实库完整术语证明由独立 RDF 报告提供。合计见实际 [manifest.json](../fish/ontology-review/data/manifest.json) 和[激活报告](activation-readback.json)；概念数包含领域父类，实例数包含观测、事件、档案、测量和图层，不等同于塘口数量。

## 验收证据

| 范围 | 当前结果／证据 |
| --- | --- |
| ZIP 与全部 CSV／元数据摘要 | 已通过：[source-manifest.json](source-manifest.json) |
| 主键、类型、关系及分级核验 | 已完成：[quality-audit.json](quality-audit.json)、[model-readback.json](model-readback.json) |
| PostgreSQL 72 表全量实库核对 | 已通过：[pg-readback.json](pg-readback.json) |
| 原四图与其他旧图保护 | 已通过：[prior-graphs-readback.json](prior-graphs-readback.json)；四图完整术语摘要相等，977 个原有非空图的清单计数保持；其他旧图仅验证计数 |
| 新图完整 RDF 术语回读 | 已通过：[rdf-readback.json](rdf-readback.json)；21,333,891 条三元组，缺失／意外词项 0，完整 termset SHA-256 为 `b1fd6a293a08c41990a328c7dc92489396cad7dc9f9388f03885a316b54d1008` |
| 新图实际 pySHACL | 已通过：[shacl-readback.json](shacl-readback.json)；66 类、153,862 个实例、1,397 个 datatype 约束、626 个关系类约束，零违规 |
| 规范化分片及导航激活 | 已通过：[navigation-files.json](navigation-files.json)、[activation-readback.json](activation-readback.json)；592 文件，manifest 最后切换 |
| 全部规范化导航与双向关系 | 已通过：[navigation-readback.json](../fish/ontology-review/navigation-readback.json)；180,997 实例，889,893 条解析关系、10,495 条演示关系双向核对，110 条未解析记录保留，零悬空／错类 |
| 新批次浏览器交互和截图 | 已通过：[csv-browser-report.json](../fish/ontology-review/csv-browser-report.json)；实际 Chrome 检查层级、摘要／详情懒加载、关系跨块及末页、旧地图和手机视图，零 JavaScript 错误，共五张截图 |
| 独立实时 HTTP → SPARQL 验收 | 已通过：[live-api-readback.json](live-api-readback.json)；实际五图合计 24,054,860 条，CSV 叶类、类范围分页、精确类型化深度、批次内养殖场关系和高关联对象后页通过，SQL 连接 0，数据库变更 0 |
| 独立全量来源与关系复核 | 已通过：[independent-review.json](independent-review.json)；153,862 条实例、3,539,134 个字段值、810,934 条关系及全部分片核对，无阻断缺陷；实库证据与本轮直接复核范围分别说明 |
| 本轮 GitHub 成果同步 | 通过本地门禁后推送到目标 Public main；提交及远端检查以仓库提交和 Actions 记录为准 |

RDF 报告中的 `activation=staged_not_active` 记录建图完成时的暂存阶段；后续独立激活报告已确认当前导航生效。以上结果不替代生产权限、容器环境、恢复演练或现场验收；这些范围分别以原工程验收和后续实际执行记录为准。

实际浏览器截图：[CSV 首页](../fish/ontology-review/screenshots/desktop-csv-overview.png)、[桌面 CSV 关系](../fish/ontology-review/screenshots/desktop-csv-relations.png)、[旧来源地图](../fish/ontology-review/screenshots/desktop-legacy-map.png)、[旧地图对象](../fish/ontology-review/screenshots/desktop-legacy-map-object.png)、[手机 CSV 关系](../fish/ontology-review/screenshots/mobile-csv-relations.png)。浏览器使用公开规范化分片检查交互；独立实时 API 通过实际 HTTP → Fuseki SPARQL 检查 RDF，两类证据分别记录。

## 复现与保护旧图

以下命令均从 `ontology-platform` 目录运行。源码和公开分片足以离线浏览；**完整实库复现另需固定来源 ZIP、已运行的本地 PostgreSQL/Fuseki、私有认证，以及旧四图和导入前基线**。旧图的准备过程见[历史四图重建说明](../fish/ontology-review/README.md#重建与核验)。不会因为执行 CSV 工具而自动启动数据库，或重启原正式 importer／worker。

私有认证沿用 [config/fish-review.example.json](../../config/fish-review.example.json) 指向的 `.runtime` 环境文件，只读取本地数据库连接 URL；不使用该模板中旧的 `source_archive`、`review_schema` 作为 CSV 输入。私有环境要求 `APP_ENV=test` 和 `LZO_GIS_MIGRATION_DATABASE_URL`，连接目标由程序限制在隔离本机 `lzo_gis`。密码不放在命令行、报告或版本库中。数据库工具依赖现有 Python 环境的 `psycopg`、SQLAlchemy 与 dotenv，RDF 工具使用锁定的 [RDF 审查依赖](../../scripts/requirements-ontology-review.txt)。

1. 从固定提交取得 `csv.zip`，私有存放为 `.runtime/source-imports/csv-2026-11-09/cb9353499b6e/source.zip`。核验与解压只写 `.runtime`，公开报告不包含来源行：

   ```sh
   python scripts/prepare_csv_batch.py --archive .runtime/source-imports/csv-2026-11-09/cb9353499b6e/source.zip --output .runtime/source-imports/csv-2026-11-09/cb9353499b6e/extracted --report docs/csv-batch/source-manifest.json
   ```

2. 生成 PostgreSQL 结构计划，再明确写入新 schema；`--apply` 拒绝覆盖冲突 schema，已存在的相同批次只做核验。`--verify` 为只读全量核对，不创建或修复数据：

   ```sh
   python scripts/build_csv_database.py
   python scripts/build_csv_database.py --apply --config config/fish-review.example.json
   python scripts/build_csv_database.py --verify --config config/fish-review.example.json
   ```

3. 写入新 CSV 图前，先捕获当前环境旧四图的完整回读基线；同时保存旧图计数清单和只读 PostgreSQL 来源身份。输出目录必须是新的私有 `.runtime` 目录，已有 `report.json` 的基线拒绝覆盖。之后构建并完整验证本批次图，分片暂存、尚不激活：

   ```sh
   python scripts/capture_csv_prior_graphs.py --output .runtime/csv-batch-20261109/baseline
   python scripts/build_csv_rdf.py --apply
   ```

   基线包含 `.runtime/csv-batch-20261109/baseline/report.json` 及相邻的 `graph-inventory.json`，必须在本环境导入前捕获，不能把导入后的捕获结果冒充导入前证据。

4. 使用已有导入前基线，重新读取并对比旧四图的全部 RDF 术语；仅执行 SELECT 和 Graph Store GET，不写 RDF 或 PostgreSQL：

   ```sh
   python scripts/verify_csv_prior_graphs.py --reference .runtime/csv-batch-20261109/baseline/report.json --output .runtime/csv-batch-20261109/after --report docs/csv-batch/prior-graphs-readback.json
   ```

5. PG、新 RDF、SHACL 和旧图保护报告全部通过后，验证暂存文件摘要、复制公开分片，最后原子切换根 manifest：

   ```sh
   python scripts/activate_csv_batch.py
   ```

数据库 DDL 为 [schema.sql](schema.sql)，OWL/SHACL 随激活合并到本体审查目录的 [vocabulary.ttl](../fish/ontology-review/vocabulary.ttl) 与 [shapes.ttl](../fish/ontology-review/shapes.ttl)。验收报告记录实际运行结果；未满足前提时应保留失败或未执行状态，不以离线单元测试替代实库成功。

代码、DDL、字段及关系契约、OWL/SHACL、全部规范化分片和验收证据属于本次公开成果。原始 ZIP／CSV／Mac 元数据原件、完整 N-Triples 运行资产、活动数据库、凭据和依赖由忽略规则排除；来源摘要可公开核对。GitHub 同步目标保持 `lianggeming14/liangzihu-ontology-traceability` 的 Public `main`，No1dry 仓库只读。

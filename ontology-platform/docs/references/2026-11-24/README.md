# 梁子湖农业本体项目：代表性项目、论文与标准

整理日期：2026-11-24。对象：[lianggeming14/liangzihu-ontology-traceability](https://github.com/lianggeming14/liangzihu-ontology-traceability)。

本索引回答“这个项目的技术来源和相近研究有哪些”。根据仓库已有文档和本体声明，区分三类关系：**已记录的工程参考**、**实际使用的技术底座/词汇**、**本次补充的相关工作**。采用某项标准，不等于搭建时读过介绍该标准的论文；以下不追认无记录的论文阅读史。

本次归档为中文导读、官方项目/论文链接与 BibTeX；没有附带论文 PDF 或上游源码镜像。

## 先看这七项

| 编号 | 项目或论文 | 与本项目的关系 | 对应内容 |
| --- | --- | --- | --- |
| P1 | 原梁子湖农场平台 | 已记录的工程参考 | 地形、测量、文件包和设备交接 |
| P2 | Apache Jena / Fuseki | 实际使用的技术底座 | RDF 保存、SPARQL 查询 |
| P3 | PostGIS | 实际使用的技术底座 | 田块/塘口几何、空间计算 |
| P4 | farmOS | 本次补充的相关项目 | 农场资产与作业日志的数据组织 |
| L1 | SOSA 轻量观测本体论文，2018 | 本次补充论文；其介绍的 SOSA 词汇已有采用依据 | 设备、观测、被观测对象的分离 |
| L2 | FoodOn 食品本体论文，2018 | 本次补充的相关论文 | 农产品分类与食品链数据互通 |
| L3 | GeoSPARQL 1.1 更新论文，2022 | 本次补充的相关论文 | 地理对象、几何与 RDF 的衔接 |

## 四个代表性项目

### P1. 原梁子湖农场平台：最直接的工程来源

- 已有来源记录：[项目 sources.md](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/database/sources.md)。
- 记录中的上游：[No1dry/liangzihu-farm-platform，固定提交 113e6491c488ebb3fc0529cf56c446e69274ce4f](https://github.com/No1dry/liangzihu-farm-platform/tree/113e6491c488ebb3fc0529cf56c446e69274ce4f)。
- 项目已有文档将其列为地形、测量、文件包、设备交接概念的工程输入。这一项比仅仅“题目相近”的开源项目更能解释实际建设来源。
- 核验边界：本次已回读项目来源记录；浏览工具未能取得该历史上游页面，因此不宣称重新核验了上游全部代码。历史地址可能需要仓库权限或发生迁移。
- 不将这一来源等同于现场测绘真值，也不据此声称完整复制上游实现。现有来源文档仍保留复用权利未完全确认的说明。
- 当前首页另将新 CAD/GIS 批次指向 litt1eloser/liangzihu-farm-platform；这是另一条数据来源记录，不应擅自合并为同一个已核实仓库。

### P2. Apache Jena / Fuseki：本体图存储与查询

- [官方 Fuseki 文档](https://jena.apache.org/documentation/fuseki2/) · [源码仓库](https://github.com/apache/jena)。
- Fuseki 提供 SPARQL 服务。本项目首页和数据库说明明确采用 Jena/Fuseki 存放、查询 RDF。
- 最值得对照：业务对象怎样使用稳定 IRI；三元组怎样放入命名图；如何查询指定发布版本。
- 本项目的批次校验、发布 ID、来源证据及界面是仓库自身的工程设计，不能全部归为 Jena 原生功能。

### P3. PostGIS：空间数据库底座

- [官方文档](https://postgis.net/documentation/) · [源码仓库](https://github.com/postgis/postgis)。
- 本项目使用 PostgreSQL/PostGIS 管理空间数据，可对应田块、塘口、道路、沟渠的几何与空间运算。
- 最值得对照：坐标参考声明、原始/转换几何的区分、几何有效性及空间索引。
- 使用空间数据库不自动证明 CAD 坐标已经完成现场配准。项目保留的未知坐标参考、候选位置和现场验收缺口仍有效。

### P4. farmOS：农业资产与日志的可比实现

- [项目官网](https://farmos.org/) · [源码仓库](https://github.com/farmOS/farmOS) · [官方数据模型](https://farmos.org/model/)。
- 官方模型围绕 Assets 和 Logs 组织农业记录，也支持人工记录及传感器数据。
- 与本项目的对应：田块/塘口/设备是相对稳定的对象，养殖、测量和生产活动是随时间产生的记录；两者分开更方便跨批次追踪。
- 推荐先读数据模型，比较一次生产记录如何连接对象、时间和观测。
- 这是本次补充的对照项目。目前未在已检查资料中找到本项目直接采用 farmOS 源码或模型的依据。

## 三篇代表性论文

### L1. SOSA: A Lightweight Ontology for Sensors, Observations, Samples, and Actuators

Janowicz, K.; Haller, A.; Cox, S. J. D.; Le Phuoc, D.; Lefrançois, M. 2018. *Journal of Web Semantics*. DOI：[10.1016/j.websem.2018.06.003](https://doi.org/10.1016/j.websem.2018.06.003)。

- [作者预印本 v2](https://arxiv.org/abs/1805.09979v2) · [PDF 阅读入口](https://arxiv.org/pdf/1805.09979v2)。
- 文章介绍 SOSA 的核心对象与关系：传感器、观测、采样及执行器，并讨论它与 SSN 等模型的衔接。
- 对本项目的价值：清楚区分传感器、被观测对象和观测结果，适合分析水温/溶氧记录与塘口、设备的连接方式。
- 已有采用依据：本项目 devices.ttl 将 Sensor 对齐 sosa:Sensor，将 WaterGate 对齐 sosa:Actuator；semantic-kernel.md 说明这属于显式层级对齐。
- 边界：可以说本项目采用了适用的 SOSA/SSN 词汇；目前不能据此断言搭建时直接参考了这篇论文。设备类型声明也不证明真实控制链路已接通。

### L2. FoodOn: a harmonized food ontology to increase global food traceability, quality control and data integration

Dooley, D. M. et al. 2018. *npj Science of Food*, 2, 23. DOI：[10.1038/s41538-018-0032-6](https://doi.org/10.1038/s41538-018-0032-6)。

- [期刊论文](https://www.nature.com/articles/s41538-018-0032-6) · [项目官网](https://foodon.org/) · [本体仓库](https://github.com/FoodOntology/foodon)。
- FoodOn 提供从农业来源到食品产品的共享词汇，以支持食品数据整合和追溯。
- 对本项目的价值：如果后续把养殖批次连接到出塘、加工、产品和流通记录，可用它研究外部类别映射，减少各系统同名异义。
- 建议阅读时重点区分生物来源、具体养殖对象、产品类别和产品批次。引入食品词汇不能替代批次身份和业务事件。
- 关系：本次补充的相关工作；没有发现本项目已导入 FoodOn 的证据。
- 访问说明：已通过期刊检索结果、FoodOn 官方网站及仓库交叉核对题名和用途；本次浏览器读取期刊全文/PDF 时遇到身份重定向，未完成全文精读，也未归档 PDF。

### L3. GeoSPARQL 1.1: Motivations, Details and Applications of the Decadal Update to the Most Important Geospatial LOD Standard

Car, N. J.; Homburg, T. 2022. *ISPRS International Journal of Geo-Information*, 11(2), 117. DOI：[10.3390/ijgi11020117](https://doi.org/10.3390/ijgi11020117)。

- [开放全文](https://www.mdpi.com/2220-9964/11/2/117) · [OGC 官方标准入口](https://opengeospatial.github.io/ogc-geosparql/) · [标准仓库](https://github.com/opengeospatial/ogc-geosparql)。
- 论文解释 GeoSPARQL 更新的动机，涉及空间对象与几何表示、词汇对齐、查询函数和实现案例。
- 对本项目的价值：为“地图上的田块”和“本体中的田块实例”建立更清晰的语义桥梁，并帮助检查几何编码与空间关系的表达。
- 建议优先阅读标准变更和实现案例，再核对本项目实际支持的查询路径。
- 关系：本次补充的相关工作。PostGIS 加 RDF 的组合本身不能证明已完整实现 GeoSPARQL 1.1；本文也不是本项目符合性或性能测试报告。

## 项目已有词汇与校验方式对应的标准

| 标准 | 官方固定版本 | 对应内容与采用边界 |
| --- | --- | --- |
| SSN / SOSA | [W3C Recommendation，2017-10-19](https://www.w3.org/TR/2017/REC-vocab-ssn-20171019/) | 设备与观测词汇。已有来源记录及本体显式类型对齐；不等于导入完整标准推理体系。 |
| PROV-O | [W3C Recommendation，2013-04-30](https://www.w3.org/TR/2013/REC-prov-o-20130430/) | 来源、实体与责任主体表达。semantic-kernel.md 记录了 PROV Entity/Agent 的适用对齐；不将项目所有审计结构称为完整 PROV 实现。 |
| SKOS | [W3C Recommendation，2009-08-18](https://www.w3.org/TR/2009/REC-skos-reference-20090818/) | 分类概念与实际对象分离；agriculture.ttl 将 CropConcept 对齐 skos:Concept。 |
| SHACL | [W3C Recommendation，2017-07-20](https://www.w3.org/TR/2017/REC-shacl-20170720/) | RDF 约束校验；项目已有 SHACL 校验流程。约束通过不等于来源数据已被现场核实。 |

## 项目内的核验入口

- [项目首页：当前架构与数据性质](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/README.md)。
- [来源与复用边界](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/database/sources.md)。
- [语义内核及词汇对齐说明](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/verification/semantic-kernel.md)。
- [设备本体](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/packages/ontology/devices/devices.ttl)。
- [农业本体](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/packages/ontology/agriculture/agriculture.ttl)。
- [设计中的观测与溯源对齐要求](https://github.com/lianggeming14/liangzihu-ontology-traceability/blob/main/ontology-platform/docs/superpowers/specs/2026-10-20-lzo-platform-p0-p1-design.md)。

推荐阅读顺序：项目来源记录 → SOSA 论文及 SSN/SOSA 标准 → Jena 与 PostGIS → GeoSPARQL 论文 → farmOS 模型 → FoodOn 论文。

## 归档与核验范围

- 本次核对已有项目文档、Turtle 声明及上述官方公开资料；导读为原创概括，具体书目见 references.bib。
- 归档至 upload-files 的 papers/2026-11-24-liangzihu-ontology/；相同导读和书目同步至项目仓库 ontology-platform/docs/references/2026-11-24/。
- 本次仅整理研究资料，没有运行软件回归、PostgreSQL 实库或现场验收；不更新项目历史测试结论。

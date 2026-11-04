# 梁子湖农业本体数据库

主仓库：[lianggeming14/liangzihu-ontology-traceability](https://github.com/lianggeming14/liangzihu-ontology-traceability)。当前审查入口为 **[本体、实例与地图](ontology-platform/docs/fish/ontology-review/README.md)**。

本轮将已审查的养殖样本和五份图纸证据接入实际 Jena RDF：**112 个概念、27,135 个可导航实例、2,720,969 条三元组**。按“领域本体 → 下级概念 → 分页实例 → 属性、关系、来源”逐级查看；关系目标和地图对象均可继续点击。OWL 类层级、类型化属性、对象属性、逆关系、来源记录和 SHACL 约束都可核验。

| 查看内容 | 入口 |
| --- | --- |
| 本体浏览、运行方式和数据边界 | **[本体审查说明](ontology-platform/docs/fish/ontology-review/README.md)** |
| 实际 RDF 导航页面 | [index.html](ontology-platform/docs/fish/ontology-review/index.html)，通过下方本地服务打开 |
| 界面与地图截图 | [本体首页](ontology-platform/docs/fish/ontology-review/screenshots/desktop-overview.png)、[来源地图](ontology-platform/docs/fish/ontology-review/screenshots/desktop-map.png)、[手机塘口](ontology-platform/docs/fish/ontology-review/screenshots/mobile-object.png) |
| RDF 精确回读与约束验证 | [Jena 回读](ontology-platform/docs/fish/ontology-review/rdf-readback.json)、[SHACL](ontology-platform/docs/fish/ontology-review/shacl-readback.json) |
| 全部关系及实时接口验证 | [导航核验](ontology-platform/docs/fish/ontology-review/navigation-readback.json)、[实时 API](ontology-platform/docs/fish/ontology-review/live-api-readback.json) |
| 本体词汇和约束 | [OWL/Turtle](ontology-platform/docs/fish/ontology-review/vocabulary.ttl)、[SHACL/Turtle](ontology-platform/docs/fish/ontology-review/shapes.ttl) |
| 总方案来源地图 | [6 个实际来源图层](ontology-platform/datasets/farm-map/README.md)及[源文件清单](ontology-platform/datasets/farm-map/source-manifest.json) |
| 五份工程图的原有完整提取 | [图纸信息及 GIS 接口](ontology-platform/docs/gis/drawings.md) |
| SQL 抽样与逐字段审计 | [辅助样本说明](ontology-platform/docs/fish/review-sample/README.md)、[DDL](ontology-platform/docs/fish/review-sample/schema.sql) |

```sh
cd ontology-platform
# 已验证 RDF 的离线导航；仅需 Python 标准库
python scripts/serve_ontology_review.py --offline --port 8792
```

打开 `http://127.0.0.1:8792/`。已备好本地 Jena 的环境可去掉 `--offline`，实时证据页通过只读 SPARQL 查询已验证的四个图。端口占用时使用 `--port 0`，读取终端输出的地址。GitHub 文件页显示 HTML 源码，不能直接运行交互页面。

地图使用 No1dry/farm 固定提交中的真实来源轮廓，包含全域及五个图纸图层、284 个空间表示。**局部图像／图纸坐标尚未地理配准**；不能解释成实测经纬度。五图的 3,202 条测量记录通过 163 条源 UUID 证据桥关联地图。缺失的实测水深和周长保留未知；来源标注、局部坐标计算、合成养殖值分别展示。

养殖 ZIP 是合成场景。基础抽样 **11,652 / 116,519** 条，另补 **8,954** 条关系依赖，共 **20,606** 条来源记录；其中 **20,548** 条可用记录形成类型化实例。经用户授权均分的 **10,495** 条演示关系单独建图，保留原始归属，不能当作现场塘口事实。其余实例包括空间表示、图层及图纸档案/测量证据，不能将总实例数视为塘口数量。全量正式导入仍等待本次结构审查。

当前工程位于 [ontology-platform](ontology-platform/README.md)，存储配置见[数据库说明](ontology-platform/database/README.md)和[环境运行手册](ontology-platform/docs/operations/environment.md)。`implementation` 为历史 v0.4 工程。仓库保持 Public、分支 `main`；凭据、活动数据库、依赖及完整原始运行资产由忽略规则排除。同步规则见 [GITHUB_SYNC.txt](GITHUB_SYNC.txt)。

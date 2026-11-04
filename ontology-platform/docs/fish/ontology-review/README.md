# 本体、实例与来源地图审查

这里是当前样本的本体浏览入口。实例已经实际写入 Apache Jena Fuseki，四个独立 RDF 图通过完整术语回读后才生成公开导航分片。SQL 样本负责来源审计；页面中的概念层级、实例类型、属性和关系有对应的 RDF 表达。

## 打开页面

从仓库的 `ontology-platform` 目录执行：

```sh
# 离线模式：仅需 Python 标准库，使用已通过 Jena 回读的导航分片
python scripts/serve_ontology_review.py --offline --port 8792

# 实时模式：已备好 Jena，默认 http://127.0.0.1:23049/fish_l1
python -m pip install -r scripts/requirements-ontology-review.txt
python scripts/serve_ontology_review.py --port 8792
```

浏览器打开 `http://127.0.0.1:8792/`。若端口受占用或系统保留，使用 `--port 0`，以终端实际输出地址为准。静态文件应通过 HTTP 打开，不能从 GitHub 源码页面或 `file://` 运行。离线模式明确标记 RDF 派生快照；实时模式的证据页实际调用 SPARQL，服务不可用时显示失败，不冒充实时查询。

## 逐级查看

1. 点击领域本体，继续进入下级概念；当前级别只显示其子级和所属实例。
2. 进入来源表或图纸概念，分页查看实例。点击实例后查看类型化属性、单位、正向/反向关系及来源。
3. 点击关联对象继续进入该实例，使用返回或面包屑保留浏览上下文。
4. 切换地图的全域或五个图纸图层，点击具体田块、塘面、道路或沟渠，进入对应 RDF 空间表示。
5. 图纸对象通过“具有原图档案及测量证据”进入原图档案，再沿测量关系查看数值、单位、证据及核对状态。图纸档案不是另一口实物鱼塘。
6. 演示分配单列展示；可进入分配记录及合成来源塘口，原始 `pond_id` 和原始关系继续保留。

实例详情的实时 RDF 证据支持双向分页。高关联数塘口不会因为首批记录上限而丢失后续关联；当前页是否还有更多会明确提示。主要浏览视图使用已逐边验证的 RDF 派生分片，实时证据可独立核对。

## 本体与数据结构

采用 OWL/RDFS 类层级、`rdf:type`、带 XSD datatype 的属性、对象属性和显式逆属性；共享领域 IRI 为 `https://w3id.org/lzo/ontology/`，来源表/档案类型作为叶类。来源记录使用 PROV 表达。缺值不转换为零，未解析目标不伪造实例，原始记录身份和关系位置继续保留。

| 图 | 内容 | 三元组 |
| --- | --- | ---: |
| sample | 20,548 条可用养殖样本、20,606 条来源记录及原始关联账本 | 2,183,946 |
| map | 284 个实际来源空间表示、6 个独立图层 | 18,546 |
| demo | 10,475 条均分活动关联及 20 条合成塘口档案模板关联 | 125,954 |
| drawing | 6,297 个原图档案/证据实例，含 3,202 条测量及 163 条地图证据桥 | 392,523 |

合计 **2,720,969** 条三元组、**27,135** 个可导航实例、**112** 个概念。概念数包含领域父类；84 个叶类提供压缩实例分片。实例数量包含观察、档案、测量和图层，不能解释成实物资产数量。

来源关联账本保留 **79,069** 条，其中 **79,002** 条可解析、**67** 条未解析；演示关系 **10,495** 条单独计数。每条可解析关联和演示关联均核对正反方向，无悬空或错类。163 条精确源 UUID 桥属于证据关系，不声明 `owl:sameAs`。完整图名及内容摘要以 [manifest.json](data/manifest.json) 为准。

## 来源、长度、面积与深度

- 养殖数据固定为 lianggeming14/upload-files 的 `1eb0bab8f86fab00d6ebf62b18e609446957fc9d` 版本，ZIP SHA-256 为 `04891aab2039607015d41575e292a0add57065af3a2037270893cc0f3cd7c4b7`。原始生成器未执行。这是合成场景，ERA5 天气保持 `imported_unverified`。
- 地图固定为 [No1dry/farm 的 e08e80ce 提交](https://github.com/No1dry/farm/tree/e08e80ce4c80ce65051ef93f1247e8797d8781f1)。八份输入和原始图纸摘要已核验；No1dry 作为只读来源，本次修改全部在 lianggeming14 的本体库。
- 全域包含 121 个影像解释对象；五个图纸图层包含 163 个空间表示，其中 100 个田块和 20 个塘面/水面多边形。不同图层保留独立坐标系和身份，不自动拼成已配准地图。
- 全域为局部图像参考像素；图纸为局部 PDF 点坐标。原始轮廓、面积/周长计算和单位保留；局部像素/点坐标不能当作米、平方米或经纬度。
- 图上标注的长度、设计/工程量、测点、证据和复核状态保留为可关联测量。未标注单位不猜单位；采样深度、设计深度和整塘水深不混用。没有可靠来源的实测深度/周长保留未知。
- 20 个图纸塘面按来源表稳定均分演示活动，表内分配数量差不超过 1。六个合成塘口的平均/最大深度、容积等仅通过独立模板关系展示，未写成真实地图对象测量，也未更改来源外键。

地图详情和来源许可证说明见 [farm-map](../../../datasets/farm-map/README.md)。此发布包含来源轮廓和规范化数据；原始卫星图、PDF 不在此重复发布，版权声明及出处保留。

## 实时只读接口

| GET 路径 | 用途 |
| --- | --- |
| `/api/ontology/status` | 实际 Jena 图计数、实时/快照状态 |
| `/api/ontology/children?parent=<IRI>` | 当前本体的直接子类 |
| `/api/ontology/instances?class=<IRI>&offset=0&limit=30` | 所选类及其子类的分页实例；必须指定类 |
| `/api/ontology/resource?iri=<IRI>&limit=500&outgoing_offset=0&incoming_offset=0` | 类型化 RDF 原词项、正/反向关系及两个方向的下一页游标 |

仅查询当前已验证 manifest 的四图白名单；监听 `127.0.0.1`。没有 SQL 查询、任意 SPARQL 输入或写入接口。该本地审查服务不替代原平台的生产认证和权限服务。

## 重建与核验

首先按[SQL 来源样本说明](../review-sample/README.md)准备固定来源包、私有本地连接和现有 10%+依赖样本。源码中的配置模板不含密码。另准备已启动的隔离 Fuseki `http://127.0.0.1:23049/fish_l1`；建图命令不会自动启动服务。

已发布的 `datasets/farm-map` 可直接用于 RDF 重建；若重新取上游数据，先以固定提交的只读目录运行地图准备命令：

```sh
python scripts/prepare_farm_map.py --source-root <No1dry-farm-e08e80ce目录>
python scripts/build_fish_rdf_sample.py --config config/fish-review.example.json
python scripts/verify_fish_rdf_navigation.py
python scripts/check_ontology_review_live.py --base-url http://127.0.0.1:8792
```

RDF 构建在只读可重复读事务中提取 SQL 样本；新图按内容摘要命名，已存在时精确验证并复用。随后依次验证地图、演示分配和完整五图证据。公开分片从实际 Jena 返回值生成；完整来源字符串和约 355 MB 的样本 N-Triples 留在忽略的 `.runtime`，可从固定来源重建。

| 验收 | 实际结果/证据 |
| --- | --- |
| PostgreSQL 原始和类型化来源核验 | [SQL 回读](../review-sample/readback.json)，458,665 个字段值无差异 |
| 四图全部 RDF 术语及 SPARQL 检查 | [rdf-readback.json](rdf-readback.json)，通过 |
| 实际 pySHACL | [shacl-readback.json](shacl-readback.json)，20,548 实例、1,354 字段约束、零违规 |
| 全导航与双向关系 | [navigation-readback.json](navigation-readback.json)，零悬空/错类 |
| 实际 HTTP → SPARQL 全链路 | [live-api-readback.json](live-api-readback.json)，层级、分页、塘口归属、图纸测量、逆关系均通过 |
| Chrome 实际点击、六图层、手机与离线模式 | [browser-report.json](browser-report.json)，零 JavaScript 错误；[桌面地图](screenshots/desktop-map.png)、[手机对象](screenshots/mobile-object.png) |
| 独立复核 | [independent-review.json](independent-review.json)，RDF、精度、证据桥、完整关系分页及前端契约检查 |

浏览器验收脚本也随项目发布：[check_ontology_review_browser.mjs](../../../scripts/check_ontology_review_browser.mjs)。安装 `frontend` 锁定依赖并准备 Playwright Chromium，启动实时审查服务后运行；可通过 `--executable-path` 指定本机 Chrome：

```sh
npm ci --prefix frontend
npm exec --prefix frontend -- playwright install chromium
node scripts/check_ontology_review_browser.mjs --base-url http://127.0.0.1:8792/
```

该脚本重建浏览器报告和七张截图，读取当前 RDF 导航分片并通过实际 HTTP 检查交互。离线降级用拦截 API 的方式验证；它不会执行 RDF 或 SQL 写入。

本轮验证了隔离 PostgreSQL/Jena 实库及本地浏览；并未将 CI、SQLite 或离线截图称为生产/OIDC/现场验收。原正式全量导入与 worker 继续暂停，待本次样本结构审查。设计细节见 [rdf-design.md](rdf-design.md)。

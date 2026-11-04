# 总方案来源地图

来源固定为 [No1dry/farm v0.6.0，提交 e08e80ce](https://github.com/No1dry/farm/tree/e08e80ce4c80ce65051ef93f1247e8797d8781f1)。本目录提供该方案的实际来源轮廓与独立图纸图层，供本体审查页面查询、点击和下载。

| 文件 | 用途 |
| --- | --- |
| [full.svg](full.svg) | 全域红线及 121 个影像判读对象 |
| [detail-miaoxia.svg](detail-miaoxia.svg) | 庙下流（台账称庙下刘）图纸 |
| [detail-xinwumao.svg](detail-xinwumao.svg) | 新屋湾、毛家湾图纸 |
| [detail-zhangjia.svg](detail-zhangjia.svg) | 张家湾图纸 |
| [detail-tanshen.svg](detail-tanshen.svg) | 谭湾沈湾图纸 |
| [detail-abcdef.svg](detail-abcdef.svg) | A/B/C/D/E/F 区图纸 |
| [map-features.json](map-features.json) | 六个局部坐标图层、285 个要素（含一条独立红线） |
| [map-objects.json](map-objects.json) | 284 个来源空间表示的本体审查 IRI、类型、证据和指标 |
| [source-manifest.json](source-manifest.json) | 固定 Git blob、SHA-256、原文件大小及派生输出校验 |
| [verification.json](verification.json) | 来源一致性、几何有效性及独立图层核验 |

全域包括 38 个耕作纹理片区、36 处塘状水面、1 湖、9 林地、9 聚落、3 裸地、20 路和 5 沟。五张图纸另有 100 个田块面、20 个塘面、22 条路渠线，以及 20 个设施文字锚点和 1 个歧义 E3 标签。文字锚点不是设施占地边界，歧义 E3 没有合并到同名田块。

全域的 46 处村落/水体轮廓采用固定上游补充文件中明确标为 `observed` 的修订，保留原轮廓和转换证据。未导入演示设备、生成建筑、作物状态、假设水深或地形。所有来源表示保留 `imported_unverified`：有文件来源不等于已完成现场测绘或验收。

## 坐标与指标

全域采用 `LOCAL_IMAGE_APPROX`：1952×1269 参考图像像素，左上原点、x 向右、y 向下。补充文件中的 2940×1912 原生像素按其声明的 x/y 比例转换到参考图。五张图纸采用各自的 `PDF_LANDSCAPE_LOCAL`，单位 `pt`，仍为左上原点。

JSON 使用 GeoJSON 的几何结构，但**不是 RFC 7946 GeoJSON，经纬度 CRS 为 null**。不得交给默认按 EPSG:4326 处理的地图接口，也不能把五图平移拼接进全域。SVG 可直接打开；坐标并未为展示而重新编造。

`metrics.coordinate_area` / `coordinate_length` 是像素或纸面单位的平面计算。`source_model_metrics` 原样保留上游按截图比例尺估算的模型值，明确不是实测。现场面积、周长、深度、体积继续为 null。台账原值及未知单位保留在 `ledger_area`；原文工程尺寸单独保存在 `documented_dimensions`，不能拿沟深代替塘深。

## 身份与复现

`source_object_iri` 来自上游真实资料集合的持久身份映射；脚本要求每个空间 ID 恰好对应一个 `real/imported_unverified` 来源对象，排除同位置的 `demo/synthetic` 身份。`object_iri` 为独立审查图的 `urn:lzo:fish-review:map:v1:object:` 命名空间，由本体导出器读取；不声称已在生产治理主库注册。演示业务分配应使用独立演示关系，不改变本目录的来源身份和原始业务外键。

在工程目录执行：

```sh
python scripts/prepare_farm_map.py --source-root /path/to/verified/No1dry-farm-source
python -B -m unittest discover -s tests/scripts -p test_prepare_farm_map.py -v
```

生成器只使用 Python 标准库。它先验证全部八个输入的固定 Git blob，再生成输出并将已验证输入缓存至本项目被忽略的 `.runtime/source-imports/no1dry-farm/<commit>/`。不运行上游脚本，不写数据库，不修改来源仓库。公开核验另用 Shapely 检查全部 285 个输出几何。

上游没有统一项目许可证。本次按用户要求复用项目来源轮廓，保留[上游第三方声明](THIRD_PARTY_NOTICES.upstream.md)，不将图纸或卫星资料重新标成 MIT/CC0。未复制卫星截图或整页图纸底图；原文件链接、摘要和来源定位保留在证据中。

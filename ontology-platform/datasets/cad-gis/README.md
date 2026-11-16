# CAD/GIS 公开派生数据

固定来源批次：`057c6984aaead37371a8c6cedfa949762cbfd4fe8aaffc3b4f0355addfd07530`。本目录由 `scripts/export_cad_gis_public.py` 使用显式字段白名单导出；没有复制源文件原件、完整 SourceRecord、原始 GPKG/CSV 数据、私有记录 IRI、数据库或运行目录。

- `map.json`：`lzo-spatial-map/2` 平面地图；面只从 `display_features` 绘制，点/线从 `features` 绘制。
- `objects.json`：258 个候选对象、计算测量、来源文件/行引用；未知深度保持 null。
- `relations.json`：232 条图纸分组和带算法证据的空间关系，不能解释为业务所有权。
- `provenance.json`：11 个来源文件的固定提交/摘要及 86 张来源表的列名与数量；完整 32464 条来源记录保留在私有批次。
- `business.nt`：仅上述公开候选对象/关系的 RDF 投影，可用 RDFLib 按 N-Triples 读取，不等同于全库 RDF 或完整私有来源图。
- `manifest.json`：输出 SHA256、大小、计数与来源批次摘要；没有时间戳或本机路径，重复导出字节稳定。

来源表计数包含 GPKG 元数据/RTree 表，以及 JSON 整份文档和清单记录；来源记录数不是独立实物或资产数量。同一实物候选的多个来源表示仍分别保留于私有批次。

坐标是来源已转换的候选经纬度：display_srid=4326，registration_status=candidate_approximate，original_cad_crs_status=UNKNOWN。显示为平面；没有把未知原始坐标猜测投影，也没有独立确认 CAD 原始 CRS 或现场精度。WGS84 椭球测量是派生计算值，算法/单位/假设与源值分开保存；未知塘深没有用高程代替。

摄像头共 39 个 CAD 摄像头符号候选，不是 39 台已核实真实设备：没有绑定 device_iri、序列号、在线状态或视频入口。设施点来自文字标注锚点，不能称为设施实物插入点；无位置对象仍为 null，不补造坐标。图纸分组不是新增行政区域边界。

源面与显示面口径：72 个田塘规范面；全部规范多边形 75 个（其中道路面 1 个、沟渠面 2 个）。显示分片 81 个，按 kind 为 `{"canal": 1, "field": 71, "pond": 6, "region": 2, "road": 1}`。真实正面积交叠保留全部 object_iris，面片只画一次；道路/沟渠默认隐藏。显示去重不删除来源引用。

复现（在 ontology-platform 目录执行；PRIVATE_BUNDLE_JSON 指向已核验的私有 bundle.json）：

```powershell
python scripts/export_cad_gis_public.py --bundle PRIVATE_BUNDLE_JSON --output-dir datasets/cad-gis
python -m pytest -q tests/local_server/test_cad_public_export.py
```

本目录只证明公开导出边界及派生数据内容；PostgreSQL/PostGIS、Fuseki、浏览器与现场验收记录另行提供。不得把本公开小批次作为旧完整本体库的替换包。

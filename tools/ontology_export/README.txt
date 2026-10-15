梁子湖本体Excel离线导出工具（v0.3兼容）

用途
读取经过人工复核的Excel本体定义，导出可直接作为 POST /api/v1/ontology/packages 请求体的独立JSON文件。该工具不作者或修改Excel，不访问网络，不读取访问令牌，不连接应用服务，不写活动数据库。JSON输出仍需管理员自行审核后另行导入；导出不是现场接入完成。

运行
在项目根目录运行：
  python -B -X utf8 tools/ontology_export/workbook_to_packages.py "工作簿.xlsx" --output-dir "输出目录"
仅检查，不输出JSON：
  python -B -X utf8 tools/ontology_export/workbook_to_packages.py "工作簿.xlsx" --check-only
再次校验已导出JSON及清单哈希：
  python -B -X utf8 tools/ontology_export/validate_packages.py "输出目录"
Windows便利入口：
  tools/ontology_export/导出本体JSON.cmd "工作簿.xlsx" "输出目录"
也可将.xlsx拖到.cmd。脚本先使用当前机器已有的ProgramData/anaconda3/python.exe（如果存在），否则使用PATH中的python；可用环境变量 ONTOLOGY_EXPORT_PYTHON 指定Python可执行文件完整路径。执行目录不影响项目定位。

依赖
使用Python 3与项目implementation/requirements.txt的现有依赖，另需openpyxl（已在当前环境验证3.1.5）。openpyxl仅read_only读取。工具不自动安装软件。不要把活动数据库、凭据、原始现场资产放进交付目录。

工作簿格式
仅支持.xlsx无宏格式。5张导入表：领域包、对象类型、属性定义、关系类型、包依赖。
第1行为机器字段名，第2行为中文说明，第3行开始数据。源字段清单、关系原始证据等其他工作表不参与导入，可完整保留。
enabled必须使用Excel原生TRUE/FALSE；FALSE行会进入validation-report.json中的skipped_rows，不导出。
多值字段为严格JSON数组文本，如 ["lzh:Field"]。不要使用逗号拼接或中文顿号。
机器控制列不得有公式或Excel错误值；即使公式显示正确结果，也必须先转换为显式值。文本标识不得用数值或日期单元格，以免Excel改变精度或版本号。

工作表列
领域包：enabled, package_id, version, namespace, label, description
对象类型：enabled, package_id, version, type_id, identity_type, label, description
属性定义：enabled, package_id, version, property_id, label, description, applies_to, value_type, unit, enum_values, usage, required, cardinality, minimum, maximum
关系类型：enabled, package_id, version, predicate_id, label, description, subject_types, object_types, subject_semantic_types, object_semantic_types, dimension, irreflexive, acyclic
包依赖：enabled, package_id, version, depends_on_package_id, depends_on_version
可保留source_table/source_column/source_sql_type/handling/source_path/source_line/source_url/notes等溯源列；它们不会混入接口JSON。source_sql_type与handling参与不支持类型检查。

数据库契约与限制
1. 每包最多200类、500属性、500关系；语义版本为x.y.z；已发布版本的语义定义不可覆盖。修改结构后需明确新版本和相应引用。
2. value_type仅decimal/string/boolean/integer/enum/datetime；usage为attribute/observation/assertion；required仅适用于attribute。单位必须与接入数据精确对应。
3. applies_to、subject_semantic_types、object_semantic_types只能引用同包type_id。跨包关系使用明确identity_type端点；跨域关系集中为桥接包可避免依赖环。需要业务确认，不能把所有外键当成业务因果。
4. dependencies精确版本必须同时在工作簿启用。工具按依赖顺序输出；缺失、重复或循环会停止导出。
5. 属性handling可为scalar、foreign_key、array_scalar、enum、identity；任何deferred_*、unsupported、excluded、manual_review行只能停用。SQL JSON/JSONB、空间、向量vector、hstore、bytea、xml、record等复合数据不能伪装为普通字符串。明确标量数组仅在array_scalar+many且元素类型已声明时导出。
6. SQL date/time不能自动变成带时区datetime；timestamp对应datetime，但原始时区仍由接入映射显式处理。业务枚举须在enum_values列提供完整可选值。
7. current_v0.3没有通用OWL/继承/JSON/空间属性类型，不自动生成对象、观测、判断、模型结果、映射或现场记录。

输出与验证
每包一份JSON、manifest.json、validation-report.json；manifest声明导入顺序、源工作簿SHA-256、每个请求体文件SHA-256与API路径。再次运行会更新当前清单；旧目录中不在新清单的历史文件不参与验证或导入，建议每次选择新的输出目录。
检查顺序：单元格显式类型→定义重复与引用→JSON Schema→精确依赖拓扑→独立临时SQLite执行当前OntologyService.register_package。临时库结束自动清理，报告明确production_database_touched=false、postgresql_verified=false，不冒充PostgreSQL或真实现场验收。
失败退出码为2并显示错误；只有全部校验通过才开始输出JSON。离线输出不包含或需要认证信息。

源码SQL目录提取
  python -B -X utf8 tools/ontology_export/extract_schema.py "源码迁移目录" --output "schema_catalog.json" --expected-files 44 --collection-method github-textarea --strict
默认固定源提交9995fc20cd84093adcaa3fab954ffe9d08b9f45a，逐条保留CREATE TABLE/ALTER审计，解析各字段、主外键、唯一约束、CHECK和直接枚举及索引；不执行源SQL。--strict在未解析DDL、缺失引用或文件数不符时退出2，仍保留审计目录供修正。函数/触发器/数据更新列在other_statements中，不把其中字符串或$$代码体误当成顶层建表。复杂条件只保留表达式，不推导业务判断。自动推定的约束名称有name_inferred=true，不表示已读取现场数据库中的真实命名。


机器表与预生成包（开发者复现）
  python -B -X utf8 tools/ontology_export/build_catalog_tables.py
默认读取 outputs/liangzihu-ontology-20261015/schema_catalog.json 与 tools/ontology_export/domain_labels.json，生成同目录 workbook_data.json 和 packages/。此步骤仅产生JSON中间数据和定义请求体，不生成Excel或接触现有数据库；Excel另由工作簿构建器渲染。
机器表一一保留来源字段和外键，停用行仍留在工作簿；技术/安全类型默认不导出，users仅保留参与者记录类、凭证属性停用。来源表独立身份类型lzhu:表名，不冒充本库已有field/device等核心身份类型。
源SQL主键只是外部身份依据，源NOT NULL保留source_nullable；目标属性required默认FALSE，全部usage=attribute。这批定义是来源记录目录，不自动建立观测通道或声称全部业务概念已经对齐。
FK列默认停用属性写入，用桥接链接登记；JSON/空间/向量/标识数组保留待映射项。text[]映射many时数组长度1至100，元素空白/业务含义由接入映射复核，SQL空数组需映射为属性缺省。日期仅保留YYYY-MM-DD字符串，不伪造事件时间。
约束枚举表以row_kind区分完整SQL约束与索引。DDL审计覆盖源码结构操作；源码覆盖记录固定提交、文件哈希、条数及来源链接。SQL约束、删除动作和维度建议未自动成为本库执行规则。
首批预生成包manifest使用source_kind=generated_workbook_data及source_data_sha256；用户编辑Excel后再导出时会变为source_workbook/workbook_sha256，区分生成源和人工编辑版本。

来源摘要范围：本次SQL经GitHub公开文件页file content textarea提取，浏览器可能去掉末尾换行；schema_catalog的SHA256与bytes只对应本地提取文本副本，未核验与Git blob原始字节一致。

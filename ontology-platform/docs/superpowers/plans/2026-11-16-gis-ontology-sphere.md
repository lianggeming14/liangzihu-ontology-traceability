# GIS 与本体球网 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整导入已审查的 CAD 空间来源，接入真实 SQL/RDF 发布，并在现有本体浏览器提供平面地图与可旋转的关系球。

**Architecture:** 沿用 Python/PostGIS/Fuseki。不可变来源批次、组合导航快照和独立 RDF 图增量加入完整历史发布；校验后原子发布。浏览器采用同一 release_id 的轻量 JS 模块。

**Tech Stack:** Python、psycopg、rdflib、Shapely、PostGIS、Fuseki、原生 JavaScript/Canvas/SVG。

**Spec:** `docs/superpowers/specs/2026-11-16-gis-ontology-sphere-design.md`，用户于本轮再次明确确认。

## Global Constraints

- 只修改 lianggeming14/liangzihu-ontology-traceability；来源仓库只读。
- 保留原有 180997 实例、178 类及历史 SQL/RDF/导航；以实际基线复核，不能用小批次替换完整发布。
- 原始文件、完整源记录、活动数据库与凭据留在忽略的私有运行目录；公开派生结果遵守既有公开边界。
- 新增命名空间 `urn:lzo:cad-gis:v1:`；业务实例使用 `instance:`，类使用 `class:`，图使用 `graph:`，来源记录使用 `source:`。
- 源 CRS 不确定性、候选定位、合成设备与正式资产明确区分；未知深度保持 null。
- 72 田塘、28 文字锚点、39 摄像头为输入核对目标；解析异常必须报告差额，不凑数。
- 所有输入保留；显示去重不删除来源。未知 CRS 原始点不自动赋予 EPSG4547。
- 只允许写新部署端口 25459 / 23059；原迁移源 25449 / 23049 禁止写入。
- 继承当前会话模型。任务限定文件所有权；控制者统一提交和发布，不执行 force push。

## Review Focus

- 切换版本后迟到响应和旧 Canvas 事件：新页不混入旧节点，卸载清理事件与绘制循环（Task 3）。
- 同一几何来自两文件、真实相交面与无效面：来源均保留，面片只画一次，失败不伪修复（Task 1）。
- 重复关系记录、反向索引、未解析目标：聚合不重复、不泄露原文、不画假目标（Task 2）。
- 导入在 SQL/RDF 完成前失败或 active 改变：旧发布保持，禁止覆盖其他导入结果（Task 4）。
- 可执行内容混入标签/属性与缺失坐标：DOM 安全显示、无猜测点、缺失有明确提示（Task 3）。

## Shared contracts

`lzo-spatial-map/2` JSON: `contract`, `crs` (including display_srid=4326, registration_status=candidate_approximate, original_cad_crs_status=UNKNOWN), `features`, `display_features`, `layers`, `unlocated`, `bounds` ([west,south,east,north]), `quality`, optional `legacy_map_path`.

Feature: `id`, `iri`, `class_iri`, `label`, `kind` (field/pond/facility/camera/road/canal/region), `geometry` (GeoJSON or null), `source_refs` (public file/commit/row evidence, no private raw payload), `attributes` (object), `position_status`, `nature`, `layer_id`. Display feature: `id`, `geometry`, `object_iris` (all memberships), `kind`, `layer_id`, `conflict`. `features` are canonical objects; polygons are drawn from `display_features`, never both arrays. Unlocated records have the same feature fields with null geometry. Layers: `id`, `label`, `visible`.

`lzo-ontology-network/1` JSON: `contract`, `nodes`, `edges`, `counts`. Nodes: `iri`, `label`, `parent_iri`, `instance_count`, `total_instance_count`, `role`. Edges: `id`, `source`, `target`, `predicate`, `label`, `kind` (schema/observed), `count`. HTTP adds `release_id`. Network built only from published classes/canonical outgoing relations plus actual schema; never raw SourceRecord.

All paths below relative to ontology-platform. Absolute Python executable currently `C:/Users/robot/Desktop/ontology/ontology-platform/.venv-local-server/Scripts/python.exe`; Node `C:/Users/robot/.conda/envs/direct/node.exe`. Tools may ignore workdir: explicitly Set-Location before commands. Never print environment secrets.

### Task 1: Complete source intake and planar geometry

**Files:** create `local_server/spatial_source.py`, `local_server/spatial_geometry.py`, `scripts/prepare_cad_gis.py`, `tests/local_server/test_spatial_source.py`, `tests/local_server/test_spatial_geometry.py`; source manifest may reuse `docs/local-server/gis-source-audit-2026-11-16.json` read-only.

**Interfaces:** produce `prepare_cad_bundle(inputs_dir: Path, output_dir: Path, source_manifest: dict) -> dict` in spatial_source. Files reside at inputs_dir/source path. Return and write `bundle.json` with `contract=lzo-cad-batch/1`, `batch_id` (64 hex digest), `namespace`, `source_files`, `source_tables`, `source_records`, `objects`, `relations`, `map`, `quality`, `counts`. Each source table has file_id/name/columns/row_count. Source record has stable id/file_id/table/row_number/payload/status/issues; bytes preserved as base64 tagged values. Each object uses shared feature shape plus `class_key`; each relation is subject/predicate/object/evidence/status. All files' Git blob and size checked; SHA256 retained. `map` follows shared contract.

- [ ] Add behavior tests: small real SQLite GPKG with metadata and binary geometry retains every column/row; all CSV strings retained; wrong hash fails; unknown CRS does not become display coordinate; original heights preserved.
- [ ] Run tests and record expected missing-function failures.
- [ ] Implement intake for JSON/CSV/GPKG/report text, read all user/source metadata tables. Parse GPKG geometry header/WKB but retain original bytes. Quarantine geometry problems while preserving record.
- [ ] Implement canonical 107 CAD objects, 39 separate camera candidates, roads/canals and diagram regions. Preserve 67 duplicate source references, use CAD code for stable identity. Include relationships to source diagram regions and evidence-bearing point-in-polygon only, not business ownership.
- [ ] Compute geodesic/projected area/perimeter/length with explicit method/units/assumptions; source values retained separately. Use source declared transformed lon/lat, no raw unknown projection.
- [ ] Add geometry tests: duplicated polygon drawn once, crossing polygons yield non-overlapping faces with all memberships; a polygon hole remains a hole; invalid polygon recorded not silently fixed; all valid positioned features included in bounds. In local metre projection use area tolerance 1e-6 m2 solely for numerical comparisons, no simplification/snapping of source boundaries.
- [ ] Implement display partition using Shapely boundary union/polygonize and representative-point coverage. Original geometry untouched. Road/canal default hidden; gross anomalous lengths reported and excluded from initial fit with explicit flag.
- [ ] Run scoped pytest; controller runs real source preparation and compares source inventory. Report file ownership and tests; controller commits this task.

### Task 2: Real ontology network read model and versioned API

**Files:** create `local_server/network.py`, `tests/local_server/test_network.py`; modify `local_server/query.py`, `local_server/http.py`, corresponding query/http tests. Own backend HTTP whitelist additions for Task 3 modules.

**Interfaces:** produce `build_network(navigation_dir: Path, manifest: dict, *, schema_graph=None) -> dict` and `write_network(navigation_dir: Path, manifest: dict, *, schema_graph=None) -> dict` writing `data/ontology-network.json` and private-safe paginated relationship index as necessary. Existing navigation has class index/detail/relation shards; inspect actual formats, support both legacy inline and sharded. Schema graph is rdflib Graph of actual published schema statements. Network adheres shared contract. Add QueryService.network() and network_relations(source, predicate, target, *, limit=None, cursor=None) returning whitelisted business endpoints with bounded release-bound pagination. API actions `network` and `network-relations`; query parameters source/predicate/target/limit/cursor/release_id. Network can also be loaded as a versioned static public file.

- [ ] Test literal fixtures: two canonical outgoing A→B records with same triple count once for unique triple, one incoming mirror adds zero; unresolved target not a node/edge; class pair/predicate counts correct; private source_record_iri never emitted.
- [ ] Record red test, implement streaming aggregation with canonical edge and triple de-duplication; retain separate unique_record/unique_triple/unresolved counts. Do not silently clip whole class graph.
- [ ] Test schema uses only rdfs:subClassOf and owl:ObjectProperty domain/range; datatype properties add no class edges; actual relations expose direction and counts.
- [ ] Add API/static routes with exact existing containment/hash rules and release pinning. Add UI filenames `spatial-map.mjs`, `ontology-sphere.mjs`, `sphere-math.mjs`; data files `ontology-network.json`, `legacy-map-features.json` and any narrowly scoped new shard paths required. No broad static path allowlist.
- [ ] Test unknown historical network yields explicit empty/unavailable data; forged cursor, cross-release cursor, invalid/private identifiers rejected; limit enforced.
- [ ] Run scoped pytest and report memory/runtime for full published navigation if available. Controller commits task.

### Task 3: Main-entry map and interactive ontology sphere

**Files:** create `docs/fish/ontology-review/spatial-map.mjs`, `ontology-sphere.mjs`, `sphere-math.mjs` and corresponding `.test.mjs`; modify `assets.js`, `assets.css`, `index.html`, `model.mjs` only if new route support needed. No backend edits.

**Interfaces:** consume shared map/network JSON. Export `mountSpatialMap(container, data, {onSelect, onLegacy, releaseId}) -> {destroy()}` and `mountOntologySphere(container, data, {onSelectClass, onSelectEdge, releaseId}) -> {destroy()}`. onSelect gets business IRI/class; onSelectClass gets class IRI; onSelectEdge gets full edge. Integrate existing `snapshots` fetch/bridge and render token rather than bypassing versioning. Endpoint `/api/v1/network` and `/api/v1/network-relations` from Task 2; static fallback `data/ontology-network.json`.

- [ ] Test sphere projection/rotation deterministic known vectors, pointer drag threshold separates click, finite depth/zoom limits and target picking. Run red first.
- [ ] Implement Canvas 3D sphere projection (not geographic globe) with depth sort, DPR resize, mouse/pointer drag rotate, wheel zoom, selectable class nodes and edges; show counts/predicate/direction, filters, connected-neighbor highlight. Actual edge list only, no generated relations. Keep keyboard-accessible node/detail list.
- [ ] Implement 2D SVG/Canvas geographic map from display features once, supporting Polygon holes/MultiPolygon, point markers, line toggles, pan/zoom/fit and region selection. Label candidate camera vs facility text anchor clearly. Detail card shows measurements, uncertainty, area memberships and links into existing instance browser. Include unlocated directory and historical map switch.
- [ ] Add network nav tab, main #view=map route dispatch based on contract, #view=network route. Class/instance selection uses existing hierarchy/details (no all-data dump). Empty/missing network displays a useful message.
- [ ] Test map invariants, safe malicious labels, null coordinates, feature bounds, release switch dropping stale loads, destroy removes listeners/RAF, drag does not navigate. Use Node tests appropriate to pure functions and existing browser test harness when available.
- [ ] Run Node and existing ontology model regression tests; controller performs real browser checks after deployment. Controller commits task.

### Task 4: Append-only SQL/RDF storage and composite publication

**Files:** create `local_server/spatial_publish.py`, `local_server/spatial_rdf.py`, `scripts/import_cad_gis.py`, `tests/local_server/test_spatial_publish.py`; small Store changes only if compare-and-swap publication is absent, coordinate with controller.

**Interfaces:** consume Task 1 bundle and Task 2 build_network; expose `publish_cad_bundle(config, bundle_path: Path, *, progress=None) -> dict`. Use existing Store/config/release paths. New schema `cad_<batch_id first24>` and graph `urn:lzo:cad-gis:v1:graph:<batch_id>`. Schema includes source_files/source_tables/source_records/objects/relations/geometries/metadata; preserve every value and source field, original and display geometry with documented SRIDs. Publish only after full checks and expected-parent active comparison.

- [ ] Test composition retains all old classes/index/detail/relation files, graphs and SQL schemas; adds GIS objects/classes without collision. Existing map copied to data/legacy-map-features.json; map version 2 replaces only current map snapshot. Null/missing device geometry stays unlocated.
- [ ] Run red; implement append-only SQL copy and all-row readback (including binary/JSON and PostGIS geometry), idempotent immutable retries refusing mismatch. Source ports forbidden. No live DB overwrite/drop.
- [ ] Generate OWL/RDF candidate classes, instances, object properties, typed measurements, provenance/geometry evidence/quality; validate SHACL and exact RDF terms after load. Public labels/properties navigable; raw records private. Include source diagram grouping and spatial candidates without inventing established asset matches.
- [ ] Copy immutable old navigation, add new class/instance/detail shards and RDF schema; class/ancestor counts computed consistently. Merge latest 24 synthetic devices into unlocated display by existing IRI, avoid historic double-count. Preserve complete old manifest metadata and named graphs.
- [ ] Compose network from all old/new canonical relations and actual schema; write hashes for all public files. Tests cover missing target, checksum mismatch, changed active parent and failure before activation; old active must remain.
- [ ] On native configured server run full SQL readback, RDF exact-term readback, SHACL, endpoint existence, file hashes then publish atomically. Keep old release selectable. Controller captures pre/post inventories and evidence.
- [ ] Run scoped pytest and report native tests separately from offline. Controller commits task.

### Task 5: Deployment, browser acceptance, guide and GitHub sync

**Files:** update `docs/local-server/README.md` or existing user guide; create `docs/local-server/gis-sphere-acceptance-2026-11-16.json` and public screenshots/report; controller owns runtime scripts and scoped integration fixes.

**Interfaces:** use Tasks 1–4 outputs; actual Config.review_dir controls deployment UI. Stable installation is ontology-platform under root, worktree code is isolated at .github-upload/server-current/ontology-platform.

- [ ] Repair baseline test invocation directory only, run existing local-server tests. Record pass/fail/skip; don't count environmental setup failures as product regressions.
- [ ] Download pinned 11 source files under ignored input directory and verify Git blobs/sizes/SHA256. Run full preparation and audit total source rows, errors, duplicates, feature kinds and geometry conflicts.
- [ ] Verify ownership of local ports/processes, configured data directory and active release without exposing credentials; capture read-only inventory. Install missing pinned dependency only if required; lifecycle changes target owned deployment only.
- [ ] Run composite import, verify old graphs/tables and instance baseline retained, compare API and SQL/RDF counts, exercise historical release and rollback selection without dropping data.
- [ ] Deploy backward-compatible UI to actual review_dir and stable code; restart owned services only as needed. Browser checks: map not blank/stacked, 2D fit and layers, object→instance→relation, missing-device directory, sphere drag/zoom/click/filter, viewport resize/mobile, version stale-response behavior.
- [ ] Fresh independent code review covers source completeness, RDF privacy/integrity, publish race/idempotency, UI correctness and all spec requirements; fix material findings and recheck changed scope.
- [ ] Write simple local start/stop/import/backup/move-machine guide additions and acceptance report with data-nature and test distinctions.
- [ ] Scan exact changed/new artifacts, use tools/sync_to_github.py when applicable, reconcile remote main, push without force, verify remote commit/files; mirror normal project outputs to stable workspace. Do not upload active databases, private sources, secrets or dependencies.

## Plan self-review

All design sections map to Tasks 1–5. Shared shapes, namespaces and filenames fixed above; tasks do not share mutable source files except controller-gated integration. Numerical tolerance affects validation only, not boundary editing. User confirmation authorizes continuous implementation and ordinary GitHub sync; no additional design permission step is required.

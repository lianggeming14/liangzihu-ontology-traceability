"""RDF projection and RDF-derived navigation for the independent source map graph."""
from collections import defaultdict
import hashlib
import json
from urllib.parse import quote

from rdflib import Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD

from fish_rdf_sample import C, PROV, STATE, V, typed_literal
from prepare_farm_map import _geometry


NS = "urn:lzo:fish-review:map:v1:"
M = Namespace(NS)
KINDS = {
    "field": ("Field", "田块来源表示", "Field"),
    "pond": ("Pond", "塘面来源表示", "Pond"),
    "lake": ("Lake", "湖泊来源表示", "Lake"),
    "woodland": ("Woodland", "林地来源表示", "Woodland"),
    "settlement": ("Settlement", "聚落来源表示", "Settlement"),
    "bare": ("Bare", "裸地来源表示", "Bare"),
    "road": ("Road", "道路来源表示", "Road"),
    "channel": ("Channel", "沟渠来源表示", "Channel"),
    "facility": ("Facility", "设施文字锚点", "Facility"),
    "unresolved_label": ("UnresolvedLabel", "未决图纸标签", "UnresolvedLabel"),
    "layer": ("Layer", "独立来源图层", "SpatialLayer"),
}
DOMAIN_PARENTS = {"Field": "BusinessEntity", "Pond": "Aquaculture", "SpatialLayer": "BusinessEntity"}
DOMAIN_LABELS = {"Field": "田块", "Pond": "鱼塘", "SpatialLayer": "空间资料", "Lake": "湖泊",
                 "Woodland": "林地", "Settlement": "聚落", "Bare": "裸地", "Road": "道路",
                 "Channel": "沟渠", "Facility": "设施来源", "UnresolvedLabel": "未决标签"}
FIELDS = {
    "spatial_id": ("来源空间编号", XSD.string), "kind": ("来源类型", XSD.string),
    "asset_id": ("独立图层编号", XSD.string), "canonical_key": ("来源稳定键", XSD.string),
    "coordinate_space": ("坐标空间", XSD.string), "coordinate_units": ("坐标单位", XSD.string),
    "georeferenced": ("已完成地理配准", XSD.boolean), "boundary_status": ("边界依据", XSD.string),
    "geometry": ("局部坐标几何", RDF.JSON), "original_geometry": ("原版来源几何", RDF.JSON),
    "geometry_provenance": ("几何推导依据", RDF.JSON), "view_box": ("图层显示范围", RDF.JSON),
    "coordinate_area": ("局部坐标平面面积", XSD.decimal), "coordinate_length": ("局部坐标线长或周长", XSD.decimal),
    "surveyed_area_m2": ("实测面积（未提供）", XSD.decimal),
    "surveyed_perimeter_m": ("实测周长（未提供）", XSD.decimal),
    "depth_m": ("实测水深（未提供）", XSD.decimal), "volume_m3": ("实测体积（未提供）", XSD.decimal),
    "ledger_area": ("台账面积原值", XSD.decimal), "ledger_area_unit": ("台账明确单位", XSD.string),
    "documented_dimensions": ("来源注明工程尺寸", RDF.JSON), "region": ("来源区域", XSD.string),
    "source_code": ("原始图纸编号", XSD.string), "upstream_object_iri": ("上游资料对象 IRI", XSD.anyURI),
    "approximate_model_area_m2": ("上游截图比例估算模型面积（非实测）", XSD.decimal),
    "approximate_model_length_m": ("上游截图比例估算模型长度（非实测）", XSD.decimal),
    "metres_per_reference_pixel": ("上游截图比例尺近似换算", XSD.decimal),
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _literal(value, datatype):
    if datatype == RDF.JSON:
        return Literal(_json(value), datatype=RDF.JSON, normalize=False)
    if datatype == XSD.anyURI:
        return Literal(value, datatype=XSD.anyURI, normalize=False)
    spec = {XSD.decimal: "number", XSD.integer: "integer", XSD.boolean: "boolean"}.get(datatype, "string")
    return typed_literal(value, {"type": spec})


def _values(item, layer=False):
    values = {"spatial_id": item["id"], "kind": "layer" if layer else item["kind"],
              "asset_id": item["id"] if layer else item["asset_id"],
              "coordinate_space": item["coordinate_space"],
              "coordinate_units": item["units"] if layer else item["coordinate_units"], "georeferenced": False}
    if layer:
        values["view_box"] = item["viewBox"]
        return values, {}
    for key in ("canonical_key", "boundary_status", "geometry", "original_geometry", "geometry_provenance",
                "documented_dimensions", "region", "source_code"):
        if key in item:
            values[key] = item[key]
    values["upstream_object_iri"] = item.get("source_object_iri")
    metrics = item.get("metrics", {})
    units = {"surveyed_area_m2": "m2", "surveyed_perimeter_m": "m", "depth_m": "m", "volume_m3": "m3"}
    for key in ("coordinate_area", "coordinate_length"):
        values[key] = metrics.get(key, {}).get("value")
        units[key] = metrics.get(key, {}).get("unit")
    for key in ("surveyed_area_m2", "surveyed_perimeter_m", "depth_m", "volume_m3"):
        values[key] = metrics.get(key)
    values["ledger_area"] = item.get("ledger_area", {}).get("value")
    values["ledger_area_unit"] = item.get("ledger_area", {}).get("unit")
    units["ledger_area"] = values["ledger_area_unit"]
    model = item.get("source_model_metrics", {})
    values.update(approximate_model_area_m2=model.get("area_m2"), approximate_model_length_m=model.get("length_m"),
                  metres_per_reference_pixel=model.get("scale_metres_per_reference_pixel"))
    units.update(approximate_model_area_m2="m2 (screenshot approximation)",
                 approximate_model_length_m="m (screenshot approximation)", metres_per_reference_pixel="m/reference_image_pixel (approximate)")
    return values, units


def project_map(payload):
    """Yield complete map RDF, including six layer instances and navigable membership."""
    if payload.get("schema_version") != "farm-map-objects/1":
        raise ValueError("Unsupported map source contract")
    layers = {x["id"]: x for x in payload["coordinate_spaces"]}
    if len(layers) != len(payload["coordinate_spaces"]):
        raise ValueError("Duplicate map layer")
    ids = set()
    for item in payload["objects"]:
        sid, kind = item["id"], item["kind"]
        if kind not in KINDS or kind == "layer" or sid in ids:
            raise ValueError("Duplicate or unknown map source identity")
        ids.add(sid)
        if (item["object_iri"] != NS + "object:" + quote(sid, safe="-._~")
                or item["class_iri"] != NS + "class:" + KINDS[kind][0]):
            raise ValueError("Map IRI/class differs from the reviewed source contract")
        if (item["data_nature"] != "imported_unverified" or item.get("georeferenced") is not False
                or item.get("crs") is not None):
            raise ValueError("Map nature/coordinate claims differ from source evidence")
        layer = layers.get(item["asset_id"])
        if layer is None or item["parent_iri"] != NS + "layer:" + item["asset_id"]:
            raise ValueError("Map has a dangling layer")
        if item["coordinate_space"] != layer["coordinate_space"] or item["coordinate_units"] != layer["units"]:
            raise ValueError("Map mixes independent coordinate spaces")
        if not item.get("source_evidence"):
            raise ValueError("Map source evidence is missing")
        _geometry(item["geometry"])
    for layer in layers.values():
        if layer.get("georeferenced") is not False or layer.get("crs") is not None:
            raise ValueError("Layer falsely claims georeferencing")
    dataset = M["dataset:" + payload["source"]["commit"]]
    yield dataset, RDF.type, OWL.Ontology
    yield dataset, RDFS.label, Literal("总方案来源空间审查图", lang="zh")
    yield dataset, V.adoptionStatus, Literal(STATE)
    yield dataset, V.formalAdoption, Literal(False)
    yield dataset, M.sourceRepository, URIRef(payload["source"]["repository"])
    yield dataset, M.sourceCommit, Literal(payload["source"]["commit"])
    kinds = sorted({x["kind"] for x in payload["objects"]} | {"layer"})
    for domain in sorted({KINDS[k][2] for k in kinds}):
        yield C[domain], RDF.type, OWL.Class
        yield C[domain], RDFS.label, Literal(DOMAIN_LABELS[domain], lang="zh")
        yield C[domain], V.conceptRole, Literal("domain")
        yield C[domain], RDFS.subClassOf, C[DOMAIN_PARENTS.get(domain, "SpatialLayer")]
    for kind in kinds:
        name, label, domain = KINDS[kind]
        cls = M["class:" + name]
        yield cls, RDF.type, OWL.Class
        yield cls, RDFS.label, Literal(label, lang="zh")
        yield cls, RDFS.subClassOf, C[domain]
        yield cls, V.sourceTable, Literal("map_" + kind)
        yield cls, V.conceptRole, Literal("spatial")
    for field, (label, datatype) in FIELDS.items():
        prop = M["property:" + field]
        yield prop, RDF.type, OWL.DatatypeProperty
        yield prop, RDFS.label, Literal(label, lang="zh")
        yield prop, RDFS.range, datatype
        yield prop, V.sourceField, Literal(field)
    yield M.inLayer, RDF.type, OWL.ObjectProperty
    yield M.inLayer, RDFS.label, Literal("属于独立来源图层", lang="zh")
    yield M.hasRepresentation, RDF.type, OWL.ObjectProperty
    yield M.hasRepresentation, RDFS.label, Literal("包含来源空间表示", lang="zh")
    yield M.inLayer, OWL.inverseOf, M.hasRepresentation
    evidence_seen = set()
    for is_layer, item in [(True, v) for v in layers.values()] + [(False, v) for v in payload["objects"]]:
        sid = item["id"]
        kind = "layer" if is_layer else item["kind"]
        subject = M["layer:" + sid] if is_layer else URIRef(item["object_iri"])
        source_record = M["source:" + ("layer:" if is_layer else "object:") + quote(sid, safe="-._~")]
        yield subject, RDF.type, M["class:" + KINDS[kind][0]]
        yield subject, RDFS.label, Literal(item["label"])
        yield subject, V.sourceTable, Literal("map_" + kind)
        yield subject, V.sourcePK, Literal(sid)
        yield subject, V.dataNature, Literal("imported_unverified")
        yield subject, V.adoptionStatus, Literal(STATE)
        yield subject, PROV.wasDerivedFrom, source_record
        yield source_record, RDF.type, PROV.Entity
        yield source_record, M.sourceRepository, URIRef(payload["source"]["repository"])
        yield source_record, M.sourceCommit, Literal(payload["source"]["commit"])
        yield source_record, M.coordinateSpace, Literal(item["coordinate_space"])
        source_evidence = item.get("source_evidence", []) if not is_layer else [{
            "path": "public/models/manifest.json" if sid == "full" else "data/spatial/drawing-entities.json",
            "asset_id": sid, "source_file": item.get("source_file"), "sha256": item.get("source_sha256")}]
        yield source_record, M.sourceEvidence, _literal(source_evidence, RDF.JSON)
        if item.get("boundary_status") is not None:
            yield source_record, M.boundaryStatus, Literal(item["boundary_status"])
        if item.get("source_object_iri"):
            yield source_record, M.upstreamObject, URIRef(item["source_object_iri"])
        for entry in source_evidence:
            evidence_id = hashlib.sha256(_json(entry).encode("utf-8")).hexdigest()
            evidence = M["evidence:" + evidence_id]
            yield source_record, PROV.wasDerivedFrom, evidence
            if evidence_id in evidence_seen:
                continue
            evidence_seen.add(evidence_id)
            yield evidence, RDF.type, PROV.Entity
            for field, value in entry.items():
                if value is not None and not isinstance(value, (dict, list)):
                    yield evidence, M["evidenceProperty:" + field], Literal(value)
        values, units = _values(item, is_layer)
        yield subject, M.propertyUnits, _literal(units, RDF.JSON)
        for field, value in values.items():
            prop = M["property:" + field]
            if value is None:
                yield subject, V.missingField, prop
            else:
                yield subject, prop, _literal(value, FIELDS[field][1])
        if not is_layer:
            target = URIRef(item["parent_iri"])
            yield subject, M.inLayer, target
            yield target, M.hasRepresentation, subject
            edge = M["edge:inLayer:" + quote(sid, safe="-._~")]
            yield edge, RDF.type, V.RelationRecord
            yield edge, RDF.subject, subject
            yield edge, RDF.predicate, M.inLayer
            yield edge, RDF.object, target
            yield edge, V.sourceField, Literal("asset_id")
            yield edge, V.resolution, Literal("resolved")


class MapNavigation:
    """Derive every public instance/property/relationship from returned RDF triples."""
    def __init__(self):
        self.records = defaultdict(lambda: defaultdict(set))

    def add(self, subject, predicate, value):
        if str(subject).startswith((NS, str(C))):
            self.records[str(subject)][str(predicate)].add(value)

    def finish(self):
        records = self.records
        def one(subject, predicate, default=None):
            values = records.get(subject, {}).get(str(predicate), set())
            if len(values) > 1:
                raise ValueError(f"Ambiguous map RDF value: {subject} {predicate}")
            return str(next(iter(values))) if values else default
        concepts, tables, instances = {}, {}, {}
        for subject, values in records.items():
            if OWL.Class not in values.get(str(RDF.type), set()) or one(subject, V.conceptRole) is None:
                continue
            table = one(subject, V.sourceTable)
            concepts[subject] = {"iri": subject, "label": one(subject, RDFS.label, subject),
                                 "parent_iri": one(subject, RDFS.subClassOf), "children": [], "table": table,
                                 "role": one(subject, V.conceptRole), "instance_count": 0, "total_instance_count": 0,
                                 "instances_path": "classes/" + table + ".json" if table else None}
            if table:
                tables[table] = {"contract": "fish-rdf-review/1", "class_iri": subject, "instances": []}
        for subject, values in records.items():
            if not subject.startswith((NS + "object:", NS + "layer:")):
                continue
            cls, table = one(subject, RDF.type), one(subject, V.sourceTable)
            if cls not in concepts or table not in tables or tables[table]["class_iri"] != cls:
                raise ValueError("Map RDF instance has no declared source class")
            if one(subject, V.adoptionStatus) != STATE or one(subject, V.dataNature) != "imported_unverified":
                raise ValueError("Map RDF adoption/nature differs from the source review contract")
            source = one(subject, PROV.wasDerivedFrom)
            if not source or source not in records:
                raise ValueError("Map RDF has no source record")
            property_units = json.loads(one(subject, M.propertyUnits, "{}"))
            missing = {str(v) for v in values.get(str(V.missingField), set())}
            props = []
            for prop in sorted({p for p in values if p.startswith(NS + "property:")} | missing):
                field, datatype = one(prop, V.sourceField), one(prop, RDFS.range)
                if field is None or datatype is None:
                    raise ValueError("Map RDF property declaration missing")
                value = one(subject, prop)
                if value is not None and datatype == str(XSD.boolean):
                    if value not in {"true", "false"}:
                        raise ValueError("Invalid RDF boolean")
                    value = value == "true"
                elif value is not None and datatype == str(XSD.integer):
                    value = int(value)
                elif value is not None and datatype == str(RDF.JSON):
                    value = json.loads(value)
                props.append({"iri": prop, "field": field, "label": one(prop, RDFS.label, field), "value": value,
                              "datatype": datatype, "unit": property_units.get(field), "nature": "imported_unverified"})
            item = {"iri": subject, "id": one(subject, V.sourcePK), "table": table, "label": one(subject, RDFS.label),
                    "class_iri": cls, "nature": "imported_unverified", "adoption_status": STATE, "properties": props,
                    "outgoing": [], "incoming": [], "unresolved_relations": [],
                    "provenance": {"source_record_iri": source, "source_evidence": json.loads(one(source, M.sourceEvidence, "[]")),
                                   "coordinate_space": one(source, M.coordinateSpace), "boundary_status": one(source, M.boundaryStatus),
                                   "repository": one(source, M.sourceRepository), "commit": one(source, M.sourceCommit),
                                   "source_object_iri": one(source, M.upstreamObject), "formal_adoption": False}}
            instances[subject] = item
            tables[table]["instances"].append(item)
            concepts[cls]["instance_count"] += 1
        for subject in records:
            if not subject.startswith(NS + "edge:"):
                continue
            source, target, predicate = one(subject, RDF.subject), one(subject, RDF.object), one(subject, RDF.predicate)
            if source not in instances or target not in instances or predicate != str(M.inLayer):
                raise ValueError("Map RDF relationship target/source is missing")
            if (URIRef(target) not in records[source].get(str(M.inLayer), set())
                    or URIRef(source) not in records[target].get(str(M.hasRepresentation), set())):
                raise ValueError("Map RDF relationship forward/inverse triples missing")
            src, dst = instances[source], instances[target]
            edge = {"iri": predicate, "edge_iri": subject, "field": one(subject, V.sourceField),
                    "label": one(predicate, RDFS.label), "resolution": one(subject, V.resolution),
                    "source_row": None, "list_index": None}
            if edge["resolution"] != "resolved":
                raise ValueError("Map layer relationship was not resolved")
            src["outgoing"].append({**edge, "target_iri": target, "target_id": dst["id"],
                                    "target_label": dst["label"], "target_class_iri": dst["class_iri"]})
            dst["incoming"].append({**edge, "source_iri": source, "source_id": src["id"],
                                    "source_label": src["label"], "source_class_iri": src["class_iri"]})
        for item in concepts.values():
            if item["parent_iri"] in concepts:
                concepts[item["parent_iri"]]["children"].append(item["iri"])
        def count(iri, visiting):
            if iri in visiting:
                raise ValueError("Map concept hierarchy cycle")
            item = concepts[iri]
            item["children"].sort()
            item["total_instance_count"] = item["instance_count"] + sum(count(child, visiting | {iri}) for child in item["children"])
            return item["total_instance_count"]
        for iri, item in concepts.items():
            if item["parent_iri"] not in concepts:
                count(iri, set())
        for table in tables.values():
            table["instances"].sort(key=lambda item: (item["id"], item["iri"]))
            for item in table["instances"]:
                item["outgoing"].sort(key=lambda e: e["edge_iri"])
                item["incoming"].sort(key=lambda e: e["edge_iri"])
        return sorted(concepts.values(), key=lambda c: c["iri"]), tables

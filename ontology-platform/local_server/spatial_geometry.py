"""Candidate CAD geometry: lossless originals, derived flat display, explicit evidence.

This module never assigns a CRS to raw CAD coordinates or repairs boundaries.
Its inputs must already be source-declared longitude/latitude geometries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from pyproj import CRS, Geod, Transformer
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, transform, unary_union
from shapely.validation import explain_validity


AREA_TOLERANCE_M2 = 1e-6
ANOMALOUS_LINE_LENGTH_M = 10_000
GEOD = Geod(ellps="WGS84")
CRS_POLICY = {"display_srid": 4326, "registration_status": "candidate_approximate",
              "original_cad_crs_status": "UNKNOWN", "display_z": 0}
LAYER_LABELS = {"field": "田块候选范围", "pond": "塘口候选范围", "facility": "设施文字锚点",
                "camera": "摄像头候选", "road": "道路参考", "canal": "沟渠参考", "region": "图纸分组与交叠面"}


def _json_geometry(geometry):
    return json.loads(json.dumps(mapping(geometry)))


def _flat_shape(geometry):
    return transform(lambda x, y, z=None: (x, y), shape(geometry))


def _valid_display_shape(geometry):
    candidate = _flat_shape(geometry)
    if candidate.is_empty:
        raise ValueError("empty_geometry")
    if not candidate.is_valid:
        raise ValueError(explain_validity(candidate))
    west, south, east, north = candidate.bounds
    if not all(math.isfinite(v) for v in candidate.bounds) or west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("outside_longitude_latitude_range")
    return candidate


def compute_measurements(geometry):
    """Geodesic values are derived from candidate lon/lat, never survey claims."""
    value = _valid_display_shape(geometry)
    result = {"method": "pyproj.Geod WGS84 ellipsoidal geodesic", "units": {"area": "m2", "length": "m", "perimeter": "m"},
              "assumptions": "Source-declared candidate longitude/latitude; original CAD CRS UNKNOWN; not field verified.",
              "area_m2": None, "perimeter_m": None, "length_m": None}
    if value.geom_type in {"Polygon", "MultiPolygon"}:
        polygons = [value] if value.geom_type == "Polygon" else list(value.geoms)
        measures = [GEOD.geometry_area_perimeter(orient(p, sign=1.0)) for p in polygons]
        result["area_m2"] = sum(abs(area) for area, _ in measures)
        # Include interior rings in boundary length, rather than only the exterior.
        result["perimeter_m"] = GEOD.geometry_length(value.boundary)
    elif value.geom_type in {"LineString", "MultiLineString"}:
        result["length_m"] = GEOD.geometry_length(value)
    return result


def partition_polygons(features):
    """Polygonize an unsnapped boundary union; each positive face is drawn once.

    Membership is determined by representative-point coverage in a local metre
    projection. The 1e-6 m2 tolerance only distinguishes numerical conflict area;
    no positive face is removed, simplified, snapped, or assigned a sole owner.
    """
    quality = {"area_tolerance_m2": AREA_TOLERANCE_M2, "invalid_geometry": [], "conflict_faces": [],
               "partition_method": "local AEQD metres; boundary unary_union/polygonize; representative-point covers",
               "boundaries_simplified": False, "boundaries_snapped": False}
    valid = []
    for feature in features:
        geometry = feature.get("geometry")
        if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        try:
            valid.append((feature, _valid_display_shape(geometry)))
        except (ValueError, TypeError, KeyError, GEOSException) as exc:
            quality["invalid_geometry"].append({"iri": feature["iri"], "reason": str(exc), "action": "quarantined_without_repair"})
    if not valid:
        return {"display_features": [], "quality": quality}
    west = min(g.bounds[0] for _, g in valid)
    south = min(g.bounds[1] for _, g in valid)
    east = max(g.bounds[2] for _, g in valid)
    north = max(g.bounds[3] for _, g in valid)
    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m +no_defs")
    forward = Transformer.from_crs(4326, local_crs, always_xy=True)
    backward = Transformer.from_crs(local_crs, 4326, always_xy=True)
    quality["partition_crs"] = local_crs.to_string()
    projected = [(f, transform(forward.transform, g)) for f, g in valid]
    boundaries = unary_union([g.boundary for _, g in projected])
    faces = []
    for face in polygonize(boundaries):
        point = face.representative_point()
        members = [f for f, g in projected if g.covers(point)]
        if not members:
            continue  # Unowned inner rings remain holes.
        memberships = sorted({f["iri"] for f in members})
        digest = hashlib.sha256(face.normalize().wkb + "\0".join(memberships).encode()).hexdigest()
        conflict = len(memberships) > 1
        kinds = {f["kind"] for f in members}
        kind = next(iter(kinds)) if len(kinds) == 1 else "region"
        display = {"id": "face-" + digest, "geometry": _json_geometry(transform(backward.transform, face)),
                   "object_iris": memberships, "kind": kind, "layer_id": kind, "conflict": conflict}
        faces.append(display)
        if conflict:
            quality["conflict_faces"].append({"id": display["id"], "object_iris": memberships,
                                             "area_m2": face.area, "above_numerical_tolerance": face.area > AREA_TOLERANCE_M2})
    return {"display_features": sorted(faces, key=lambda row: row["id"]), "quality": quality}


def build_spatial_map(features):
    """Return the public map DTO without mutating canonical source geometries."""
    located, unlocated, bounds_geometries, invalid, anomalous = [], [], [], [], []
    for original in features:
        feature = copy.deepcopy(original)
        feature.pop("source_record_ids", None)
        geometry = feature.get("geometry")
        feature.setdefault("attributes", {})
        if not geometry:
            unlocated.append(feature)
            continue
        try:
            flat = _valid_display_shape(geometry)
            flat_json = _json_geometry(flat)
            if flat_json != geometry:
                feature["attributes"]["original_geometry"] = geometry
            feature["geometry"] = flat_json
            measured = compute_measurements(flat_json)
            feature["attributes"]["computed_measurements"] = measured
            is_anomaly = feature["kind"] in {"road", "canal"} and (measured["length_m"] or 0) > ANOMALOUS_LINE_LENGTH_M
            feature["attributes"]["exclude_from_initial_fit"] = is_anomaly
            if is_anomaly:
                anomalous.append({"iri": feature["iri"], "length_m": measured["length_m"],
                                  "threshold_m": ANOMALOUS_LINE_LENGTH_M, "action": "retained_excluded_from_initial_fit"})
            else:
                bounds_geometries.append(flat)
            located.append(feature)
        except (ValueError, TypeError, KeyError, GEOSException) as exc:
            invalid.append({"iri": feature["iri"], "reason": str(exc), "action": "quarantined_without_repair"})
            feature["attributes"]["original_geometry"] = geometry
            feature["geometry"] = None
            feature["position_status"] = "invalid_geometry_quarantined"
            unlocated.append(feature)
    partition = partition_polygons(located)
    quality = partition["quality"]
    quality["invalid_geometry"].extend(invalid)
    quality["anomalous_lengths"] = anomalous
    quality["initial_fit_exclusions"] = [r["iri"] for r in anomalous]
    bounds = None
    if bounds_geometries:
        bounds = [min(g.bounds[0] for g in bounds_geometries), min(g.bounds[1] for g in bounds_geometries),
                  max(g.bounds[2] for g in bounds_geometries), max(g.bounds[3] for g in bounds_geometries)]
    return {"contract": "lzo-spatial-map/2", "crs": copy.deepcopy(CRS_POLICY), "features": located,
            "display_features": partition["display_features"], "unlocated": unlocated,
            "layers": [{"id": key, "label": label, "visible": key not in {"road", "canal"}} for key, label in LAYER_LABELS.items()],
            "bounds": bounds, "quality": quality}

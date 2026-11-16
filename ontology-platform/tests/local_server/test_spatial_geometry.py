"""Planar display keeps every original boundary and reports candidate evidence."""
import copy

import pytest

from local_server.spatial_geometry import build_spatial_map, partition_polygons


def polygon(ring, holes=()):
    return {"type": "Polygon", "coordinates": [ring, *holes]}


def feature(iri, geometry, kind="field", **attributes):
    return {"id": iri, "iri": iri, "class_iri": "urn:test:class:" + kind, "label": iri,
            "kind": kind, "geometry": geometry, "source_refs": [], "attributes": attributes,
            "position_status": "candidate_approximate", "nature": "cad_candidate", "layer_id": kind}


def test_duplicate_polygons_are_drawn_once_with_all_memberships():
    ring = [[114, 30], [114.001, 30], [114.001, 30.001], [114, 30.001], [114, 30]]
    features = [feature("urn:a", polygon(ring)), feature("urn:b", polygon(ring))]
    before = copy.deepcopy(features)
    result = partition_polygons(features)
    assert len(result["display_features"]) == 1
    assert result["display_features"][0]["object_iris"] == ["urn:a", "urn:b"]
    assert result["display_features"][0]["conflict"] is True
    assert features == before


def test_crossing_polygons_partition_without_overlap_and_keep_memberships():
    from shapely.geometry import shape
    a = polygon([[114, 30], [114.002, 30], [114.002, 30.002], [114, 30.002], [114, 30]])
    b = polygon([[114.001, 30.001], [114.003, 30.001], [114.003, 30.003], [114.001, 30.003], [114.001, 30.001]])
    result = partition_polygons([feature("urn:a", a), feature("urn:b", b)])
    faces = result["display_features"]
    assert {tuple(f["object_iris"]) for f in faces} == {("urn:a",), ("urn:b",), ("urn:a", "urn:b")}
    for i, first in enumerate(faces):
        for second in faces[i + 1:]:
            assert shape(first["geometry"]).intersection(shape(second["geometry"])).area < 1e-15
    assert result["quality"]["area_tolerance_m2"] == 1e-6


def test_hole_is_not_filled_and_invalid_polygon_is_quarantined_without_repair():
    from shapely.geometry import Point, shape
    shell = [[114, 30], [114.004, 30], [114.004, 30.004], [114, 30.004], [114, 30]]
    hole = [[114.001, 30.001], [114.003, 30.001], [114.003, 30.003], [114.001, 30.003], [114.001, 30.001]]
    bowtie = [[114, 30], [114.002, 30.002], [114, 30.002], [114.002, 30], [114, 30]]
    inputs = [feature("urn:hole", polygon(shell, [hole])), feature("urn:bad", polygon(bowtie))]
    result = partition_polygons(inputs)
    assert len(result["display_features"]) == 1
    assert not shape(result["display_features"][0]["geometry"]).covers(Point(114.002, 30.002))
    assert result["quality"]["invalid_geometry"][0]["iri"] == "urn:bad"
    assert inputs[1]["geometry"]["coordinates"][0] == bowtie


def test_bounds_include_facility_outside_fields_and_display_height_is_flat():
    objects = [feature("urn:field", polygon([[114, 30, 9], [114.001, 30, 9], [114.001, 30.001, 9], [114, 30, 9]])),
               feature("urn:anchor", {"type": "Point", "coordinates": [114.01, 30.02, 27.125]}, "facility"),
               feature("urn:missing", None, "facility")]
    result = build_spatial_map(objects)
    assert result["bounds"] == [114.0, 30.0, 114.01, 30.02]
    assert result["features"][1]["geometry"]["coordinates"] == [114.01, 30.02]
    assert result["features"][1]["attributes"]["original_geometry"]["coordinates"][2] == 27.125
    assert result["unlocated"][0]["iri"] == "urn:missing"
    assert objects[1]["geometry"]["coordinates"][2] == 27.125
    assert result["features"][0]["attributes"]["computed_measurements"]["area_m2"] > 0


def test_gross_line_anomaly_is_preserved_but_excluded_from_initial_fit():
    objects = [feature("urn:anchor", {"type": "Point", "coordinates": [114, 30]}, "facility"),
               feature("urn:road", {"type": "LineString", "coordinates": [[114, 30], [120, 31]]}, "road")]
    result = build_spatial_map(objects)
    assert result["bounds"] == [114.0, 30.0, 114.0, 30.0]
    assert result["features"][1]["attributes"]["exclude_from_initial_fit"] is True
    assert result["features"][1]["geometry"] == objects[1]["geometry"]
    assert {l["id"]: l["visible"] for l in result["layers"]}["road"] is False


def test_malformed_geometry_is_retained_in_quarantine_instead_of_aborting_map():
    malformed = {"type": "LineString", "coordinates": [[114, 30]]}
    result = build_spatial_map([feature("urn:malformed", malformed, "road")])
    assert result["features"] == []
    assert result["bounds"] is None
    assert result["unlocated"][0]["attributes"]["original_geometry"] == malformed
    assert result["unlocated"][0]["position_status"] == "invalid_geometry_quarantined"
    assert result["quality"]["invalid_geometry"][0]["iri"] == "urn:malformed"


def test_field_pond_overlap_is_visible_in_default_layers():
    geometry = polygon([[114, 30], [114.001, 30], [114.001, 30.001], [114, 30.001], [114, 30]])
    result = build_spatial_map([feature("urn:field", geometry), feature("urn:pond", geometry, "pond")])
    assert len(result["display_features"]) == 1
    face = result["display_features"][0]
    assert face["object_iris"] == ["urn:field", "urn:pond"]
    assert next(layer["visible"] for layer in result["layers"] if layer["id"] == face["layer_id"]) is True

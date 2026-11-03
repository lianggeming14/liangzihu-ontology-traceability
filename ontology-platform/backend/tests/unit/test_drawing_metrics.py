from decimal import Decimal
import pytest


def test_polygon_area_and_all_boundary_perimeters_include_holes():
    from lzo.gis.drawing_metrics import geometry_metrics
    geom={'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[2,2],[4,2],[4,4],[2,4],[2,2]]]}
    result=geometry_metrics(geom)
    assert result['area_pt2']==96 and result['outer_perimeter_pt']==40 and result['perimeter_pt']==48
    assert result['bbox_pt']==[0,0,10,10]


def test_elevation_is_never_parsed_as_depth():
    from lzo.gis.drawing_metrics import extract_quantities
    items=extract_quantities('生态渠I型-1（长341m、宽6m、渠底17.94m）')
    assert {(i['quantity_kind'],i['value_original']) for i in items}=={('length','341'),('width','6'),('bottom_elevation','17.94')}
    assert not any('depth' in i['quantity_kind'] for i in items)


def test_units_precision_and_project_dredging_thickness():
    from lzo.gis.drawing_metrics import quantity, mean_dredging_thickness
    q=quantity('0.1421','公顷','area')
    assert Decimal(q['si_value'])==Decimal('1421') and q['value_original']=='0.1421'
    assert quantity('4.93',None,'ledger_area')['si_value'] is None
    result=mean_dredging_thickness('86300.15','86300.15')
    assert result['value_m']=='1' and result['quantity_kind']=='project_mean_dredging_thickness'
    assert result['applies_to_individual_pond'] is False


def test_repeated_positions_do_not_become_one_water_depth():
    from lzo.gis.drawing_metrics import extract_quantities
    items=extract_quantities('2m宽环形沟-1（深0.8m）')
    assert any(q['quantity_kind']=='channel_depth' and q['value_original']=='0.8' for q in items)
    assert all(q['quantity_kind']!='water_depth' for q in items)


def test_perimeter_estimate_requires_documented_calibration_and_keeps_provenance():
    from lzo.gis.drawing_metrics import estimate_ground_metrics
    base={'perimeter_pt':40,'outer_perimeter_pt':40,'area_pt2':96}
    assert estimate_ground_metrics(base,None)['status']=='no_supported_scale'
    result=estimate_ground_metrics(base,{'method':'reference_length','metres_per_pt':0.7,'min_metres_per_pt':0.68,
        'max_metres_per_pt':0.72,'evidence_ids':['road-1','road-2'],'scope':'pdf-03','status':'conditional_estimate'})
    assert result['perimeter_m']==28 and result['perimeter_range_m']==[27.2,28.8]
    assert result['status']=='conditional_estimate' and result['evidence_ids']==['road-1','road-2']
    with pytest.raises(ValueError):estimate_ground_metrics(base,{'metres_per_pt':1,'evidence_ids':[]})


def test_hole_and_boundary_containment_are_distinguished():
    from lzo.gis.drawing_metrics import point_in_polygon
    rings=[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[2,2],[4,2],[4,4],[2,4],[2,2]]]
    assert point_in_polygon([1,1],rings) and not point_in_polygon([3,3],rings)


def test_range_and_dimension_tuple_are_not_negative_or_single_axis_measurements():
    from lzo.gis.drawing_metrics import extract_quantities
    items=extract_quantities('柳树地径（10-15cm）；沉沙池（1.5m*1.5m*3m）；渠底-2.5m')
    assert len(items)==3
    assert items[0]['value_original']==['10','15']
    assert items[1]['quantity_kind']=='dimension_tuple_unassigned_axes'
    assert items[1]['value_original']==['1.5','1.5','3']
    assert items[2]['quantity_kind']=='bottom_elevation' and items[2]['value_original']=='-2.5'


def test_count_expression_keeps_reported_formula_and_components():
    from lzo.gis.drawing_metrics import extract_quantities
    item=extract_quantities('灌木（1160*36）株')[0]
    assert item['quantity_kind']=='count_from_expression'
    assert item['value_original']=='41760'
    assert item['formula']=='1160*36' and item['unit_original']=='株'

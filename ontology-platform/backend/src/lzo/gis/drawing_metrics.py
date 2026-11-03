"""Document quantities and qualified paper metrics, never invented survey data."""
from decimal import Decimal, InvalidOperation
import math
import re

UNITS={'m':('m',Decimal(1)),'米':('m',Decimal(1)),'cm':('m',Decimal('.01')),'厘米':('m',Decimal('.01')),
       'mm':('m',Decimal('.001')),'毫米':('m',Decimal('.001')),'m²':('m2',Decimal(1)),
       '㎡':('m2',Decimal(1)),'m2':('m2',Decimal(1)),'平方米':('m2',Decimal(1)),
       '公顷':('m2',Decimal(10000)),'ha':('m2',Decimal(10000)),'亩':('m2',Decimal(2000)/3),
       'm³':('m3',Decimal(1)),'m3':('m3',Decimal(1)),'立方米':('m3',Decimal(1)),
       '座':('count',Decimal(1)),'个':('count',Decimal(1)),'套':('count',Decimal(1)),
       '处':('count',Decimal(1)),'株':('count',Decimal(1)),'棵':('count',Decimal(1)),
       '根':('count',Decimal(1)),'项':('count',Decimal(1)),'吨':('kg',Decimal(1000)),
       't':('kg',Decimal(1000)),'kW':('W',Decimal(1000)),'%':('ratio',Decimal('.01'))}
NUMBER=r'[-+]?\d+(?:\.\d+)?'
UNIT_PATTERN='|'.join(re.escape(k) for k in sorted(UNITS,key=len,reverse=True))
QUANTITY_PATTERN=re.compile(r'(?P<value>'+NUMBER+r')\s*(?P<unit>'+UNIT_PATTERN+r')(?![A-Za-z0-9²³])')


def decimal_string(value):
    result=format(Decimal(value),'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def quantity(value,unit,kind,**extra):
    original=str(value).strip()
    try:number=Decimal(original.replace(',',''))
    except InvalidOperation:raise ValueError('Quantity is not numeric') from None
    if not number.is_finite():raise ValueError('Nonfinite quantity')
    result={'quantity_kind':kind,'value_original':original,'value_decimal':str(number),'unit_original':unit,
            'si_value':None,'si_unit':None,'status':'document_reported_not_surveyed',**extra}
    if unit in UNITS:
        si,factor=UNITS[unit];result.update(si_unit=si,si_value=decimal_string((number*factor).quantize(Decimal('.000001'))))
    return result


def extract_quantities(text,*,subject_kind=None):
    """Only explicit number+unit pairs; unsupported bare figures stay untyped."""
    result=[];occupied=[]
    positive=r'\d+(?:\.\d+)?'
    count_expression=re.compile(r'(?P<a>'+positive+r')\s*[*×]\s*(?P<b>'+positive+r')\s*[）)]\s*(?P<unit>株|棵|个|座|套|根)')
    for match in count_expression.finditer(text):
        item=quantity(decimal_string(Decimal(match['a'])*Decimal(match['b'])),match['unit'],'count_from_expression',
            formula=match['a']+'*'+match['b'],text_original=match[0],text_span=[match.start(),match.end()],
            status='derived_from_source_count_expression_not_independent_count')
        result.append(item);occupied.append((match.start(),match.end()))
    # Process dimension tuples and ranges before scalar tokens. Otherwise the
    # hyphen in 10-15cm becomes a negative physical dimension, and a tuple's
    # last component looks like a standalone height/depth.
    tuple_pattern=re.compile(r'(?:'+positive+r'\s*(?:'+UNIT_PATTERN+r')?\s*[*×x]\s*)+'+positive+r'\s*(?P<unit>'+UNIT_PATTERN+r')(?![A-Za-z0-9²³])')
    range_pattern=re.compile(r'(?P<low>'+positive+r')\s*[-–—~～]\s*(?P<high>'+positive+r')\s*(?P<unit>'+UNIT_PATTERN+r')(?![A-Za-z0-9²³])')
    for pattern,kind in [(tuple_pattern,'dimension_tuple_unassigned_axes'),(range_pattern,'dimension_range')]:
        for match in pattern.finditer(text):
            if any(match.start()<b and match.end()>a for a,b in occupied):continue
            unit=match['unit']
            if kind=='dimension_range':values=[match['low'],match['high']]
            else:values=[re.match(positive,part.strip())[0] for part in re.split(r'[*×x]',match[0])]
            # A tuple with conflicting explicit units is kept in raw source
            # rather than silently assigning the final unit to all components.
            units=re.findall(UNIT_PATTERN,match[0])
            if any(u!=unit for u in units):continue
            result.append({'quantity_kind':kind,'value_original':values,'unit_original':unit,
                'si_value':None,'si_unit':None,'text_original':match[0],'text_span':[match.start(),match.end()],
                'status':'explicit_dimension_components_axes_or_range_semantics_require_context'})
            occupied.append((match.start(),match.end()))
    for match in QUANTITY_PATTERN.finditer(text):
        if any(match.start()<b and match.end()>a for a,b in occupied):continue
        value,unit=match['value'],match['unit'];prefix=text[max(0,match.start()-9):match.start()]
        suffix=text[match.end():match.end()+4]
        if re.search(r'(渠底|沟底|塘底|池底)(?:高程|标高)?\s*$',prefix):kind='bottom_elevation'
        elif re.search(r'(高程|标高|海拔)\s*$',prefix):kind='elevation'
        elif re.search(r'(水深)\s*$',prefix):kind='water_depth'
        elif re.search(r'(清淤厚度|清淤深度|淤泥厚度)\s*$',prefix):kind='dredging_thickness'
        elif re.search(r'(深|深度)\s*$',prefix) or suffix.startswith('深'):
            kind='channel_depth' if re.search(r'渠|沟',text) else 'depth_unspecified'
        elif re.search(r'(宽|宽度|净宽)\s*$',prefix) or suffix.startswith('宽'):kind='width'
        elif re.search(r'(长|长度|总长)\s*$',prefix) or suffix.startswith('长'):kind='length'
        elif re.search(r'(高|高度|净高)\s*$',prefix) or suffix.startswith('高'):kind='height'
        elif re.search(r'(厚|厚度)\s*$',prefix) or suffix.startswith('厚'):kind='thickness'
        elif re.search(r'(直径|管径|Φ|φ|∅)\s*$',prefix):kind='diameter'
        else:
            dimension=UNITS[unit][0]
            kind={'m2':'area','m3':'volume','count':'count','ratio':'ratio'}.get(dimension,'dimension_unspecified')
            if kind=='dimension_unspecified' and re.search(r'(路|渠|沟|管).*[-－]\s*\d+\s*[（(]\s*$',text[:match.start()]):kind='length'
        result.append(quantity(value,unit,kind,text_original=match[0],text_span=[match.start(),match.end()]))
    return sorted(result,key=lambda q:q['text_span'][0])


def geometry_metrics(geometry):
    kind=geometry['type'];coordinates=geometry['coordinates']
    rings=coordinates if kind=='Polygon' else [coordinates] if kind=='LineString' else [[coordinates]]
    points=[p for r in rings for p in r]
    if not points or any(len(p)!=2 or any(not math.isfinite(v) for v in p) for p in points):raise ValueError('Invalid geometry')
    lengths=[sum(math.dist(a,b) for a,b in zip(r,r[1:])) for r in rings]
    result={'bbox_pt':[min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)],
            'coordinate_units':'pt','method':'source_geometry_euclidean','area_pt2':None,'perimeter_pt':None,'outer_perimeter_pt':None,'length_pt':None}
    if kind=='Polygon':
        if any(len(r)<4 or r[0]!=r[-1] for r in rings):raise ValueError('Unclosed source ring')
        areas=[abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:])))/2 for r in rings]
        area=areas[0]-sum(areas[1:])
        if area<=0:raise ValueError('Nonpositive polygon area')
        result.update(area_pt2=round(area,6),perimeter_pt=round(sum(lengths),6),outer_perimeter_pt=round(lengths[0],6))
    elif kind=='LineString':result['length_pt']=round(lengths[0],6)
    return result


def estimate_ground_metrics(metrics,calibration):
    if calibration is None:return {'status':'no_supported_scale','perimeter_m':None,'area_m2':None,'length_m':None}
    scale=calibration.get('metres_per_pt')
    if not isinstance(scale,(int,float)) or not math.isfinite(scale) or scale<=0 or not calibration.get('evidence_ids'):
        raise ValueError('Positive scale and traceable calibration evidence required')
    low=calibration.get('min_metres_per_pt',scale);high=calibration.get('max_metres_per_pt',scale)
    if not 0<low<=scale<=high:raise ValueError('Invalid calibration interval')
    result={**calibration,'status':calibration.get('status','conditional_estimate'),'surveyed':False,'georeferenced':False,
            'perimeter_m':None,'area_m2':None,'length_m':None,
            'range_semantics':'calibration_reference_spread_not_statistical_confidence_interval'}
    for input_key,key,power in [('perimeter_pt','perimeter_m',1),('outer_perimeter_pt','outer_perimeter_m',1),('length_pt','length_m',1),('area_pt2','area_m2',2)]:
        if metrics.get(input_key) is not None:
            result[key]=round(metrics[input_key]*scale**power,3)
            result[key.replace('_m','_range_m')]=[round(metrics[input_key]*v**power,3) for v in (low,high)]
    return result


def mean_dredging_thickness(volume_m3,area_m2):
    volume,area=Decimal(volume_m3),Decimal(area_m2)
    if not volume.is_finite() or not area.is_finite() or volume<0 or area<=0:raise ValueError('Invalid project volume/area')
    return {'quantity_kind':'project_mean_dredging_thickness','value_m':decimal_string((volume/area).quantize(Decimal('.000001'))),
            'method':'project_dredging_volume_divided_by_project_dredging_area','applies_to_individual_pond':False,
            'status':'derived_from_document_totals_not_water_depth'}


def point_in_polygon(point,rings):
    def inside(ring):
        x,y=point;included=False
        for a,b in zip(ring,ring[1:]):
            if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:included=not included
        return included
    return bool(rings) and inside(rings[0]) and not any(inside(r) for r in rings[1:])

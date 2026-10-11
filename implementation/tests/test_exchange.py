import copy
import pytest
from agri.exchange import to_jsonld, from_jsonld, to_turtle
from agri.qr import make_svg


def test_qualified_exchange_preserves_evidence_time_and_unknowns():
    graph={'nodes':[{'id':'a','name':'田块','kind':'field'},{'id':'b','name':'批次','kind':'production_batch'}],
           'edges':[{'id':'edge1','source':'b','target':'a','predicate_id':'locatedIn','dimension':'space',
                     'valid_from':'2026-10-01T00:00:00Z','evidence_ids':['ev1'],'status':'candidate','qualifiers':{'depth':None}}],
           'truncated':True,'gaps':['source missing'],'snapshot_kind':'current'}
    exported=to_jsonld(graph)
    assert exported['@graph'][2]['source']=='urn:agri:node:b'
    assert exported['@graph'][2]['target']=='urn:agri:node:a'
    assert from_jsonld(exported)==graph
    altered=copy.deepcopy(exported);altered['@graph'][2]['source']='urn:agri:node:a'
    with pytest.raises(ValueError,match='endpoint'):from_jsonld(altered)
    assert 'rdf:JSON' in to_turtle(graph)


def test_dangling_edges_and_unknown_profiles_rejected():
    with pytest.raises(ValueError,match='missing node'):
        to_jsonld({'nodes':[{'id':'a'}],'edges':[{'id':'e','source':'a','target':'missing'}]})
    with pytest.raises(ValueError,match='frozen'):
        from_jsonld({'profile':'unknown','@context':{}})


def test_qr_has_quiet_zone_and_no_embedded_user_markup():
    import xml.etree.ElementTree as ET
    image=ET.fromstring(make_svg('https://example.org/trace/abc-def'))
    assert image.attrib['viewBox'].startswith('0 0 ')
    assert image.find('{http://www.w3.org/2000/svg}path') is not None
    assert '<script' not in make_svg('https://example.org/trace/<script>')

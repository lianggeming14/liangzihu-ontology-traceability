"""Carrier recognition does not imply decoding, analysis or evidence truth."""
from agri.asset_inspection import inspect_asset


def test_container_brand_is_not_assumed_to_be_mp4():
    for brand,mime in [(b'avif','image/avif'),(b'heic','image/heic'),(b'zzzz','application/octet-stream')]:
        result=inspect_asset(b'\x00\x00\x00\x18ftyp'+brand+b'0'*20,'video')
        assert result['detected_media_type']==mime
        assert result['classification_status']=='needs_mapping'
        assert result['decode_status']=='not_checked'
        assert result['content_analysis']=='not_performed'


def test_truncated_image_and_malformed_json_remain_unverified():
    result=inspect_asset(b'\x89PNG\r\n\x1a\n' + b'broken','image')
    assert result['format_status']=='invalid'
    assert inspect_asset(b'{"v":NaN}','document')['format_status']=='unknown'
    assert inspect_asset(b'{"v":1','document')['format_status']=='unknown'
    assert inspect_asset(b'{"v":1}','document')['detected_media_type']=='application/json'


def test_declared_media_type_does_not_override_bytes():
    result=inspect_asset(b'%PDF-1.7 synthetic header','image','image/png')
    assert result['detected_media_type']=='application/pdf'
    assert result['classification_status']=='needs_mapping'
    assert result['content_analysis']=='not_performed'


def test_remote_sensing_source_can_contain_image_carrier():
    result=inspect_asset(b'\x00\x00\x00\x18ftypavif'+b'0'*20,'remote_sensing')
    assert result['classification_status']=='classified'
    assert result['detected_media_type']=='image/avif'


def test_malformed_metadata_and_legacy_decode_failure_are_not_usable(tmp_path):
    from agri.field_service import FieldService
    service=FieldService(None,asset_root=tmp_path)
    evidence={'status':'active','kind':'image','uri':'asset://invalid','metadata':{'asset_key':[],'carrier':[],'processing':[]}}
    assert service._availability('tenant',evidence)=='invalid_asset_reference'
    checks=service._evidence_checks('tenant',evidence)
    assert checks['carrier_status']=='invalid_metadata'
    assert checks['external_processing_status']=='invalid_metadata'
    evidence['metadata']={'processing':{'status':'failed','reason':'invalid_or_unsupported_media'}}
    assert service._evidence_checks('tenant',evidence)['carrier_status']=='legacy_unvalidated'

    evidence['metadata']={'receipt_format':[]}
    evidence['uri']='urn:test'
    assert service._availability('tenant',evidence)=='invalid_metadata'
    evidence['metadata']={'carrier':{'format_status':[]},'processing':{'status':[]}}
    checks=service._evidence_checks('tenant',evidence)
    assert checks['carrier_status']=='invalid_metadata'
    assert checks['external_processing_status']=='invalid_metadata'

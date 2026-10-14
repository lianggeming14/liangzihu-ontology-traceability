"""Bounded carrier inspection only: no image interpretation or video decoding."""
from io import BytesIO
import json
import warnings

MAX_PIXELS=24_000_000


def inspect_asset(content, declared_kind, declared_media_type='application/octet-stream'):
    result={'inspector':'carrier-inspection/1','declared_kind':declared_kind,
            'declared_media_type':declared_media_type,'detected_media_type':'application/octet-stream',
            'format_status':'unknown','content_analysis':'not_performed'}
    raw=content[:512]
    image_type=None
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): image_type='image/png'
    elif raw.startswith(b'\xff\xd8\xff'): image_type='image/jpeg'
    elif raw.startswith((b'GIF87a',b'GIF89a')): image_type='image/gif'
    elif raw.startswith((b'II*\x00',b'MM\x00*')): image_type='image/tiff'
    elif raw.startswith(b'BM'): image_type='image/bmp'
    elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP':image_type='image/webp'
    if image_type:
        result['detected_media_type']=image_type
        try:
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as img:
                    width,height=img.size
                    if width<=0 or height<=0 or width*height>MAX_PIXELS:raise ValueError('pixel_budget')
                    img.verify()
                result.update(format_status='verified_structure',width=width,height=height)
        except Exception:
            result.update(format_status='invalid',reason='image_structure_invalid_or_over_budget')
    elif len(raw)>=12 and raw[4:8]==b'ftyp':
        brand=raw[8:12]
        detected='video/mp4' if brand in {b'isom',b'iso2',b'mp41',b'mp42',b'avc1',b'dash',b'M4V '} else 'image/avif' if brand in {b'avif',b'avis'} else 'image/heic' if brand in {b'heic',b'heix',b'hevc',b'hevx',b'mif1'} else 'application/octet-stream'
        result.update(detected_media_type=detected,format_status='recognized_header',decode_status='not_checked',container_hint='iso-bmff')
    elif raw.startswith(b'\x1a\x45\xdf\xa3'):
        result.update(detected_media_type='video/x-matroska',format_status='recognized_header',decode_status='not_checked',container_note='EBML container; exact codec and Matroska/WebM subtype unverified')
    elif raw.startswith(b'RIFF') and raw[8:12]==b'AVI ':
        result.update(detected_media_type='video/x-msvideo',format_status='recognized_header',decode_status='not_checked')
    elif raw.startswith(b'%PDF-'):
        result.update(detected_media_type='application/pdf',format_status='recognized_header',content_analysis='not_performed')
    elif len(content)<=2*1024*1024:
        try:
            text=content.decode('utf-8-sig')
            if text.lstrip().startswith(('{','[')):
                json.loads(text,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non_finite')))
                result.update(detected_media_type='application/json',format_status='verified_structure')
            elif '\x00' not in text:
                result.update(detected_media_type='text/plain',format_status='recognized_text')
        except (ValueError,UnicodeError):pass
    actual=result['detected_media_type']
    expected_prefix={'image':'image/','video':'video/'}.get(declared_kind)
    declared_conflict=bool(expected_prefix and not actual.startswith(expected_prefix))
    result['classification_status']='needs_mapping' if declared_conflict else 'classified' if actual!='application/octet-stream' else 'unknown'
    if declared_conflict:result['classification_issue']='declared_kind_does_not_match_detected_carrier'
    return result

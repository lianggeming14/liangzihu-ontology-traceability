"""Bounded local media inspection; outputs are technical signals, not farm facts.
Reference: https://pillow.readthedocs.io/en/stable/reference/Image.html
Video CLI: https://ffmpeg.org/ffmpeg.html ; optional operator-provided FFMPEG_BIN.
"""
from pathlib import Path
from io import BytesIO
import hashlib
import os
import subprocess
import tempfile
import warnings

PROCESSOR = 'local-media-inspector/1'
MAX_PIXELS = 24_000_000


def _image(content, folder):
    from PIL import Image, ImageOps, ImageStat
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as original:
            if original.format not in {'JPEG','PNG','WEBP','BMP','TIFF'}:
                raise ValueError('Unsupported image container')
            width, height = original.size
            if width * height > MAX_PIXELS or width <= 0 or height <= 0:
                raise ValueError('Image exceeds pixel budget')
            original.load()
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((960,720))
    gray = image.convert('L')
    stats = ImageStat.Stat(gray)
    mean, contrast = round(stats.mean[0],2), round(stats.stddev[0],2)
    tiny = gray.resize((9,8))
    pixels = list(tiny.getdata())
    bits = ''.join('1' if pixels[y*9+x] > pixels[y*9+x+1] else '0' for y in range(8) for x in range(8))
    output = BytesIO(); image.save(output, format='JPEG', quality=82)
    preview = output.getvalue(); digest = hashlib.sha256(preview).hexdigest()
    target = folder / digest
    try:
        with target.open('xb') as stream: stream.write(preview)
    except FileExistsError:
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Derived preview integrity mismatch')
    return {'width':width,'height':height,'brightness':mean,'contrast':contrast,
            'visual_hash':format(int(bits,2),'016x'),'preview_hash':digest,
            'flags':(['dark_frame'] if mean < 25 else []) + (['low_contrast'] if contrast < 8 else [])}


def inspect_media(path, kind, derived_root, interval_seconds=10, max_frames=12):
    base = {'processor':PROCESSOR,'agricultural_inference':False}
    if kind not in {'image','video'}: return dict(base,status='not_applicable')
    folder = Path(derived_root); folder.mkdir(parents=True,exist_ok=True)
    try:
        if kind == 'image':
            result = _image(Path(path).read_bytes(),folder)
            return dict(base,status='processed',summary=result,frames=[dict(result,target_offset_seconds=0)])
        executable = os.environ.get('FFMPEG_BIN','')
        if not executable or not Path(executable).is_file():
            return dict(base,status='unavailable',reason='ffmpeg_not_configured',summary={'message':'视频原件已保留；配置FFMPEG_BIN后可重新上传进行抽帧'})
        # No network input or arbitrary playlist demuxer; fixed-size output and wall timeout.
        with tempfile.TemporaryDirectory(prefix='media-',dir=folder) as tmp:
            pattern = str(Path(tmp) / 'frame-%03d.jpg')
            args = [executable,'-nostdin','-loglevel','error','-threads','1',
                '-protocol_whitelist','file,pipe','-format_whitelist','mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi',
                '-i',str(Path(path).resolve()),'-an','-sn','-dn','-t',str(interval_seconds*max_frames),
                '-vf',f'fps=1/{interval_seconds}:start_time=0,scale=640:360:force_original_aspect_ratio=decrease',
                '-frames:v',str(max_frames),'-threads','1',pattern]
            subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           timeout=25,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
            frames = []
            for index, frame in enumerate(sorted(Path(tmp).glob('frame-*.jpg'))[:max_frames]):
                item = _image(frame.read_bytes(),folder)
                item['target_offset_seconds'] = index * interval_seconds
                frames.append(item)
            if not frames: raise ValueError('No decodable frames')
            return dict(base,status='processed',frames=frames,summary={
                'sample_interval_seconds':interval_seconds,'frame_count':len(frames),
                'max_sampled_seconds':interval_seconds*max_frames,
                'timestamps':'requested_relative_sampling_positions; not device capture times',
                'coverage':'bounded_prefix; not complete recording analysis'})
    except ImportError:
        return dict(base,status='unavailable',reason='pillow_not_installed')
    except subprocess.TimeoutExpired:
        return dict(base,status='failed',reason='processing_timeout')
    except Exception:
        return dict(base,status='failed',reason='invalid_or_unsupported_media')

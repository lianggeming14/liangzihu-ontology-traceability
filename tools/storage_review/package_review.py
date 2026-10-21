"""Verify the reviewed screenshots and package only this documentation delivery."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from build_github_snapshot import zip_bytes, groups_for, stable_read
from restore_github_snapshot import (
    checked_path, forbidden_reason, scan_secrets, digest, FORMAT, ARCHIVE_LIMIT,
    FILE_LIMIT, TOTAL_LIMIT, FILE_COUNT_LIMIT, load_verified,
)

FOLDER = ROOT / '交付文档' / '数据库结构源码图解_20261021'
SCOPE = ['tools/storage_review', FOLDER.relative_to(ROOT).as_posix()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visual-review-complete', action='store_true',
                        help='Use only after a person or agent inspected all 13 images.')
    parser.add_argument('--baseline-commit', required=True)
    args = parser.parse_args()
    sources = json.loads((FOLDER / 'sources.json').read_text(encoding='utf-8'))
    verification_path = FOLDER / 'verification.json'
    verification = json.loads(verification_path.read_text(encoding='utf-8'))
    if verification['passed'] != len(sources['items']) or verification['failed']:
        raise RuntimeError('Incomplete screenshot verification')
    for item, check in zip(sources['items'], verification['checks'], strict=True):
        if item['id'] != check['id'] or check['status'] != 'passed':
            raise RuntimeError('Mismatched screenshot check')
        if digest((ROOT / item['path']).read_bytes()) != item['source_sha256']:
            raise RuntimeError('Source changed: ' + item['path'])
        excerpt = (FOLDER / 'excerpts' / (item['id'] + '.txt')).read_bytes()
        if digest(excerpt) != item['excerpt_sha256']:
            raise RuntimeError('Excerpt changed: ' + item['id'])
        if digest((FOLDER / item['screenshot']).read_bytes()) != check['screenshot_sha256']:
            raise RuntimeError('Screenshot changed: ' + item['id'])
    if args.visual_review_complete:
        verification['visual_review'] = 'passed'
        verification['visually_reviewed_images'] = ['00-report-overview'] + [i['id'] for i in sources['items']]
        verification['visual_review_notes'] = 'All 12 code images and report overview inspected: legible text, retained line numbers, no clipping or overlap.'
        verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if verification['visual_review'] != 'passed':
        raise RuntimeError('Visual review remains pending')
    paths = []
    for scope in SCOPE:
        paths.extend(p for p in (ROOT / scope).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    payloads = []
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        checked_path(name)
        if forbidden_reason(name):
            raise RuntimeError('Prohibited path: ' + name)
        data, _ = stable_read(ROOT, name)
        scan_secrets(data, name)
        payloads.append((name, data))
    git = 'C:/Users/robot/.conda/envs/direct/Library/bin/git.exe'
    check = subprocess.run([git, '-c', 'safe.directory=' + ROOT.as_posix(), 'check-ignore', '--stdin'],
                           input='\n'.join(n for n, _ in payloads) + '\n',
                           text=True, encoding='utf-8', capture_output=True, cwd=ROOT)
    if check.returncode not in (0, 1) or check.stdout.strip():
        raise RuntimeError('Ignore rule verification failed: ' + check.stdout + check.stderr)
    # Portable reader package contains the whole report directory, no live data.
    report_payload = [(str(Path(n).relative_to(FOLDER.parent.relative_to(ROOT))).replace('\\', '/'), d)
                      for n, d in payloads if n.startswith(SCOPE[1] + '/')]
    package_path = FOLDER.with_suffix('.zip')
    package_path.write_bytes(zip_bytes(report_payload))
    package_name = package_path.relative_to(ROOT).as_posix()
    scan_secrets(package_path.read_bytes(), package_name)
    payloads.append((package_name, package_path.read_bytes()))
    if len(payloads) > FILE_COUNT_LIMIT or sum(len(d) for _, d in payloads) > TOTAL_LIMIT:
        raise RuntimeError('Snapshot budget exceeded')
    output = ROOT / '.github-upload' / 'storage-review'
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
        'source': {'selection_mode': 'reviewed-incremental', 'scope': SCOPE + [package_name],
                   'baseline_commit': args.baseline_commit},
        'limits': {'archive_bytes': ARCHIVE_LIMIT, 'file_bytes': FILE_LIMIT,
                   'total_bytes': TOTAL_LIMIT, 'file_count': FILE_COUNT_LIMIT},
        'archives': [], 'files': [],
        'excluded': ['live-database', 'source-imports', 'raw-assets', 'credentials', 'dependencies'],
    }
    for index, group in enumerate(groups_for(payloads), 301):
        name = f'snapshot-{index:03d}.zip'
        packed = zip_bytes(group)
        (output / name).write_bytes(packed)
        manifest['archives'].append({'name': name, 'size': len(packed), 'sha256': digest(packed),
                                    'file_count': len(group), 'uncompressed_size': sum(len(d) for _, d in group)})
        manifest['files'].extend({'path': n, 'archive': name, 'size': len(d), 'sha256': digest(d)} for n, d in group)
    manifest_path = output / 'snapshot-manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _, verified = load_verified(manifest_path)
    print(json.dumps({'status': 'verified', 'files': len(verified), 'report_zip': str(package_path),
                      'archives': manifest['archives'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

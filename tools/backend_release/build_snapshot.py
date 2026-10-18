"""Package only reviewed v0.4 deliverables for the existing manual GitHub importer.

This does not modify Git metadata, publish files, or read private runtime data.
The importer checks every archive and member hash before restoring any file.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from build_github_snapshot import zip_bytes, groups_for, stable_read
from restore_github_snapshot import (
    checked_path, forbidden_reason, scan_secrets, digest, FORMAT, ARCHIVE_LIMIT,
    FILE_LIMIT, TOTAL_LIMIT, FILE_COUNT_LIMIT, load_verified,
)

FILES = [
    '.gitignore', 'README.md',
    'implementation/agri/app.py', 'implementation/agri/openapi.py',
    'implementation/agri/service.py', 'implementation/agri/network.py',
    'implementation/agri/source_mapping.py',
    'implementation/contracts/openapi.json',
    'implementation/contracts/source-mapping-schemas.json',
    'implementation/migrations/005_source_mapping.sql',
    'implementation/migrations/005_source_mapping.sqlite.sql',
    'implementation/tests/test_source_mapping.py',
    'implementation/tests/test_liangzihu_adapter.py',
    'implementation/tests/test_integration_api.py',
    'implementation/tests/test_network.py',
    'implementation/web/app.js', 'implementation/ops/import_liangzihu.py',
    'implementation/IMPLEMENTATION_STATUS.json',
    'implementation/database-gate.json', 'implementation/README.txt',
    'implementation/验证结果.txt', 'implementation/runtime/api-contract-check.json',
    '交付文档/梁子湖本体数据库后端操作说明书_v0.4.docx',
    '交付文档/原梁子湖项目数据库分析与本体库比较报告.docx',
    'tools/ontology_export/build_source_profile.py',
]
FOLDERS = [
    'implementation/integrations/liangzihu', 'tools/backend_release',
    'outputs/backend-integration-20261019',
]


def main():
    paths = list(FILES)
    for folder in FOLDERS:
        for base, dirs, files in os.walk(ROOT / folder, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'__pycache__', '.pytest_cache', 'node_modules'}]
            for name in files:
                paths.append((Path(base) / name).relative_to(ROOT).as_posix())
    names = sorted(set(paths))
    git = Path('C:/Users/robot/.conda/envs/direct/Library/bin/git.exe')
    result = subprocess.run(
        [str(git), '-c', 'safe.directory=' + ROOT.as_posix(), 'check-ignore', '--stdin'],
        input='\n'.join(names) + '\n', text=True, encoding='utf-8',
        capture_output=True, cwd=ROOT,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError('Could not verify ignore rules: ' + result.stderr)
    if result.stdout.strip():
        raise RuntimeError('Reviewed selection includes ignored files: ' + result.stdout)
    payloads = []
    for name in names:
        checked_path(name)
        reason = forbidden_reason(name)
        if reason:
            raise RuntimeError(name + ': ' + reason)
        data, _ = stable_read(ROOT, name)
        if len(data) > FILE_LIMIT:
            raise RuntimeError('File exceeds budget: ' + name)
        scan_secrets(data, name)
        payloads.append((name, data))
    if len(payloads) > FILE_COUNT_LIMIT or sum(len(d) for _, d in payloads) > TOTAL_LIMIT:
        raise RuntimeError('Snapshot budget exceeded')
    output = ROOT / '.github-upload/backend-v04'
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
        'source': {'selection_mode': 'reviewed-incremental', 'scope': FILES + FOLDERS,
                   'baseline_commit': 'b27f730f271e8fa8f84bc7c53e30aaa1d9b911cf'},
        'limits': {'archive_bytes': ARCHIVE_LIMIT, 'file_bytes': FILE_LIMIT,
                   'total_bytes': TOTAL_LIMIT, 'file_count': FILE_COUNT_LIMIT},
        'archives': [], 'files': [],
        'excluded': ['live-database', 'database-backup', 'source-imports', 'raw-assets',
                     'source-cache', 'credentials', 'dependencies', 'private-runtime-logs'],
    }
    for index, group in enumerate(groups_for(payloads), 201):
        name = f'snapshot-{index:03d}.zip'
        packed = zip_bytes(group)
        (output / name).write_bytes(packed)
        manifest['archives'].append({'name': name, 'size': len(packed), 'sha256': digest(packed),
            'file_count': len(group), 'uncompressed_size': sum(len(d) for _, d in group)})
        manifest['files'].extend({'path': p, 'archive': name, 'size': len(d), 'sha256': digest(d)} for p, d in group)
    path = output / 'snapshot-manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _, verified = load_verified(path)
    print(json.dumps({'status': 'verified', 'files': len(verified), 'archives': manifest['archives'],
                      'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

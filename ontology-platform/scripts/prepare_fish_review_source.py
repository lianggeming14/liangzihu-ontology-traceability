"""Verify a downloaded pinned ZIP and prepare private sample input; stdlib only.

Save the original source ZIP as the config's source_archive first. This command
does not download files, run the generator, connect to DBs, or replace mismatches.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

from fish_review_config import DEFAULT_CONFIG, ROOT, load_config

PINNED_SHA = '04891aab2039607015d41575e292a0add57065af3a2037270893cc0f3cd7c4b7'
PINNED_BLOB = '85e513fdb8e388b251a990608436b2de24020993'


def safe_member(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
            or ':' in name or path.as_posix() != name or path.parts[0] != 'output'):
        raise ValueError('Unsafe archive member path')
    return path


def prepare_source(config):
    private = (ROOT / '.runtime').resolve()
    for path in (config.source_archive, config.source_manifest, config.extracted_root):
        if not path.is_relative_to(private):
            raise ValueError('Source preparation writes only beneath this checkout .runtime')
    if config.extracted_root.name != 'output':
        raise ValueError('extracted_root must identify the archive output directory')
    reviewed = (ROOT / 'datasets/fish/source-manifest.json').read_bytes()
    manifest = json.loads(reviewed)
    if manifest['archive_sha256'] != PINNED_SHA or manifest['archive_git_blob'] != PINNED_BLOB:
        raise ValueError('Checked-in source manifest differs from the pinned archive')
    archive = config.source_archive.read_bytes()
    if (len(archive) != manifest['archive_bytes']
            or hashlib.sha256(archive).hexdigest() != PINNED_SHA
            or hashlib.sha1(b'blob ' + str(len(archive)).encode() + b'\0' + archive).hexdigest() != PINNED_BLOB):
        raise ValueError('Downloaded source archive does not match the pinned SHA256/Git blob/size')
    members = {}
    for member in manifest['members']:
        name = str(safe_member(member['path']))
        if name in members:
            raise ValueError('Duplicate manifest member')
        members[name] = member
    destination = config.extracted_root.parent
    if config.source_manifest.exists() and json.loads(config.source_manifest.read_text(encoding='utf-8-sig')) != manifest:
        raise ValueError('Existing source manifest differs; refusing overwrite')
    # Verify every archived member before creating directories or files. Do not
    # use ZipFile.extractall: canonical paths and file types are checked here.
    with zipfile.ZipFile(config.source_archive) as package:
        files = {}
        for info in package.infolist():
            if info.is_dir():
                safe_member(info.filename.rstrip('/'))
                continue
            name = str(safe_member(info.filename))
            if name in files or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Duplicate or symlink archive entry')
            files[name] = info
        if files.keys() != members.keys():
            raise ValueError('Archive member inventory differs from the reviewed manifest')
        for name, info in files.items():
            expected = members[name]
            data = package.read(info)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError('Archive member hash mismatch')
        existing = destination.exists() and any(destination.iterdir())
        if existing:
            actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
            if actual != members.keys():
                raise ValueError('Existing extraction inventory differs; refusing overwrite')
            for name, expected in members.items():
                path = destination.joinpath(*safe_member(name).parts)
                if not path.resolve().is_relative_to(destination.resolve()) or path.is_symlink():
                    raise ValueError('Existing extraction contains an unsafe path')
                data = path.read_bytes()
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise ValueError('Existing extraction differs; refusing overwrite')
        else:
            destination.mkdir(parents=True, exist_ok=True)
            for name, info in files.items():
                path = destination.joinpath(*safe_member(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive writes also reject any concurrent conflicting input.
                with path.open('xb') as stream:
                    stream.write(package.read(info))
    if not config.source_manifest.exists():
        with config.source_manifest.open('xb') as stream:
            stream.write(reviewed)
    return {'contract':'fish-review-source-preparation/1','status':'verified_existing' if existing else 'prepared',
        'package_sha256':PINNED_SHA,'verified_members':len(members),'generator_executed':False,
        'database_accessed':False,'formal_adoption':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    print(json.dumps(prepare_source(load_config(args.config)), indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Fish review source preparation failed: ' + str(error)) from None

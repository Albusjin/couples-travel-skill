#!/usr/bin/env python3
"""Build a small, deterministic distribution from an explicit reviewed allowlist."""

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"[?&](?:key|token|api_key)=[A-Za-z0-9_%+-]{24,}", re.I),
    re.compile(r"Bearer [A-Za-z0-9_.-]{32,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"/Users/(?!example/|YOUR_USER/)[A-Za-z0-9_.-]+/"),
)


def checked_file(skill, relative):
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts or "\\" in relative
            or path.as_posix() != relative or relative == "MANIFEST.json"):
        raise ValueError("invalid release path: " + relative)
    if any(part.startswith('.') or part in {'__pycache__', 'node_modules', 'private', 'travel-data'}
           or ('.local.' in part and part != 'runtime.local.example.toml')
           or part.endswith(('.pyc', '.zip')) for part in path.parts):
        raise ValueError("private/generated path refused: " + relative)
    candidate = skill
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("symlink refused: " + relative)
    if not candidate.is_file() or candidate.stat().st_size > MAX_FILE:
        raise ValueError("missing or oversized release file: " + relative)
    data = candidate.read_bytes()
    content = data.decode('utf-8')
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise ValueError("possible credential or publisher path: " + relative)
    return data


def build(root=ROOT):
    spec = json.loads((root / 'release-files.json').read_text(encoding='utf-8'))
    version = spec['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('invalid version')
    files = spec['files']
    if not isinstance(files, list) or len(files) != len(set(files)) or not files:
        raise ValueError('release allowlist must be nonempty and unique')
    skill = root / 'skills/travel-planner'
    contents = {name: checked_file(skill, name) for name in sorted(files)}
    if contents.get('VERSION', b'').decode().strip() != version:
        raise ValueError('package VERSION and allowlist version differ')
    if sum(map(len, contents.values())) > MAX_TOTAL:
        raise ValueError('release exceeds lightweight package budget')
    manifest = {'package_version': version, 'schema_version': '1.0',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    contents['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo('travel-planner/' + name, date_time=(2026, 11, 2, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return version, buffer.getvalue(), len(contents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'releases')
    args = parser.parse_args()
    version, data, count = build()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = 'travel-planner-universal-' + version + '.zip'
    destination = args.output_dir / name
    destination.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (args.output_dir / 'SHA256SUMS').write_text(digest + '  ' + name + '\n', encoding='utf-8')
    print(json.dumps({'zip': str(destination), 'files': count, 'bytes': len(data), 'sha256': digest}))


if __name__ == '__main__':
    main()

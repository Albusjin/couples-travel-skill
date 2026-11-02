#!/usr/bin/env python3
"""Verify a fresh extracted release without dependencies or network access."""

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


def verify(root):
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    failures = []
    files = manifest['files']
    if not isinstance(files, dict) or not files:
        raise ValueError('invalid file manifest')
    for name, expected in files.items():
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name or parts.as_posix() != name:
            raise ValueError('invalid manifest path')
        path = root
        symlink = False
        for part in parts.parts:
            path = path / part
            symlink |= path.is_symlink()
        if symlink or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name)
    return {'ok': not failures, 'package_version': manifest['package_version'],
            'checked_files': len(files), 'failed_files': failures,
            'note': 'Checks listed files only; not a signature, environment check or business verification.'}


def main():
    try:
        result = verify(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, KeyError, TypeError):
        result = {'ok': False, 'error': 'Missing/invalid MANIFEST.json; use a fresh extracted release ZIP.'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())

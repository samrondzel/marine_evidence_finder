"""Reject tracked local data/secret paths before pushing or in CI.

This is a path guard, NOT a content secret scanner or a Git history audit.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import subprocess
import sys


def forbidden_path(path: str) -> bool:
    p = PurePosixPath(path)
    parts = tuple(part.lower() for part in p.parts)
    if not parts:
        return False
    name = parts[-1]
    return (parts[0] in {'papers', 'data', '.venv'}
            or (name.startswith('.env') and name != '.env.example')
            or name.endswith(('.pdf', '.zip', '.pem', '.key', '.pfx', '.p12')))


def main() -> int:
    result = subprocess.run(['git', 'ls-files', '-z'], check=True, stdout=subprocess.PIPE)
    paths = [p.decode('utf-8', errors='replace') for p in result.stdout.split(b'\0') if p]
    forbidden = [p for p in paths if forbidden_path(p)]
    if forbidden:
        print('STOP: review these tracked paths before pushing (names only):', file=sys.stderr)
        for path in forbidden:
            print(repr(path), file=sys.stderr)
        print('Ignoring files does not untrack them or remove prior commits. Review history separately.', file=sys.stderr)
        return 1
    print('PASS: no forbidden tracked paths. This does not scan secrets in file contents or history.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

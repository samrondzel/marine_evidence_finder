"""Publish only the three smoke-tested CI images, then record registry digests."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROLES = ('runtime', 'ui', 'migrations')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')


def release_identity(env: dict[str, str]) -> tuple[str, str, str]:
    if (env.get('GITHUB_ACTIONS') != 'true'
            or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_EVENT_NAME') not in {'push', 'workflow_dispatch'}):
        raise ValueError('Publishing is restricted to main on a GitHub-hosted runner.')
    repo = env.get('GITHUB_REPOSITORY', '').lower()
    sha = env.get('GITHUB_SHA', '')
    run, attempt = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_RUN_ATTEMPT', '')
    if (not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repo)
            or not SHA.fullmatch(sha) or not run.isdecimal() or not attempt.isdecimal()):
        raise ValueError('Invalid release identity.')
    return f'ghcr.io/{repo}', sha, f'sha-{sha}-r{run}-a{attempt}'


def read_ids(path: Path) -> dict[str, str]:
    ids = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        role, image_id = line.split()
        if role not in ROLES or role in ids or not DIGEST.fullmatch(image_id):
            raise ValueError('Invalid tested-image inventory.')
        ids[role] = image_id
    if set(ids) != set(ROLES):
        raise ValueError('Incomplete tested-image inventory.')
    return ids


def docker(*args: str, input_text: str | None = None) -> str:
    result = subprocess.run(['docker', *args], input=input_text, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        # Do not surface login output or credentials on failure.
        if args[0] != 'login':
            print(result.stderr[-4000:])
        raise RuntimeError(f'docker {args[0]} failed ({result.returncode})')
    return result.stdout


def inspect_image(role: str, expected_id: str, sha: str, source: str) -> None:
    info = json.loads(docker('image', 'inspect', f'marine-ci-{role}:tested'))[0]
    labels = info['Config'].get('Labels') or {}
    if (info['Id'] != expected_id or info['Os'] != 'linux' or info['Architecture'] != 'amd64'
            or labels.get('org.opencontainers.image.revision') != sha
            or labels.get('org.opencontainers.image.source') != source):
        raise ValueError(f'Tested image identity mismatch: {role}')


def push_digest(output: str) -> str:
    matches = re.findall(r'\bdigest: (sha256:[0-9a-f]{64})\b', output)
    if len(matches) != 1:
        raise ValueError('Could not identify exactly one registry manifest digest.')
    return matches[0]


def publish(bundle: Path, output: Path) -> dict:
    prefix, sha, tag = release_identity(dict(os.environ))
    source = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
    token = os.environ.pop('GHCR_TOKEN', '')
    if not token:
        raise ValueError('GHCR_TOKEN is required.')
    ids = read_ids(bundle / 'image-ids.txt')
    # The workflow verifies SHA256SUMS before invoking this script.
    docker('image', 'load', '-i', str(bundle / 'images.tar.gz'))
    for role in ROLES:
        inspect_image(role, ids[role], sha, source)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'commit': sha, 'tag': tag, 'platform': 'linux/amd64', 'images': {}}
    docker('login', 'ghcr.io', '-u', os.environ['GITHUB_ACTOR'], '--password-stdin', input_text=token + '\n')
    try:
        for role in ROLES:
            name = f'{prefix}-{role}'
            ref = f'{name}:{tag}'
            docker('image', 'tag', f'marine-ci-{role}:tested', ref)
            digest = push_digest(docker('image', 'push', ref))
            manifest['images'][role] = {'tag': ref, 'digest': digest,
                                        'ref': f'{name}@{digest}', 'image_id': ids[role]}
            print(f'Published {ref} -> {digest}')
    finally:
        docker('logout', 'ghcr.io')
    # No complete release manifest is emitted until all three pushes succeed.
    (output / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (output / 'release.env').write_text(''.join(
        f'MARINE_{role.upper()}_IMAGE={manifest["images"][role]["ref"]}\n' for role in ROLES), encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as f:
            f.write(f'## GHCR release\n\nCommit: `{sha}`\n\n')
            for role in ROLES:
                f.write(f'- `{manifest["images"][role]["ref"]}`\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    publish(args.bundle, args.output)

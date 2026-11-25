from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import publish_tested_images as release

SHA = 'a' * 40
ID = 'sha256:' + 'b' * 64
REGISTRY_DIGEST = 'sha256:' + 'c' * 64
ENV = {
    'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
    'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'push',
    'GITHUB_REPOSITORY': 'Example/Marine', 'GITHUB_SHA': SHA,
    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
    'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_ACTOR': 'example',
    'GHCR_TOKEN': 'test-only',
}


def test_release_identity():
    assert release.release_identity(ENV) == ('ghcr.io/example/marine', SHA, f'sha-{SHA}-r123-a2')


@pytest.mark.parametrize('key,value', [
    ('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
    ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_EVENT_NAME', 'pull_request'),
    ('GITHUB_SHA', 'invalid'), ('GITHUB_RUN_ID', 'invalid'),
])
def test_refuses_unsafe_identity(key, value):
    with pytest.raises(ValueError):
        release.release_identity({**ENV, key: value})


def test_manual_main_release():
    assert release.release_identity({**ENV, 'GITHUB_EVENT_NAME': 'workflow_dispatch'})[1] == SHA


@pytest.mark.parametrize('rows', [f'runtime {ID}\n', f'runtime {ID}\nruntime {ID}\n', 'runtime bogus\n'])
def test_bad_inventory(tmp_path, rows):
    p = tmp_path / 'ids'; p.write_text(rows)
    with pytest.raises(ValueError):
        release.read_ids(p)


def test_registry_digest_not_local_image_id():
    assert release.push_digest(f'tag: digest: {REGISTRY_DIGEST} size: 100') == REGISTRY_DIGEST
    with pytest.raises(ValueError):
        release.push_digest('no digest')


@pytest.fixture
def fake_bundle(tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary'))
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    (bundle / 'image-ids.txt').write_text(''.join(f'{role} {ID}\n' for role in release.ROLES))
    (bundle / 'images.tar.gz').touch()
    return bundle


def fake_docker(calls, *, bad_id=False, fail_push=False):
    def invoke(*args, input_text=None):
        calls.append(args)
        if args[:2] == ('image', 'inspect'):
            return json.dumps([{'Id': 'sha256:' + 'd' * 64 if bad_id else ID,
                                'Os': 'linux', 'Architecture': 'amd64',
                                'Config': {'Labels': {
                                    'org.opencontainers.image.revision': SHA,
                                    'org.opencontainers.image.source': 'https://github.com/Example/Marine'}}}])
        if args[0] == 'login':
            assert input_text == 'test-only\n'
        if args[:2] == ('image', 'push'):
            if fail_push and '-ui:' in args[-1]:
                raise RuntimeError('simulated push failure')
            return f'tag: digest: {REGISTRY_DIGEST} size: 100'
        return ''
    return invoke


def test_publish_manifest(fake_bundle, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(release, 'docker', fake_docker(calls))
    out = tmp_path / 'release'
    manifest = release.publish(fake_bundle, out)
    assert len([c for c in calls if c[:2] == ('image', 'push')]) == 3
    assert calls[-1] == ('logout', 'ghcr.io')
    assert manifest['images']['runtime']['image_id'] == ID
    assert manifest['images']['runtime']['digest'] == REGISTRY_DIGEST
    assert json.loads((out / 'release.json').read_text()) == manifest
    assert f'MARINE_RUNTIME_IMAGE=ghcr.io/example/marine-runtime@{REGISTRY_DIGEST}' in (out / 'release.env').read_text()
    assert 'test-only' not in (out / 'release.json').read_text()


def test_bad_image_never_logs_in(fake_bundle, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(release, 'docker', fake_docker(calls, bad_id=True))
    with pytest.raises(ValueError, match='identity mismatch'):
        release.publish(fake_bundle, tmp_path / 'release')
    assert not any(c[0] == 'login' for c in calls)


def test_partial_push_has_no_release_manifest(fake_bundle, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(release, 'docker', fake_docker(calls, fail_push=True))
    out = tmp_path / 'release'
    with pytest.raises(RuntimeError):
        release.publish(fake_bundle, out)
    assert calls[-1] == ('logout', 'ghcr.io')
    assert not (out / 'release.json').exists()
    assert not (out / 'release.env').exists()

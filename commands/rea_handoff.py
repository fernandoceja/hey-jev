"""Portable clean-room handoffs. Only the allowlisted spec files reach builders."""
import json
import re
from datetime import datetime
from pathlib import Path

FILES = {'findings': 'findings.md', 'build_plan': 'build-plan.md', 'review': 'review.md'}
FIELDS = {'schema_version', 'request_id', 'created', 'mode', 'target_kind', 'feature',
          'suggested_builder', 'clean_room', 'files'}


def strip_target_path(text, target=None):
    if target:
        text = text.replace(str(target), '[research target]')
        text = text.replace(str(target).replace('/', '\\/'), '[research target]')
    text = re.sub(r'file:(?://)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[A-Za-z]:[\\/][^\s\"<>`]*', '[local path]', text)
    # Builder-bound prose must not contain filesystem absolute paths, including
    # other evidence paths embedded by the researcher.
    return re.sub(r'(?<![\w:/])(?:~/|/)[^\s\"<>`]*', '[local path]', text)


def validate(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('Invalid handoff fields (target paths are forbidden).')
    for key in FIELDS - {'clean_room', 'files'}:
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError('Invalid handoff ' + key)
    if data['schema_version'] != '1.0' or data['clean_room'] is not True:
        raise ValueError('A clean_room=true schema 1.0 handoff is required.')
    if data['mode'] not in ('research', 'review', 'replicate') or data['target_kind'] not in ('app', 'file', 'folder', 'repo', 'build', 'unknown') or data['suggested_builder'] not in ('nxnative', 'new_app', 'none'):
        raise ValueError('Invalid handoff mode, target kind, or builder.')
    datetime.fromisoformat(data['created'])
    if data['files'] != dict(FILES, review='review.md' if data['mode'] == 'review' else None):
        raise ValueError('Invalid spec file manifest.')
    for key in ('request_id', 'feature'):
        if strip_target_path(data[key]) != data[key] or re.search(r'[A-Za-z]:[\\/]', data[key]):
            raise ValueError('Target paths are forbidden in handoffs.')
    return data


def load(request):
    spec = Path(request) / 'spec'
    if spec.is_symlink():
        raise ValueError('Spec must not be a symlink.')
    manifest = spec / 'handoff.json'
    if manifest.is_symlink():
        raise ValueError('Handoff must not be a symlink.')
    data = validate(json.loads(manifest.read_text(encoding='utf-8')))
    for name in data['files'].values():
        if name and (not (spec / name).is_file() or (spec / name).is_symlink()):
            raise ValueError('Missing or linked spec artifact: ' + name)
    return data


def create(request, mode, target_kind, feature, target=None):
    request = Path(request)
    spec = request / 'spec'
    if spec.is_symlink():
        raise ValueError('Spec must not be a symlink.')
    spec.mkdir(exist_ok=True)
    for key, name in FILES.items():
        if key == 'review' and mode != 'review':
            continue
        source = request / name
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing research artifact: ' + name)
        dest = spec / name
        if dest.is_symlink():
            raise ValueError('Linked spec artifact.')
        dest.write_text(strip_target_path(source.read_text(encoding='utf-8'), target), encoding='utf-8')
    data = dict(schema_version='1.0', request_id=strip_target_path(request.name, target),
                created=datetime.now().astimezone().isoformat(), mode=mode,
                target_kind=target_kind, feature=strip_target_path(feature, target),
                suggested_builder='none', clean_room=True,
                files=dict(FILES, review='review.md' if mode == 'review' else None))
    validate(data)
    manifest = spec / 'handoff.json'
    if manifest.is_symlink():
        raise ValueError('Linked handoff.')
    manifest.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    return data


def copy_spec(request, destination):
    data = load(request)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    # Re-serialize and sanitize; never copy arbitrary files or links from spec/.
    (destination / 'handoff.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    for name in data['files'].values():
        if name:
            text = (Path(request) / 'spec' / name).read_text(encoding='utf-8')
            (destination / name).write_text(strip_target_path(text), encoding='utf-8')
    return data

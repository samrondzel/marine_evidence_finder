"""Opt-in, source-specific correction of visually verified P05 PDF glyph errors.
Dry run by default. Never changes the PDF, uploaded documents or other sources.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

PDF_SHA256 = 'e1cd83902a9d9d256039794f35c0680ebfc2a77a7acaa421b2a6b8b2c9a252b5'
# chunk ID -> original text SHA256, corrected text SHA256, replacement count
REVIEWED = {'P05:p0001:c0002': ('f46577b95c935b25056392ac1177cda8ab98d9f13d2d4b8a74d89b9ca75438f1',
                     '048eb6baad5cc3aeff0957468cbb8b02917e98b6f2a4f4d52eea6e9ef9425c69',
                     1),
 'P05:p0002:c0002': ('cb1474e6ee0bc02d7c5ad51bc5c77603c2f643e1a8c49c413385119a5fd73308',
                     '6e594d9cee73c21e52367906ea6e1379e878b2a800920d3068fe38261171ffe2',
                     1),
 'P05:p0002:c0003': ('b0351c87b6ad0bc297fe72ff626dc18e0fe0da8e8aaeaf713e34eb097ab5c794',
                     'bcecde22411e41a69d7f0f73e8984067f3f736c1a1956fe0c2eb573203ccdb13',
                     1),
 'P05:p0004:c0001': ('dcd3cc6186a6548b46488da1bd8e89f25db06f61f7be90fb00d099b770962734',
                     '9e9e8ffe7947db283688dea46aae372f3a7fc9c5fde3f5030c2c7b6dc57969bd',
                     2),
 'P05:p0005:c0001': ('4c3e4854268342c0e1791037b327dc7e08e247cbc493163242fb0fb0341b0c0d',
                     '98b468fa2a311bd23f5eef42b6299776aa63a360dd49daa59332e04226d23e14',
                     1),
 'P05:p0006:c0001': ('0ed9b0cbe870d068c119cd53cb089be246a8b32f0386464940ab2018acc1b9d2',
                     '32e8dff43f26b13cd87d0932f22ad44e1e2d213f85cbd7d37239c3e24be1d7f5',
                     4),
 'P05:p0007:c0003': ('3dcafc7abc359869416d421627eebe26364a8c68ad3ce8a90dbdd286bd3df37b',
                     'cac328683caa05964f4c2b4aead4dd5b1073da901a72995d83a32a664f068b83',
                     1),
 'P05:p0008:c0001': ('046ce72365c0499a0028ff937bc58cf1d56eaa1916553ec857d390cbf8ee877e',
                     '5998e6b3324c5823de120acb782d56fa712872ca382b4e7c5f28472925e3a9c2',
                     1)}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corrected_bytes(raw: bytes) -> tuple[bytes, int]:
    seen = set()
    changes = 0
    output = []
    for line in raw.decode('utf-8-sig').splitlines(keepends=True):
        if not line.strip():
            output.append(line)
            continue
        item = json.loads(line)
        cid = item['chunk_id']
        if cid not in REVIEWED:
            if item.get('source_id') == 'P05' and re.search(r'\bmPa\b', item['text']):
                raise ValueError(f'Unreviewed P05 unit in {cid}; stop and inspect manually')
            output.append(line)
            continue
        if cid in seen or item['source_id'] != 'P05' or item['filename'] != 'rspb20172314.pdf':
            raise ValueError(f'Unexpected chunk metadata: {cid}')
        seen.add(cid)
        before, after, expected = REVIEWED[cid]
        h = digest(item['text'].encode('utf-8'))
        if h == after:
            output.append(line)
            continue
        if h != before:
            raise ValueError(f'Chunk hash changed: {cid}; no automatic correction')
        revised, n = re.subn(r'\bmPa\b', 'μPa', item['text'])
        if n != expected or digest(revised.encode('utf-8')) != after or len(revised) != len(item['text']):
            raise ValueError(f'Unexpected correction: {cid}')
        item['text'] = revised
        changes += n
        output.append(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n')
    if seen != set(REVIEWED):
        raise ValueError('Reviewed chunks missing; no automatic correction')
    return ''.join(output).encode('utf-8'), changes


def run(pdf: Path, chunks: Path, *, apply: bool = False) -> int:
    if digest(pdf.read_bytes()) != PDF_SHA256:
        raise ValueError('PDF hash does not match the visually reviewed version')
    raw = chunks.read_bytes()
    updated, changes = corrected_bytes(raw)
    if not changes:
        print('Already corrected; no write needed.')
        return 0
    print(f'{changes} visually verified unit corrections in {len(REVIEWED)} reviewed chunks')
    if not apply:
        print('DRY RUN: no files changed. Use --apply with API stopped to write.')
        return changes
    backup = chunks.with_name(chunks.name + '.before_p05_unit_fix')
    # Exclusive backup; refuse to overwrite an existing original.
    with backup.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=chunks.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, chunks)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    print(f'Updated {chunks}; original backup: {backup}')
    return changes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pdf', type=Path, default=Path('papers/rspb20172314.pdf'))
    p.add_argument('--chunks', type=Path, default=Path('data/chunks/word_safe/chunks.jsonl'))
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    try:
        run(args.pdf, args.chunks, apply=args.apply)
    except (ValueError, OSError, KeyError) as exc:
        p.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()

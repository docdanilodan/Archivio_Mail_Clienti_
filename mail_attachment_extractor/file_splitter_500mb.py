# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHUNK_SIZE = 500 * 1024 * 1024


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def split_file(source: str, output_dir: str, chunk_size: int = CHUNK_SIZE) -> Path:
    src = Path(source)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    total_size = src.stat().st_size
    parts = []
    with src.open('rb') as fin:
        index = 1
        while True:
            data = fin.read(chunk_size)
            if not data:
                break
            name = f'{src.name}.part{index:04d}'
            part_path = out / name
            with part_path.open('wb') as fout:
                fout.write(data)
            parts.append({
                'index': index,
                'name': name,
                'size': len(data),
                'sha256': sha256_file(part_path),
            })
            index += 1

    manifest = {
        'original_name': src.name,
        'original_size': total_size,
        'chunk_size': chunk_size,
        'parts': parts,
        'original_sha256': sha256_file(src),
    }
    manifest_path = out / f'{src.name}.manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest_path


def join_parts(parts: list[str], output_file: str) -> Path:
    ordered = sorted((Path(p) for p in parts), key=lambda p: p.name)
    out = Path(output_file)
    with out.open('wb') as fout:
        for part in ordered:
            with part.open('rb') as fin:
                while True:
                    block = fin.read(8 * 1024 * 1024)
                    if not block:
                        break
                    fout.write(block)
    return out


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Divide file grandi in parti da circa 500 MB')
    sub = parser.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('split')
    s.add_argument('source')
    s.add_argument('output_dir')
    s.add_argument('--mb', type=int, default=500)

    j = sub.add_parser('join')
    j.add_argument('output_file')
    j.add_argument('parts', nargs='+')

    args = parser.parse_args()
    if args.cmd == 'split':
        manifest = split_file(args.source, args.output_dir, args.mb * 1024 * 1024)
        print(manifest)
    else:
        print(join_parts(args.parts, args.output_file))

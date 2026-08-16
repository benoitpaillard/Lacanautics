#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import math
import shutil
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path('.')
OUT_ROOT = ROOT / 'tiles' / 'mobile-v1'
TILE = 1024
LEVELS = [2, 4, 8]


def v31_world_size() -> tuple[int, int]:
    data = json.loads((ROOT / 'data/lacanau_2012_bands_v3.json').read_text())
    b = data['bbox']
    w = 1000
    lat0 = (b['south'] + b['north']) / 2 * math.pi / 180
    width_m = (b['east'] - b['west']) * 111320 * math.cos(lat0)
    height_m = (b['north'] - b['south']) * 111320
    h = round(w * height_m / width_m)
    return w, h


def render_and_tile(src: Path, key: str, base_w: int, base_h: int) -> dict:
    target = OUT_ROOT / key
    if target.exists():
        shutil.rmtree(target)
    result = {'base_size': [base_w, base_h], 'levels': {}}

    for level in LEVELS:
        width = base_w * level
        height = base_h * level
        png = cairosvg.svg2png(
            bytestring=src.read_bytes(),
            output_width=width,
            output_height=height,
        )
        image = Image.open(io.BytesIO(png)).convert('RGBA')
        level_dir = target / str(level)
        level_dir.mkdir(parents=True, exist_ok=True)
        cols = math.ceil(width / TILE)
        rows = math.ceil(height / TILE)
        total_bytes = 0
        for y in range(rows):
            for x in range(cols):
                left = x * TILE
                top = y * TILE
                right = min(width, left + TILE)
                bottom = min(height, top + TILE)
                tile = image.crop((left, top, right, bottom))
                out = level_dir / f'{x}_{y}.png'
                tile.save(out, 'PNG', optimize=True, compress_level=9)
                total_bytes += out.stat().st_size
        result['levels'][str(level)] = {
            'pixel_size': [width, height],
            'cols': cols,
            'rows': rows,
            'bytes': total_bytes,
        }
        print(f'{key} level {level}: {width}x{height}, {cols}x{rows} tiles, {total_bytes} bytes')
    return result


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    v45_meta = json.loads((ROOT / 'data/lacanau_geopdf_v41.json').read_text())
    v45_w, v45_h = int(v45_meta['width']), int(v45_meta['height'])
    v31_w, v31_h = v31_world_size()

    manifest = {
        'version': 'mobile-v1',
        'tile_px': TILE,
        'levels': LEVELS,
        'maps': {
            'vector': render_and_tile(ROOT / 'bathymetry-geopdf-v45-taubin.svg', 'vector', v45_w, v45_h),
            'v31': render_and_tile(ROOT / 'bathymetry-2012-v31.svg', 'v31', v31_w, v31_h),
        },
    }
    (OUT_ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

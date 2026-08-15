#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path('.')
SRC = ROOT / 'data/lacanau_2012_bands_v3.json'
V41 = ROOT / 'data/lacanau_geopdf_v41.json'
OUT = ROOT / 'bathymetry-2012-v3.webp'
REPORT = ROOT / 'data/lacanau_v31_visual_report.json'

LAND = np.array([238, 240, 232], dtype=np.uint8)  # #eef0e8, app land/background
CONTOUR = np.array([36, 78, 90], dtype=np.uint8)  # #244e5a, Vector 4.5 isobaths
SCALE = 2  # 5 m rendered pixel from the 10 m v3.1 survey grid
INNER_ALPHA = 0.48
SHORE_ALPHA = 0.62


def blend(rgb: np.ndarray, mask: np.ndarray, color: np.ndarray, alpha: float) -> None:
    if not np.any(mask):
        return
    base = rgb[mask].astype(np.float32)
    rgb[mask] = np.rint(base * (1.0 - alpha) + color.astype(np.float32) * alpha).astype(np.uint8)


def main() -> None:
    src = json.loads(SRC.read_text())
    v41 = json.loads(V41.read_text())
    palette = np.asarray(v41['palette_rgb'][:8], dtype=np.uint8)
    rows = src['rows_south_to_north']
    ny, nx = int(src['ny']), int(src['nx'])
    if len(rows) != ny or any(len(r) != nx for r in rows):
        raise RuntimeError('v3.1 grid dimensions do not match metadata')

    # JSON rows are south->north, while image rows are top->bottom (north->south).
    cls = np.full((ny, nx), -1, dtype=np.int8)
    for sy, row in enumerate(rows):
        y = ny - 1 - sy
        vals = np.frombuffer(row.encode('ascii'), dtype=np.uint8)
        valid = (vals >= ord('0')) & (vals <= ord('7'))
        cls[y, valid] = vals[valid] - ord('0')

    # Nearest-neighbour enlargement preserves the original v3.1 geometry exactly.
    hi = np.repeat(np.repeat(cls, SCALE, axis=0), SCALE, axis=1)
    rgb = np.empty((*hi.shape, 3), dtype=np.uint8)
    rgb[:] = LAND
    for k, c in enumerate(palette):
        rgb[hi == k] = c

    water = hi >= 0
    # One rendered pixel contour at every class transition. At SCALE=2 this is
    # ~5 m wide, close to Vector 4.5's ~3.5 m cartographic contour width.
    inner = np.zeros(hi.shape, dtype=bool)
    diff_h = water[:, 1:] & water[:, :-1] & (hi[:, 1:] != hi[:, :-1])
    inner[:, 1:] |= diff_h
    diff_v = water[1:, :] & water[:-1, :] & (hi[1:, :] != hi[:-1, :])
    inner[1:, :] |= diff_v

    shore = np.zeros(hi.shape, dtype=bool)
    shore[:, 1:] |= water[:, 1:] & ~water[:, :-1]
    shore[:, :-1] |= water[:, :-1] & ~water[:, 1:]
    shore[1:, :] |= water[1:, :] & ~water[:-1, :]
    shore[:-1, :] |= water[:-1, :] & ~water[1:, :]

    blend(rgb, inner, CONTOUR, INNER_ALPHA)
    blend(rgb, shore, CONTOUR, SHORE_ALPHA)

    Image.fromarray(rgb, 'RGB').save(OUT, 'WEBP', lossless=True, method=6)

    report = {
        'version': '3.1-harmonized-visual',
        'source_version': src.get('version'),
        'geometry_note': 'Original 10 m v3.1 class grid unchanged; only visual rendering changed.',
        'palette_rgb': palette.tolist(),
        'palette_hex': ['#%02x%02x%02x' % tuple(map(int, c)) for c in palette],
        'land_hex': '#eef0e8',
        'contour_hex': '#244e5a',
        'inner_contour_opacity': INNER_ALPHA,
        'shoreline_opacity': SHORE_ALPHA,
        'render_scale': SCALE,
        'render_size_px': [int(nx * SCALE), int(ny * SCALE)],
        'survey_step_m': src.get('step_m'),
        'webp_bytes': OUT.stat().st_size,
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

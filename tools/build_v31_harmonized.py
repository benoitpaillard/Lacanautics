#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from skimage.measure import approximate_polygon, find_contours

ROOT = Path('.')
SRC = ROOT / 'data/lacanau_2012_bands_v3.json'
V41 = ROOT / 'data/lacanau_geopdf_v41.json'
OUT = ROOT / 'bathymetry-2012-v31.svg'
REPORT = ROOT / 'data/lacanau_v31_visual_report.json'

CONTOUR_HEX = '#244e5a'
INNER_OPACITY = 0.48
SHORE_OPACITY = 0.62
INNER_WIDTH = 0.62
SHORE_WIDTH = 0.72
SIMPLIFY_TOLERANCE = 0.05
PAD = 1


def load_classes(src: dict) -> np.ndarray:
    rows = src['rows_south_to_north']
    ny, nx = int(src['ny']), int(src['nx'])
    if len(rows) != ny or any(len(r) != nx for r in rows):
        raise RuntimeError('v3.1 grid dimensions do not match metadata')

    cls = np.full((ny, nx), -1, dtype=np.int8)
    for sy, row in enumerate(rows):
        y = ny - 1 - sy
        vals = np.frombuffer(row.encode('ascii'), dtype=np.uint8)
        valid = (vals >= ord('0')) & (vals <= ord('7'))
        cls[y, valid] = vals[valid] - ord('0')
    return cls


def extract_rings(mask: np.ndarray) -> list[np.ndarray]:
    field = np.pad(mask.astype(float), PAD, mode='constant')
    rings: list[np.ndarray] = []
    for arr in find_contours(field, 0.5, fully_connected='high'):
        if len(arr) < 4:
            continue
        # find_contours returns cell-centre boundaries. +0.5 maps them back to
        # the original raster cell edges: outer shoreline at 0 / nx / ny and
        # class transitions exactly between neighbouring 10 m survey cells.
        pts = np.asarray(
            [(float(c) - PAD + 0.5, float(r) - PAD + 0.5) for r, c in arr],
            dtype=float,
        )
        if np.linalg.norm(pts[0] - pts[-1]) < 1e-9:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        closed = np.vstack([pts, pts[0]])
        simp = approximate_polygon(closed, tolerance=SIMPLIFY_TOLERANCE)
        if len(simp) > 1 and np.linalg.norm(simp[0] - simp[-1]) < 1e-9:
            simp = simp[:-1]
        if len(simp) >= 3:
            rings.append(simp)
    return rings


def path_data(rings: list[np.ndarray]) -> str:
    return ' '.join(
        f'M {pts[0,0]:.3f},{pts[0,1]:.3f}'
        + ''.join(f' L {x:.3f},{y:.3f}' for x, y in pts[1:])
        + ' Z'
        for pts in rings
    )


def nested_uses(kind: str, colors: list[str] | None = None) -> str:
    chunks: list[str] = []
    if kind == 'fill':
        chunks.append(f'<use id="depth-fill-0" href="#geom-0" fill="{colors[0]}" fill-rule="evenodd"/>')
    else:
        chunks.append(
            f'<use id="shoreline" href="#geom-0" fill="none" stroke="{CONTOUR_HEX}" '
            f'stroke-opacity="{SHORE_OPACITY}" stroke-width="{SHORE_WIDTH}" '
            'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        )

    for k in range(1, 8):
        chunks.append(f'<g clip-path="url(#clip-{k-1})">')
        if kind == 'fill':
            chunks.append(f'<use id="depth-fill-{k}" href="#geom-{k}" fill="{colors[k]}" fill-rule="evenodd"/>')
        else:
            chunks.append(
                f'<use id="isobath-{k}m" href="#geom-{k}" fill="none" stroke="{CONTOUR_HEX}" '
                f'stroke-opacity="{INNER_OPACITY}" stroke-width="{INNER_WIDTH}" '
                'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
            )
    chunks.extend('</g>' for _ in range(7))
    return ''.join(chunks)


def main() -> None:
    src = json.loads(SRC.read_text())
    v41 = json.loads(V41.read_text())
    cls = load_classes(src)
    ny, nx = cls.shape

    palette = np.asarray(v41['palette_rgb'][:8], dtype=np.uint8)
    colors = ['#%02x%02x%02x' % tuple(map(int, c)) for c in palette]

    ring_sets: list[list[np.ndarray]] = []
    for k in range(8):
        ring_sets.append(extract_rings(cls >= k))

    defs = ''.join(
        f'<path id="geom-{k}" d="{path_data(rings)}" fill-rule="evenodd"/>'
        for k, rings in enumerate(ring_sets)
    )
    defs += ''.join(
        f'<clipPath id="clip-{k}"><use href="#geom-{k}" fill-rule="evenodd"/></clipPath>'
        for k in range(7)
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {nx} {ny}" preserveAspectRatio="none" shape-rendering="geometricPrecision">'
        '<title>Lac de Lacanau Survey v3.1 bathymetry</title>'
        '<desc>Original 10 m Survey v3.1 depth classes rendered with the same palette and line styling as Vector 4.5. Geometry is not smoothed.</desc>'
        '<defs>' + defs + '</defs>'
        '<g id="depth-bands">' + nested_uses('fill', colors) + '</g>'
        '<g id="depth-lines">' + nested_uses('line') + '</g>'
        '</svg>'
    )
    OUT.write_text(svg, encoding='utf-8')

    report = {
        'version': '3.1-harmonized-vector-lines',
        'source_version': src.get('version'),
        'geometry_note': 'Original 10 m v3.1 class grid unchanged; boundaries are vectorized at cell edges with no smoothing.',
        'asset': OUT.name,
        'palette_rgb': palette.tolist(),
        'palette_hex': colors,
        'land_hex': '#eef0e8',
        'contour_hex': CONTOUR_HEX,
        'inner_contour_opacity': INNER_OPACITY,
        'shoreline_opacity': SHORE_OPACITY,
        'inner_contour_width_px': INNER_WIDTH,
        'shoreline_width_px': SHORE_WIDTH,
        'line_join': 'round',
        'line_cap': 'round',
        'vector_effect': 'non-scaling-stroke',
        'survey_step_m': src.get('step_m'),
        'source_grid_size': [nx, ny],
        'rings_by_threshold': [len(r) for r in ring_sets],
        'svg_bytes': OUT.stat().st_size,
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

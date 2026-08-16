#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from skimage.draw import polygon

ROOT = Path('.')
DEFAULT_MASK = ROOT / 'data/lacanau_open_water_mask.geojson'


def _polygons(geometry: dict):
    t = geometry.get('type')
    c = geometry.get('coordinates', [])
    if t == 'Polygon':
        yield c
    elif t == 'MultiPolygon':
        yield from c
    else:
        raise ValueError(f'Unsupported shoreline geometry type: {t}')


def rasterize_open_water(shape: tuple[int, int], bbox: dict, mask_path: Path = DEFAULT_MASK) -> np.ndarray:
    """Rasterize the committed WGS84 open-water shoreline onto a north-up class grid."""
    h, w = shape
    data = json.loads(Path(mask_path).read_text(encoding='utf-8'))
    geom = data['geometry'] if data.get('type') == 'Feature' else data
    west, east = float(bbox['west']), float(bbox['east'])
    south, north = float(bbox['south']), float(bbox['north'])
    out = np.zeros((h, w), dtype=bool)

    def xy(ring):
        a = np.asarray(ring, dtype=float)
        x = (a[:, 0] - west) / (east - west) * (w - 1)
        y = (north - a[:, 1]) / (north - south) * (h - 1)
        return x, y

    for rings in _polygons(geom):
        if not rings:
            continue
        x, y = xy(rings[0])
        rr, cc = polygon(y, x, shape=(h, w))
        out[rr, cc] = True
        for hole in rings[1:]:
            x, y = xy(hole)
            rr, cc = polygon(y, x, shape=(h, w))
            out[rr, cc] = False
    return out


def mask_classes(cls: np.ndarray, bbox: dict, mask_path: Path = DEFAULT_MASK):
    before = cls >= 0
    water = rasterize_open_water(cls.shape, bbox, mask_path)
    corrected = cls.copy()
    corrected[~water] = -1
    after = corrected >= 0
    removed = before & ~after
    stats = {
        'authority': 'IGN BD TOPO V3 permanent non-marsh hydrography',
        'mask_asset': str(mask_path),
        'water_cells_before': int(before.sum()),
        'water_cells_after': int(after.sum()),
        'water_cells_removed': int(removed.sum()),
        'removed_fraction_of_original_water': float(removed.sum() / max(1, before.sum())),
        'adds_water': False,
    }
    return corrected, stats

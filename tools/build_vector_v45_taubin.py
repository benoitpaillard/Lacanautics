#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import ndimage
from skimage.draw import polygon
from skimage.measure import approximate_polygon, find_contours

import build_vector_v44 as v44
import shoreline_mask

ROOT = Path('.')
OUT_SVG = ROOT / 'bathymetry-geopdf-v45-taubin.svg'
OUT_REPORT = ROOT / 'data/lacanau_vector_v45_taubin_report.json'

SIGMA_BY_THRESHOLD = v44.SIGMA_BY_THRESHOLD
TAUBIN_LAMBDA = 0.50
TAUBIN_MU = -0.53
# Shoreline and the small 6–8 m zones stay exactly on the v4.4 geometry.
TARGET_ITERATIONS = [0, 4, 4, 4, 3, 2, 0, 0]
MIN_PERIMETER_PX = [1e9, 28, 28, 28, 24, 20, 16, 1e9]
SIMPLIFY_TOLERANCE_PX = 0.18
V44_SIMPLIFY_TOLERANCE_PX = 0.12
PAD = v44.PAD


def perimeter(pts: np.ndarray) -> float:
    return float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum())


def signed_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def roughness_rms(pts: np.ndarray) -> float:
    if len(pts) < 3:
        return 0.0
    lap = 0.5 * (np.roll(pts, 1, axis=0) + np.roll(pts, -1, axis=0)) - pts
    return float(np.sqrt(np.mean(np.sum(lap * lap, axis=1))))


def taubin_closed(pts: np.ndarray, iterations: int) -> np.ndarray:
    q = np.asarray(pts, dtype=float).copy()
    for _ in range(iterations):
        lap = 0.5 * (np.roll(q, 1, axis=0) + np.roll(q, -1, axis=0)) - q
        q = q + TAUBIN_LAMBDA * lap
        lap = 0.5 * (np.roll(q, 1, axis=0) + np.roll(q, -1, axis=0)) - q
        q = q + TAUBIN_MU * lap
    return q


def simplify_closed(pts: np.ndarray, tolerance: float) -> np.ndarray:
    closed = np.vstack([pts, pts[0]])
    simp = approximate_polygon(closed, tolerance=tolerance)
    if len(simp) > 1 and np.linalg.norm(simp[0] - simp[-1]) < 1e-8:
        simp = simp[:-1]
    return simp if len(simp) >= 3 else pts


def extract_raw_rings(field: np.ndarray):
    rings = []
    for arr in find_contours(field, 0.5, fully_connected='high'):
        if len(arr) < 4:
            continue
        pts = np.asarray([(float(c) - PAD, float(r) - PAD) for r, c in arr], dtype=float)
        if np.linalg.norm(pts[0] - pts[-1]) < 1e-8:
            pts = pts[:-1]
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def process_rings(raw_rings, threshold: int):
    iterations = TARGET_ITERATIONS[threshold]
    tolerance = V44_SIMPLIFY_TOLERANCE_PX if iterations == 0 else SIMPLIFY_TOLERANCE_PX
    out, stats = [], []
    for raw in raw_rings:
        do_smooth = iterations > 0 and perimeter(raw) >= MIN_PERIMETER_PX[threshold]
        smooth = taubin_closed(raw, iterations) if do_smooth else raw.copy()
        disp = np.linalg.norm(smooth - raw, axis=1)
        a0 = abs(signed_area(raw)); a1 = abs(signed_area(smooth))
        simp = simplify_closed(smooth, tolerance)
        out.append(simp)
        stats.append({
            'smoothed': bool(do_smooth),
            'raw_vertices': int(len(raw)),
            'svg_vertices': int(len(simp)),
            'perimeter_px': perimeter(raw),
            'roughness_before': roughness_rms(raw),
            'roughness_after': roughness_rms(smooth),
            'max_displacement_px': float(disp.max(initial=0.0)),
            'p95_displacement_px': float(np.percentile(disp, 95)) if len(disp) else 0.0,
            'area_ratio': float(a1 / a0) if a0 > 1e-12 else 1.0,
        })
    return out, stats, iterations, tolerance


def rasterize_evenodd(rings, h: int, w: int) -> np.ndarray:
    mask = np.zeros((h, w), dtype=bool)
    for pts in rings:
        rr, cc = polygon(pts[:, 1], pts[:, 0], shape=(h, w))
        mask[rr, cc] ^= True
    return mask


def path_data(rings) -> str:
    return ' '.join(
        f'M {pts[0,0]:.3f},{pts[0,1]:.3f}'
        + ''.join(f' L {x:.3f},{y:.3f}' for x, y in pts[1:])
        + ' Z'
        for pts in rings
    )


def nested_uses(kind: str, colors=None):
    """Render recursively clipped layers without duplicating path data."""
    chunks = []
    if kind == 'fill':
        chunks.append(f'<use id="depth-fill-0" href="#geom-0" fill="{colors[0]}" fill-rule="evenodd"/>')
    else:
        chunks.append('<use id="shoreline" href="#geom-0" fill="none" stroke="#244e5a" stroke-opacity="0.62" stroke-width="0.72" stroke-linejoin="round" stroke-linecap="round"/>')
    for k in range(1, 8):
        chunks.append(f'<g clip-path="url(#clip-{k-1})">')
        if kind == 'fill':
            chunks.append(f'<use id="depth-fill-{k}" href="#geom-{k}" fill="{colors[k]}" fill-rule="evenodd"/>')
        else:
            chunks.append(f'<use id="isobath-{k}m" href="#geom-{k}" fill="none" stroke="#244e5a" stroke-opacity="0.48" stroke-width="0.62" stroke-linejoin="round" stroke-linecap="round"/>')
    chunks.extend('</g>' for _ in range(7))
    return ''.join(chunks)


def build_geometry(pal: np.ndarray, cls: np.ndarray):
    h, w = cls.shape
    ring_sets, raw_masks, masks, layer_stats = [], [], [], []

    for k, sigma in enumerate(SIGMA_BY_THRESHOLD):
        field = v44.smooth_field(cls >= k, sigma)
        raw = extract_raw_rings(field)
        rings, stats, iterations, tolerance = process_rings(raw, k)
        raw_mask = rasterize_evenodd(rings, h, w)
        mask = raw_mask if k == 0 else (raw_mask & masks[k - 1])
        ring_sets.append(rings); raw_masks.append(raw_mask); masks.append(mask)

        smoothed = [s for s in stats if s['smoothed']]
        weighted_before = sum(s['roughness_before'] * s['raw_vertices'] for s in smoothed)
        weighted_after = sum(s['roughness_after'] * s['raw_vertices'] for s in smoothed)
        weight = sum(s['raw_vertices'] for s in smoothed)
        disps = [s['max_displacement_px'] for s in smoothed]
        area_errs = [abs(s['area_ratio'] - 1.0) for s in smoothed]
        spill = int(np.sum(raw_mask & ~masks[k - 1])) if k else 0
        layer_stats.append({
            'threshold_m': k,
            'gaussian_sigma_px': sigma,
            'taubin_iterations': iterations,
            'lambda': TAUBIN_LAMBDA,
            'mu': TAUBIN_MU,
            'simplify_tolerance_px': tolerance,
            'rings': len(rings),
            'rings_taubin_smoothed': len(smoothed),
            'raw_vertices': int(sum(s['raw_vertices'] for s in stats)),
            'svg_vertices': int(sum(s['svg_vertices'] for s in stats)),
            'roughness_rms_before': float(weighted_before / weight) if weight else 0.0,
            'roughness_rms_after': float(weighted_after / weight) if weight else 0.0,
            'roughness_ratio': float(weighted_after / weighted_before) if weighted_before > 0 else 1.0,
            'max_taubin_displacement_px': max(disps, default=0.0),
            'max_abs_area_change_fraction': max(area_errs, default=0.0),
            'preclip_spill_cells': spill,
            'cells_removed_by_parent_clip': int(np.sum(raw_mask & ~mask)),
        })

    nested_violations = [int(np.sum(masks[k] & ~masks[k - 1])) for k in range(1, 8)]
    if any(nested_violations):
        raise RuntimeError(f'clipped nesting failure: {nested_violations}')

    path_sets = [path_data(r) for r in ring_sets]
    defs = ''.join(f'<path id="geom-{k}" d="{d}" fill-rule="evenodd"/>' for k, d in enumerate(path_sets))
    # Each clip references the geometry already stored once in defs; nested groups make
    # the clipping cumulative, so a deeper band can never escape any shallower band.
    defs += ''.join(f'<clipPath id="clip-{k}"><use href="#geom-{k}" fill-rule="evenodd"/></clipPath>' for k in range(7))
    colors = ['#%02x%02x%02x' % tuple(int(v) for v in pal[k]) for k in range(8)]

    labels = []
    label_count = 0
    for k in range(1, 8):
        chosen = 0
        for ring in sorted(ring_sets[k], key=perimeter, reverse=True)[:8]:
            if perimeter(ring) < 180:
                continue
            p, ang, _ = v44.point_on_ring(ring, 0.46 if chosen == 0 else 0.72)
            x, y = float(p[0]), float(p[1])
            if not (15 < x < w - 15 and 15 < y < h - 15):
                continue
            labels.append(
                f'<text x="{x:.2f}" y="{y:.2f}" transform="rotate({ang:.1f} {x:.2f} {y:.2f})" text-anchor="middle" dominant-baseline="central" '
                'font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="8.4" font-weight="750" fill="#17343d" stroke="#ffffff" '
                f'stroke-width="1.15" paint-order="stroke" stroke-opacity="0.92">{k} m</text>'
            )
            label_count += 1; chosen += 1
            if chosen >= 2:
                break

    label_count = 0
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none" shape-rendering="geometricPrecision">'
        '<title>Lac de Lacanau bathymetry — Taubin-faired integer isobaths</title>'
        '<desc>Corrected GeoPDF 4.1 depth classes. v4.4 Gaussian occupancy iso-contours are followed by sparse non-shrinking Taubin curve smoothing, Douglas-Peucker simplification, and cumulative parent clipping. Depth classes come from corrected v4.1 and are clipped to the IGN permanent-water shoreline.</desc>'
        '<defs>' + defs + '</defs>'
        '<g id="depth-bands">' + nested_uses('fill', colors) + '</g>'
        '<g id="depth-lines">' + nested_uses('line') + '</g>'
        '</svg>'
    )
    return svg, masks, layer_stats, nested_violations, label_count


def qc(cls: np.ndarray, masks):
    water = cls >= 0
    cart = np.full(cls.shape, -1, dtype=np.int8)
    for k, mask in enumerate(masks):
        cart[mask] = k
    cwater = cart >= 0
    overlap = water & cwater
    water_iou = float(np.sum(water & cwater) / np.sum(water | cwater))
    exact = float(np.mean(cart[overlap] == cls[overlap]))
    within1 = float(np.mean(np.abs(cart[overlap] - cls[overlap]) <= 1))
    mean_source = float(np.mean(cls[water].astype(float) + 0.5))
    mean_vector = float(np.mean(cart[cwater].astype(float) + 0.5))

    thresholds = []
    for k, mask in enumerate(masks):
        src = cls >= k
        inter = int(np.sum(src & mask)); union = int(np.sum(src | mask))
        dist = v44.symmetric_boundary_distance(src, mask)
        thresholds.append({
            'threshold_m': k,
            'iou': float(inter / union),
            'area_ratio': float(np.sum(mask) / max(1, np.sum(src))),
            'boundary_p95_px': float(np.percentile(dist, 95)),
            'boundary_p99_px': float(np.percentile(dist, 99)),
            'source_components': int(ndimage.label(src)[1]),
            'vector_components': int(ndimage.label(mask)[1]),
        })

    report = {
        'water_mask_iou': water_iou,
        'all_overlap_exact_class_fraction': exact,
        'all_overlap_within_1m_fraction': within1,
        'mean_depth_midpoint_source_m': mean_source,
        'mean_depth_midpoint_vector_m': mean_vector,
        'mean_depth_shift_m': mean_vector - mean_source,
        'threshold_qc': thresholds,
    }
    if water_iou < 0.997 or within1 < 0.999 or abs(mean_vector - mean_source) > 0.01:
        raise RuntimeError(f'global QC failed: {report}')
    for q in thresholds[:5]:
        if q['iou'] < 0.98 or q['boundary_p95_px'] > 2.1:
            raise RuntimeError(f'broad isobath QC failed: {q}')
    for q in thresholds[5:]:
        if q['iou'] < 0.97:
            raise RuntimeError(f'deep isobath QC failed: {q}')
    return report


def main():
    _, pal, cls = v44.load_classes()
    v41_meta = json.loads((ROOT / 'data/lacanau_geopdf_v41.json').read_text())
    cls, shoreline_stats = shoreline_mask.mask_classes(cls, v41_meta['bbox'])
    svg, masks, layers, nested, labels = build_geometry(pal, cls)
    q = qc(cls, masks)
    OUT_SVG.write_text(svg)
    old = json.loads((ROOT / 'data/lacanau_vector_v44_report.json').read_text())
    report = {
        'version': '4.5-taubin-candidate',
        'source_version': '4.1-fixed',
        'parent_version': '4.4-smooth-isobaths',
        'method': 'v4.4 Gaussian occupancy iso-contours -> Taubin lambda/mu low-pass on closed curves -> Douglas-Peucker simplification -> cumulative parent clipping using SVG <use>',
        'taubin_reference': 'Gabriel Taubin, Curve and Surface Smoothing without Shrinkage, ICCV 1995',
        'taubin_lambda': TAUBIN_LAMBDA,
        'taubin_mu': TAUBIN_MU,
        'target_iterations': TARGET_ITERATIONS,
        'source_resolution_m_per_px': old['source_resolution_m_per_px'],
        'nested_violations': nested,
        'depth_label_count': labels,
        'shoreline_mask': shoreline_stats,
        'layers': layers,
        'svg_bytes': len(svg.encode()),
        'v44_svg_bytes': old['svg_bytes'],
        'size_ratio_vs_v44': len(svg.encode()) / old['svg_bytes'],
        'qc': q,
        'navigation_note': 'Depth classes remain the corrected v4.1 source inside water, but both display and navigation lookup are clipped to the committed IGN permanent-water shoreline. Taubin smoothing remains visual/cartographic only.',
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

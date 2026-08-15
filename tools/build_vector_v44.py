#!/usr/bin/env python3
from __future__ import annotations

import json, math, re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.measure import approximate_polygon, find_contours

ROOT = Path('.')
CLASS_IMAGE = ROOT / 'bathymetry-geopdf-v41-classes.webp'
META_PATH = ROOT / 'data/lacanau_geopdf_v41.json'
OUT_SVG = ROOT / 'bathymetry-geopdf-v44-smooth.svg'
OUT_REPORT = ROOT / 'data/lacanau_vector_v44_report.json'

# Broad classes get enough low-pass filtering to remove the pixel/scallop frequency.
# Deep zones are smaller, so smoothing is intentionally reduced with depth.
SIGMA_BY_THRESHOLD = [1.30, 1.30, 1.30, 1.30, 1.30, 1.10, 0.90, 0.80]
SIMPLIFY_TOLERANCE_PX = 0.12
PAD = 8


def load_classes():
    meta = json.loads(META_PATH.read_text())
    im = np.asarray(Image.open(CLASS_IMAGE).convert('RGBA'))
    h, w = im.shape[:2]
    if (w, h) != (meta['width'], meta['height']):
        raise RuntimeError('class image / metadata size mismatch')
    pal = np.asarray(meta['palette_rgb'], dtype=np.int16)
    rgb = im[:, :, :3].astype(np.int16)
    water = im[:, :, 3] >= 128
    d2 = ((rgb[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
    cls = np.argmin(d2, axis=2).astype(np.int8)
    if np.any(np.min(d2, axis=2)[water] != 0):
        raise RuntimeError('class image is not exact palette data')
    cls[~water] = -1
    return meta, pal.astype(np.uint8), cls


def smooth_field(mask: np.ndarray, sigma: float) -> np.ndarray:
    padded = np.pad(mask.astype(np.float32), PAD, mode='constant', constant_values=0)
    return ndimage.gaussian_filter(padded, sigma=sigma, mode='constant', cval=0.0)


def field_mask(field: np.ndarray, h: int, w: int) -> np.ndarray:
    return field[PAD:PAD + h, PAD:PAD + w] >= 0.5


def field_paths(field: np.ndarray):
    contours = find_contours(field, 0.5, fully_connected='high')
    rings = []
    paths = []
    for arr in contours:
        if len(arr) < 4:
            continue
        pts = np.asarray([(float(c) - PAD, float(r) - PAD) for r, c in arr], dtype=float)
        if np.linalg.norm(pts[0] - pts[-1]) < 1e-8:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        closed = np.vstack([pts, pts[0]])
        simp = approximate_polygon(closed, tolerance=SIMPLIFY_TOLERANCE_PX)
        if len(simp) > 1 and np.linalg.norm(simp[0] - simp[-1]) < 1e-8:
            simp = simp[:-1]
        if len(simp) >= 3:
            pts = simp
        rings.append(pts)
        paths.append(
            f'M {pts[0,0]:.3f},{pts[0,1]:.3f}'
            + ''.join(f' L {x:.3f},{y:.3f}' for x, y in pts[1:])
            + ' Z'
        )
    return paths, rings


def perimeter(pts: np.ndarray) -> float:
    return float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum())


def point_on_ring(pts: np.ndarray, frac: float):
    nxt = np.roll(pts, -1, axis=0)
    seg = np.linalg.norm(nxt - pts, axis=1)
    total = float(seg.sum())
    if total <= 0:
        return pts[0], 0.0, total
    target = frac * total
    cumulative = np.cumsum(seg)
    i = int(np.searchsorted(cumulative, target))
    i = min(i, len(pts) - 1)
    before = float(cumulative[i - 1]) if i else 0.0
    t = (target - before) / (float(seg[i]) + 1e-12)
    p = pts[i] * (1 - t) + nxt[i] * t
    v = nxt[i] - pts[i]
    ang = math.degrees(math.atan2(float(v[1]), float(v[0])))
    if ang > 90:
        ang -= 180
    elif ang < -90:
        ang += 180
    return p, ang, total


def boundary(mask: np.ndarray) -> np.ndarray:
    b = np.zeros_like(mask, dtype=bool)
    b[:-1] |= mask[:-1] != mask[1:]
    b[1:] |= mask[:-1] != mask[1:]
    b[:, :-1] |= mask[:, :-1] != mask[:, 1:]
    b[:, 1:] |= mask[:, :-1] != mask[:, 1:]
    return b


def symmetric_boundary_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ba, bb = boundary(a), boundary(b)
    if not ba.any() or not bb.any():
        return np.asarray([0.0])
    return np.concatenate([
        ndimage.distance_transform_edt(~bb)[ba],
        ndimage.distance_transform_edt(~ba)[bb],
    ])


def build_geometry(pal: np.ndarray, cls: np.ndarray):
    h, w = cls.shape
    fields = []
    masks = []
    ring_sets = []
    path_sets = []

    for k, sigma in enumerate(SIGMA_BY_THRESHOLD):
        field = smooth_field(cls >= k, sigma)
        mask = field_mask(field, h, w)
        paths, rings = field_paths(field)
        fields.append(field)
        masks.append(mask)
        path_sets.append(paths)
        ring_sets.append(rings)

    # Different depth-dependent sigmas are allowed only while the nested bathymetric
    # ordering is preserved exactly. Fail loudly if a future dataset breaks this.
    nested_violations = []
    for k in range(1, 8):
        n = int(np.sum(masks[k] & ~masks[k - 1]))
        nested_violations.append(n)
        if n:
            raise RuntimeError(f'nested contour violation at {k} m: {n} cells')

    fills = []
    lines = []
    labels = []
    label_count = 0
    layer_stats = []

    for k in range(8):
        color = '#%02x%02x%02x' % tuple(int(v) for v in pal[k])
        d = ' '.join(path_sets[k])
        fills.append(f'<path id="depth-fill-{k}" d="{d}" fill="{color}" fill-rule="evenodd"/>')
        layer_stats.append({
            'threshold_m': k,
            'sigma_px': SIGMA_BY_THRESHOLD[k],
            'rings': len(ring_sets[k]),
            'vertices': int(sum(len(r) for r in ring_sets[k])),
        })

        if k == 0:
            lines.append(
                f'<path id="shoreline" d="{d}" fill="none" stroke="#244e5a" '
                'stroke-opacity="0.62" stroke-width="0.72" stroke-linejoin="round" stroke-linecap="round"/>'
            )
            continue

        lines.append(
            f'<path id="isobath-{k}m" d="{d}" fill="none" stroke="#244e5a" '
            'stroke-opacity="0.48" stroke-width="0.62" stroke-linejoin="round" stroke-linecap="round"/>'
        )

        # Label at most two of the longest readable rings for each integer isobath.
        chosen = 0
        for ring in sorted(ring_sets[k], key=perimeter, reverse=True)[:8]:
            if perimeter(ring) < 180:
                continue
            frac = 0.46 if chosen == 0 else 0.72
            p, ang, _ = point_on_ring(ring, frac)
            x, y = float(p[0]), float(p[1])
            if not (15 < x < w - 15 and 15 < y < h - 15):
                continue
            labels.append(
                f'<text x="{x:.2f}" y="{y:.2f}" transform="rotate({ang:.1f} {x:.2f} {y:.2f})" '
                'text-anchor="middle" dominant-baseline="central" '
                'font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="8.4" font-weight="750" '
                'fill="#17343d" stroke="#ffffff" stroke-width="1.15" paint-order="stroke" stroke-opacity="0.92">'
                f'{k} m</text>'
            )
            label_count += 1
            chosen += 1
            if chosen >= 2:
                break

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        'shape-rendering="geometricPrecision">'
        '<title>Lac de Lacanau bathymetry — smooth integer isobaths</title>'
        '<desc>Official 1 m classes from corrected GeoPDF 4.1. Visual boundaries are extracted as '
        '0.5 iso-contours of depth-threshold occupancy fields after low-pass filtering. Integer-depth '
        'contour lines are drawn on top. GPS lookup remains the untouched corrected 4.1 classes.</desc>'
        '<g id="depth-bands">' + ''.join(fills) + '</g>'
        '<g id="depth-lines">' + ''.join(lines) + '</g>'
        '<g id="depth-labels" pointer-events="none">' + ''.join(labels) + '</g>'
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
        inter = int(np.sum(src & mask))
        union = int(np.sum(src | mask))
        dist = symmetric_boundary_distance(src, mask)
        thresholds.append({
            'threshold_m': k,
            'sigma_px': SIGMA_BY_THRESHOLD[k],
            'iou': float(inter / union),
            'area_ratio': float(np.sum(mask) / max(1, np.sum(src))),
            'boundary_p95_px': float(np.percentile(dist, 95)),
            'boundary_p99_px': float(np.percentile(dist, 99)),
            'source_components': int(ndimage.label(src)[1]),
            'smoothed_components': int(ndimage.label(mask)[1]),
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

    if water_iou < 0.997:
        raise RuntimeError(f'water mask QC failed: {water_iou}')
    if within1 < 0.999:
        raise RuntimeError(f'class-band QC failed: {within1}')
    if abs(mean_vector - mean_source) > 0.01:
        raise RuntimeError(f'mean depth QC failed: {mean_vector - mean_source}')
    for q in thresholds[:5]:
        if q['iou'] < 0.98 or q['boundary_p95_px'] > 2.1:
            raise RuntimeError(f'broad isobath QC failed: {q}')
    for q in thresholds[5:]:
        if q['iou'] < 0.97:
            raise RuntimeError(f'deep isobath QC failed: {q}')
    return report


def patch_ui():
    p = ROOT / 'hires.html'
    s = p.read_text()
    s = s.replace('Lacanautics Vector v4.3', 'Lacanautics Vector v4.4')
    s = s.replace('bathymetry-geopdf-v43-subpixel.svg?v=43', 'bathymetry-geopdf-v44-smooth.svg?v=44')
    s = s.replace('Vectorized corrected GeoPDF bathymetry', 'Smooth corrected GeoPDF bathymetry with integer isobaths')
    s = s.replace('VECTOR 4.3 · sub-pixel', 'VECTOR 4.4 · smooth isobaths')
    s = s.replace('<strong>VECTOR</strong><small>4.3</small>', '<strong>VECTOR</strong><small>4.4</small>')
    s = s.replace(
        'Vector 4.3: cartographic reconstruction from corrected 4.1. Raster staircases are collapsed within one native source pixel, then converted to bounded smooth curves; GPS still samples the unsmoothed 4.1 classes. Not a certified chart.',
        'Vector 4.4: smooth iso-contours reconstructed from the corrected 4.1 depth classes, with labelled 1 m depth lines. The visual low-pass filter removes raster/scallop frequency; GPS still samples the untouched 4.1 classes. Not a certified chart.'
    )
    s = s.replace(
        'The corrected GeoPDF 4.1 bathymetry is rendered as <b>cartographic SVG depth polygons</b>. Instead of preserving every raster step, each broad boundary is first simplified by at most one native pixel (~5.66 m), then rounded with a bounded curve pass. Small deep features receive much lighter treatment.',
        'The corrected GeoPDF 4.1 bathymetry is rendered as <b>smooth SVG iso-contours</b>. Each integer depth threshold is low-pass filtered before extracting its 0.5 contour, so the curve is reconstructed directly instead of rounding raster corners. The 1–7 m isobaths are drawn and labelled on top.'
    )
    s = s.replace('Vector 4.3 → corrected Raster 4.1 → Survey v3.1', 'Vector 4.4 → corrected Raster 4.1 → Survey v3.1')
    s = s.replace(
        'Source sampling ≈5.66 m/pixel; smoothing is visual/geometric within that source-cell uncertainty and does not change GPS depth lookup. Vertical definition remains the official 1 m bands.',
        'Source sampling ≈5.66 m/pixel. Broad visual contours use σ≈1.3 source pixels; deeper small zones use lighter smoothing. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.'
    )
    s = s.replace(
        "badge.textContent='VECTOR 4.3 · sub-pixel';warn.textContent='Vector 4.3: source-pixel staircases removed before bounded curve fitting; p95 displacement on broad 0–5 m bands is ≤1.5 native pixels. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.3</small>';meta.textContent='Sub-pixel SVG zones · source ~5.66 m/px'",
        "badge.textContent='VECTOR 4.4 · smooth isobaths';warn.textContent='Vector 4.4: Gaussian occupancy iso-contours remove the raster/scallop frequency and add labelled 1 m depth lines. GPS remains on exact corrected 4.1 classes. Tap VECTOR for raster 4.1, then v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.4</small>';meta.textContent='Smooth SVG bands + 1 m isobaths · source ~5.66 m/px'"
    )
    s = s.replace('then vector 4.2.', 'then vector 4.4.')
    s = s.replace('return to vector 4.2.', 'return to vector 4.4.')
    s = s.replace("mode==='vector'?'4.3 vector'", "mode==='vector'?'4.4 smooth vector'")

    # Add a legend key for the explicit contour lines once.
    if '1 m contours</div>' not in s:
        s = s.replace(
            '<div class="row"><i class="sw" style="background:#251c58"></i>7–8 m</div></div>',
            '<div class="row"><i class="sw" style="background:#251c58"></i>7–8 m</div>'
            '<div class="row"><i style="display:inline-block;width:16px;height:0;border-top:1.5px solid #244e5a;opacity:.7"></i>1 m contours</div></div>'
        )
    p.write_text(s)

    idx = ROOT / 'index.html'
    x = idx.read_text().replace('Vector v4.3', 'Vector v4.4').replace('v=43', 'v=44')
    idx.write_text(x)

    sw = ROOT / 'sw.js'
    w = sw.read_text()
    w = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.4-smooth-isobaths';", w)
    w = w.replace('./bathymetry-geopdf-v43-subpixel.svg', './bathymetry-geopdf-v44-smooth.svg')
    sw.write_text(w)

    manifest = ROOT / 'manifest.webmanifest'
    m = json.loads(manifest.read_text())
    m['description'] = 'Smooth corrected 2012 GeoPDF bathymetry with labelled 1 m isobaths, live GPS and raster/v3.1 comparison'
    manifest.write_text(json.dumps(m, ensure_ascii=False, separators=(',', ':')))


def main():
    meta, pal, cls = load_classes()
    svg, masks, layers, nested, label_count = build_geometry(pal, cls)
    q = qc(cls, masks)
    OUT_SVG.write_text(svg)
    report = {
        'version': '4.4-smooth-isobaths',
        'source_version': '4.1-fixed',
        'method': 'depth-threshold occupancy Gaussian low-pass -> 0.5 iso-contours; no corner-cut/Chaikin stage; explicit labelled integer isobaths',
        'sigma_by_threshold_px': SIGMA_BY_THRESHOLD,
        'source_resolution_m_per_px': meta['native_resolution_m_per_px'],
        'vertical_definition': 'official 1 m classes',
        'simplify_tolerance_px': SIMPLIFY_TOLERANCE_PX,
        'nested_violations': nested,
        'depth_label_count': label_count,
        'layers': layers,
        'svg_bytes': len(svg.encode()),
        'qc': q,
        'navigation_note': 'GPS lookup remains the exact corrected v4.1 class raster; v4.4 smoothing and contour lines are visual/cartographic only.',
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2))
    patch_ui()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

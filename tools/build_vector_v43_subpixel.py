#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import math
import re
from pathlib import Path

import cairosvg
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.measure import find_contours, approximate_polygon

ROOT = Path('.')
CLASS_IMAGE = ROOT / 'bathymetry-geopdf-v41-classes.webp'
NATIVE_IMAGE = ROOT / 'bathymetry-geopdf-v41-native.webp'
META_PATH = ROOT / 'data/lacanau_geopdf_v41.json'
OUT_SVG = ROOT / 'bathymetry-geopdf-v43-subpixel.svg'
OUT_REPORT = ROOT / 'data/lacanau_vector_v43_report.json'

# ArcMap/Aquabio colours measured from the native GeoPDF, before the prettier UI palette.
RAW_PALETTE = np.asarray([
    [182,237,240],[145,205,237],[107,174,232],[61,144,227],
    [32,114,214],[32,76,189],[25,44,168],[9,9,145]
], dtype=np.float32)


def load_data():
    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    cimg = np.asarray(Image.open(CLASS_IMAGE).convert('RGBA'))
    nimg = np.asarray(Image.open(NATIVE_IMAGE).convert('RGBA'))
    if cimg.shape != nimg.shape:
        raise RuntimeError(f'class/native image mismatch {cimg.shape} != {nimg.shape}')
    h, w = cimg.shape[:2]
    if (w, h) != (meta['width'], meta['height']):
        raise RuntimeError('image dimensions do not match v4.1 metadata')

    ui_palette = np.asarray(meta['palette_rgb'], dtype=np.int16)
    rgb = cimg[:, :, :3].astype(np.int16)
    alpha = cimg[:, :, 3]
    d = ((rgb[:, :, None, :] - ui_palette[None, None, :, :]) ** 2).sum(axis=3)
    cls = np.argmin(d, axis=2).astype(np.int8)
    water = alpha >= 128
    if np.any(np.min(d, axis=2)[water] != 0):
        raise RuntimeError('class mask is not exact lossless palette data')
    cls[~water] = -1
    return meta, ui_palette.astype(np.uint8), cls, nimg[:, :, :3].astype(np.float32), water


def boundary_pixels(mask):
    b = np.zeros_like(mask, dtype=bool)
    b[:-1, :] |= mask[:-1, :] != mask[1:, :]
    b[1:, :] |= mask[:-1, :] != mask[1:, :]
    b[:, :-1] |= mask[:, :-1] != mask[:, 1:]
    b[:, 1:] |= mask[:, :-1] != mask[:, 1:]
    return b


def pair_mix_probability(rgb, a, b):
    """Fraction from colour a toward colour b, projected onto the palette segment.

    This uses the anti-aliased/JPEG transition colours already present in the native
    GeoPDF rather than snapping every boundary back to the hard class pixels.
    """
    va = RAW_PALETTE[a]
    vb = RAW_PALETTE[b]
    v = vb - va
    den = float(np.dot(v, v))
    t = ((rgb - va) * v).sum(axis=2) / den
    return np.clip(t, 0.0, 1.0)


def build_fields(cls, native_rgb, water):
    fields = []

    # Shoreline: the class image has a hard alpha cut, so only apply a source-scale
    # uncertainty kernel. 0.62 px keeps displacement inside the native ~5.66 m cell.
    shore = ndimage.gaussian_filter(water.astype(np.float32), sigma=0.62, mode='constant', cval=0.0)
    fields.append(np.clip(shore, 0, 1))

    for k in range(1, 8):
        hard = (cls >= k).astype(np.float32)
        edge = boundary_pixels(hard > 0.5)
        band = ndimage.binary_dilation(edge, iterations=2)

        # Use the native colour mixture only near this specific class boundary.
        # Away from it, retain the exact hard class membership.
        p = pair_mix_probability(native_rgb, k - 1, k)
        q = hard.copy()
        q[band] = p[band]

        # Gentle regularization removes JPEG speckle and pixel staircases, while the
        # boundary location remains driven by the native transition colours.
        q = ndimage.gaussian_filter(q, sigma=0.42, mode='constant', cval=0.0)
        q = np.clip(q, 0, 1)
        fields.append(q)

    # The physical depth zones are cumulative/nested. Enforce this exactly so colour
    # noise can never make a deeper polygon leak outside a shallower polygon.
    for k in range(1, 8):
        fields[k] = np.minimum(fields[k], fields[k - 1])
    return fields


def contour_paths(field, tolerance=0.10):
    pad = 4
    f = np.pad(field.astype(np.float32), pad, mode='constant', constant_values=0.0)
    rings = find_contours(f, 0.5, fully_connected='high')
    ds = []
    raw_vertices = 0
    kept_vertices = 0
    for arr in rings:
        if len(arr) < 5:
            continue
        raw_vertices += len(arr)
        # Remove numerical wiggle well below one source pixel. This is geometry
        # compression, not smoothing; the scalar field above already defines the curve.
        arr2 = approximate_polygon(arr, tolerance=tolerance)
        if len(arr2) < 4:
            continue
        # find_contours coordinates refer to pixel centres. Convert to SVG pixel space.
        pts = [(float(c) - pad + 0.5, float(r) - pad + 0.5) for r, c in arr2]
        if math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1]) < 1e-8:
            pts.pop()
        if len(pts) < 3:
            continue
        kept_vertices += len(pts)
        d = f'M {pts[0][0]:.3f},{pts[0][1]:.3f}' + ''.join(
            f' L {x:.3f},{y:.3f}' for x, y in pts[1:]
        ) + ' Z'
        ds.append(d)
    return ds, raw_vertices, kept_vertices


def build_svg(palette, cls, native_rgb, water):
    h, w = cls.shape
    fields = build_fields(cls, native_rgb, water)
    layers = []
    stats = []
    for k, field in enumerate(fields):
        paths, raw_n, kept_n = contour_paths(field)
        color = '#%02x%02x%02x' % tuple(int(x) for x in palette[k])
        extra = ' stroke="#365e68" stroke-opacity="0.30" stroke-width="0.42"' if k == 0 else ''
        layers.append(
            f'<path id="depth-ge-{k}" d="{" ".join(paths)}" fill="{color}" fill-rule="evenodd"{extra}/>'
        )
        stats.append({
            'threshold_m': k,
            'rings': len(paths),
            'vertices_scalar_contour': raw_n,
            'vertices_after_0_10px_geometric_compression': kept_n,
        })

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="none" shape-rendering="geometricPrecision">'
        '<title>Lac de Lacanau bathymetry — sub-pixel vector reconstruction</title>'
        '<desc>Official 1 m depth bands reconstructed from corrected GeoPDF 4.1. '
        'Internal boundaries use native anti-aliased colour transitions plus a sub-pixel regularization constrained to the source raster uncertainty.</desc>'
        + ''.join(layers) + '</svg>'
    )
    return svg, stats, fields


def classify_render(arr, palette):
    rgb = arr[:, :, :3].astype(np.int16)
    p = palette.astype(np.int16)
    d = ((rgb[:, :, None, :] - p[None, None, :, :]) ** 2).sum(axis=3)
    return np.argmin(d, axis=2).astype(np.int8)


def mask_boundary(mask):
    return boundary_pixels(mask)


def boundary_distances(a, b):
    ba = mask_boundary(a)
    bb = mask_boundary(b)
    if not ba.any() or not bb.any():
        return []
    db = ndimage.distance_transform_edt(~bb)
    da = ndimage.distance_transform_edt(~ba)
    return np.concatenate([db[ba], da[bb]]).tolist()


def qc(svg, palette, cls):
    h, w = cls.shape
    png = cairosvg.svg2png(bytestring=svg.encode('utf-8'), output_width=w, output_height=h)
    arr = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
    rcls = classify_render(arr, palette)
    rwater = arr[:, :, 3] >= 128
    water = cls >= 0

    inter = int((rwater & water).sum())
    union = int((rwater | water).sum())
    water_iou = inter / union if union else 1.0

    # Deep interior must remain exactly unchanged despite the smoothed boundaries.
    boundary = boundary_pixels(cls)
    boundary = ndimage.binary_dilation(boundary, iterations=3)
    stable = water & rwater & ~boundary
    exact_stable = float((rcls[stable] == cls[stable]).mean()) if stable.any() else 1.0

    overlap = water & rwater
    exact_all = float((rcls[overlap] == cls[overlap]).mean()) if overlap.any() else 1.0
    within1 = float((np.abs(rcls[overlap] - cls[overlap]) <= 1).mean()) if overlap.any() else 1.0

    orig_counts = [int((cls == k).sum()) for k in range(8)]
    render_counts = [int((rwater & (rcls == k)).sum()) for k in range(8)]
    rel_area = [
        (render_counts[k]-orig_counts[k])/orig_counts[k] if orig_counts[k] else 0.0
        for k in range(8)
    ]
    mean_orig = float(np.mean(cls[water].astype(float)+0.5))
    mean_render = float(np.mean(rcls[rwater].astype(float)+0.5))

    all_d = []
    per_threshold = []
    for k in range(8):
        om = cls >= k
        rm = rwater & (rcls >= k)
        d = boundary_distances(om, rm)
        if d:
            all_d.extend(d)
            per_threshold.append({
                'threshold_m': k,
                'p95_boundary_displacement_px': float(np.percentile(d,95)),
                'max_boundary_displacement_px': float(np.max(d)),
            })

    report = {
        'water_mask_iou': water_iou,
        'stable_interior_exact_class_fraction': exact_stable,
        'all_overlap_exact_class_fraction': exact_all,
        'all_overlap_within_1m_fraction': within1,
        'relative_area_error_by_class': rel_area,
        'mean_depth_midpoint_original_m': mean_orig,
        'mean_depth_midpoint_vector_m': mean_render,
        'boundary_displacement_px': {
            'p50': float(np.percentile(all_d,50)),
            'p95': float(np.percentile(all_d,95)),
            'p99': float(np.percentile(all_d,99)),
            'max': float(np.max(all_d)),
            'per_threshold': per_threshold,
        },
    }

    if water_iou < 0.995:
        raise RuntimeError(f'water IoU failed: {water_iou:.6f}')
    if exact_stable < 0.9995:
        raise RuntimeError(f'interior class fidelity failed: {exact_stable:.6f}')
    if within1 < 0.995:
        raise RuntimeError(f'within-one-band fidelity failed: {within1:.6f}')
    if abs(mean_render-mean_orig) > 0.025:
        raise RuntimeError(f'mean depth shift too large: {mean_render:.4f} vs {mean_orig:.4f}')
    if report['boundary_displacement_px']['p95'] > 1.25:
        raise RuntimeError(f'boundary displacement too large: p95={report["boundary_displacement_px"]["p95"]:.3f}px')
    return report


def patch_ui():
    p = ROOT/'hires.html'
    s = p.read_text(encoding='utf-8')
    s = s.replace('<title>Lacanautics Vector v4.2</title>', '<title>Lacanautics Vector v4.3</title>')
    s = s.replace('bathymetry-geopdf-v42-zones.svg?v=42', 'bathymetry-geopdf-v43-subpixel.svg?v=43')
    s = s.replace('VECTOR 4.2 · GeoPDF', 'VECTOR 4.3 · sub-pixel')
    s = s.replace('<strong>VECTOR</strong><small>4.2</small>', '<strong>VECTOR</strong><small>4.3</small>')
    s = s.replace(
        'Vector 4.2: filled depth polygons derived from corrected GeoPDF 4.1 at exact half-pixel class boundaries; no smoothing or invented bathymetry. Tap VECTOR to compare raster 4.1, then v3.1. Not a certified chart.',
        'Vector 4.3: sub-pixel depth polygons reconstructed from native GeoPDF colour transitions. Pixel staircases are regularized inside the ~5.66 m source-cell uncertainty; GPS still samples the unsmoothed corrected 4.1 classes. Not a certified chart.'
    )
    s = s.replace('Lacanautics Vector v4.2', 'Lacanautics Vector v4.3')
    s = s.replace(
        'The corrected GeoPDF 4.1 bathymetry is now rendered as <b>filled SVG depth polygons</b>, not a raster image. The vector boundaries follow the source class mask at half-pixel resolution with no smoothing.',
        'The corrected GeoPDF 4.1 bathymetry is rendered as <b>sub-pixel SVG depth polygons</b>. Instead of tracing square raster cells, boundaries use the anti-aliased colour transitions already present in the native GeoPDF and are regularized only within one source-cell uncertainty.'
    )
    s = s.replace('Vector 4.2 → corrected Raster 4.1 → Survey v3.1', 'Vector 4.3 → corrected Raster 4.1 → Survey v3.1')
    s = s.replace('Source sampling ≈5.66 m/pixel; scalable vector rendering does not invent extra measurements.', 'Source sampling ≈5.66 m/pixel; smoothing is visual/geometric within that source-cell uncertainty and does not change GPS depth lookup.')
    s = s.replace("map.src='bathymetry-geopdf-v42-zones.svg?v=42'", "map.src='bathymetry-geopdf-v43-subpixel.svg?v=43'")
    s = s.replace("badge.textContent='VECTOR 4.2 · GeoPDF'", "badge.textContent='VECTOR 4.3 · sub-pixel'")
    s = s.replace("warn.textContent='Vector 4.2: filled polygons from corrected GeoPDF 4.1 half-pixel class boundaries; no smoothing. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'", "warn.textContent='Vector 4.3: sub-pixel polygons from native GeoPDF colour transitions; staircase regularization is constrained to source-pixel uncertainty. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'")
    s = s.replace("layerBtn.innerHTML='<strong>VECTOR</strong><small>4.2</small>'", "layerBtn.innerHTML='<strong>VECTOR</strong><small>4.3</small>'")
    s = s.replace("meta.textContent='Filled SVG zones · source ~5.66 m/px'", "meta.textContent='Sub-pixel SVG zones · source ~5.66 m/px'")
    s = s.replace("'4.2 vector'", "'4.3 vector'")
    s = s.replace("'4.2 depth '", "'4.3 depth '")
    p.write_text(s, encoding='utf-8')

    idx = (ROOT/'index.html').read_text(encoding='utf-8')
    idx = idx.replace('Vector v4.2', 'Vector v4.3').replace('hires.html?v=42','hires.html?v=43')
    (ROOT/'index.html').write_text(idx,encoding='utf-8')

    sw = (ROOT/'sw.js').read_text(encoding='utf-8')
    sw = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.3-subpixel';", sw)
    sw = sw.replace("'./bathymetry-geopdf-v42-zones.svg',", "'./bathymetry-geopdf-v43-subpixel.svg',")
    (ROOT/'sw.js').write_text(sw,encoding='utf-8')

    man = (ROOT/'manifest.webmanifest').read_text(encoding='utf-8')
    man = man.replace('filled vector GeoPDF bathymetry', 'sub-pixel vector GeoPDF bathymetry')
    (ROOT/'manifest.webmanifest').write_text(man,encoding='utf-8')


def main():
    meta, palette, cls, native_rgb, water = load_data()
    svg, layers, _fields = build_svg(palette, cls, native_rgb, water)
    q = qc(svg, palette, cls)
    OUT_SVG.write_text(svg,encoding='utf-8')
    report = {
        'version':'4.3-subpixel',
        'source_version':'4.1-fixed',
        'method':'native RGB transition projection + 0.42 px regularization for internal class boundaries; 0.62 px shoreline regularization; cumulative nesting enforced',
        'source_resolution_m_per_px':meta['native_resolution_m_per_px'],
        'vertical_definition':'official 1 m classes',
        'layers':layers,
        'svg_bytes':len(svg.encode('utf-8')),
        'qc':q,
        'navigation_note':'GPS depth lookup remains the unsmoothed corrected v4.1 class mask. v4.3 changes only the visual/vector boundary representation.'
    }
    OUT_REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8')
    patch_ui()
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()

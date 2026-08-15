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
from skimage.measure import find_contours

ROOT = Path('.')
CLASS_IMAGE = ROOT / 'bathymetry-geopdf-v41-classes.webp'
META_PATH = ROOT / 'data/lacanau_geopdf_v41.json'
OUT_SVG = ROOT / 'bathymetry-geopdf-v42-zones.svg'
OUT_REPORT = ROOT / 'data/lacanau_vector_v42_report.json'


def load_classes():
    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    im = np.asarray(Image.open(CLASS_IMAGE).convert('RGBA'))
    h, w = im.shape[:2]
    if (w, h) != (meta['width'], meta['height']):
        raise RuntimeError(f'class image size {(w,h)} != metadata {(meta["width"],meta["height"])}')
    palette = np.asarray(meta['palette_rgb'], dtype=np.int16)
    alpha = im[:, :, 3]
    rgb = im[:, :, :3].astype(np.int16)
    d = ((rgb[:, :, None, :] - palette[None, None, :, :]) ** 2).sum(axis=3)
    cls = np.argmin(d, axis=2).astype(np.int8)
    md = np.min(d, axis=2)
    water = alpha >= 128
    # The class WebP is lossless and should contain only exact palette colors on water.
    if np.any(md[water] != 0):
        raise RuntimeError(f'class image is not exact palette data: max squared RGB error {int(md[water].max())}')
    cls[~water] = -1
    return meta, palette.astype(np.uint8), cls


def cyclic_collinear_reduce(points):
    # points: list[(x,y)] closed conceptually, without duplicated end point.
    pts = list(points)
    if len(pts) < 4:
        return pts
    changed = True
    while changed and len(pts) >= 4:
        changed = False
        out = []
        n = len(pts)
        for i, b in enumerate(pts):
            a = pts[(i - 1) % n]
            c = pts[(i + 1) % n]
            abx, aby = b[0] - a[0], b[1] - a[1]
            bcx, bcy = c[0] - b[0], c[1] - b[1]
            cross = abx * bcy - aby * bcx
            dot = abx * bcx + aby * bcy
            if abs(cross) < 1e-12 and dot >= 0:
                changed = True
                continue
            out.append(b)
        pts = out
    return pts


def contour_paths(mask):
    # Padding guarantees closed rings even when the mapped water touches the image frame.
    padded = np.pad(mask.astype(np.uint8), 1, mode='constant', constant_values=0)
    rings = find_contours(padded, 0.5, fully_connected='high')
    ds = []
    vertices_raw = 0
    vertices_reduced = 0
    for arr in rings:
        if len(arr) < 4:
            continue
        # Original pixel centers are at SVG x+0.5/y+0.5. With a 1-pixel pad,
        # marching-squares coordinates map to SVG by subtracting 0.5.
        pts = [(float(c) - 0.5, float(r) - 0.5) for r, c in arr]
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
            pts.pop()
        vertices_raw += len(pts)
        pts = cyclic_collinear_reduce(pts)
        vertices_reduced += len(pts)
        if len(pts) < 3:
            continue
        # All coordinates are integer or half-integer; one decimal is lossless.
        d = f'M {pts[0][0]:.1f},{pts[0][1]:.1f}' + ''.join(
            f' L {x:.1f},{y:.1f}' for x, y in pts[1:]
        ) + ' Z'
        ds.append(d)
    return ds, vertices_raw, vertices_reduced


def build_svg(palette, cls):
    h, w = cls.shape
    layers = []
    stats = []
    # Cumulative filled zones eliminate cracks between adjacent depth classes:
    # base = all water, then >=1 m, >=2 m ... >=7 m overlays.
    for k in range(8):
        mask = cls >= k
        paths, raw_n, reduced_n = contour_paths(mask)
        color = '#%02x%02x%02x' % tuple(int(x) for x in palette[k])
        d = ' '.join(paths)
        extra = ''
        if k == 0:
            extra = ' stroke="#365e68" stroke-opacity="0.42" stroke-width="0.65"'
        layers.append(
            f'<path id="depth-ge-{k}" d="{d}" fill="{color}" fill-rule="evenodd"{extra}/>'
        )
        stats.append({
            'threshold_m': k,
            'rings': len(paths),
            'vertices_raw': raw_n,
            'vertices_after_exact_collinear_reduction': reduced_n,
        })
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'preserveAspectRatio="none" shape-rendering="geometricPrecision">'
        f'<title>Lac de Lacanau bathymetry — vectorized corrected GeoPDF 2012</title>'
        f'<desc>Eight official 1 metre depth classes vectorized from the corrected native GeoPDF class mask. '
        f'Geometry follows half-pixel marching-squares boundaries with only exact collinear point removal; no smoothing.</desc>'
        + ''.join(layers)
        + '</svg>'
    )
    return svg, stats


def classify_render(arr, palette):
    rgb = arr[:, :, :3].astype(np.int16)
    d = ((rgb[:, :, None, :] - palette.astype(np.int16)[None, None, :, :]) ** 2).sum(axis=3)
    return np.argmin(d, axis=2).astype(np.int8)


def qc_svg(svg, palette, cls):
    h, w = cls.shape
    png = cairosvg.svg2png(bytestring=svg.encode('utf-8'), output_width=w, output_height=h)
    rend = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
    rcls = classify_render(rend, palette)
    rwater = rend[:, :, 3] >= 128
    water = cls >= 0

    inter = int((rwater & water).sum())
    union = int((rwater | water).sum())
    water_iou = inter / union if union else 1.0

    # Ignore a 2-pixel neighbourhood of all class/shore boundaries for the strict
    # fidelity test; those pixels are intentionally anti-aliased by SVG renderers.
    boundary = np.zeros_like(water, dtype=bool)
    boundary[:-1, :] |= cls[:-1, :] != cls[1:, :]
    boundary[1:, :] |= cls[:-1, :] != cls[1:, :]
    boundary[:, :-1] |= cls[:, :-1] != cls[:, 1:]
    boundary[:, 1:] |= cls[:, :-1] != cls[:, 1:]
    boundary = ndimage.binary_dilation(boundary, iterations=2)
    stable = water & ~boundary & rwater
    exact_stable = float((rcls[stable] == cls[stable]).mean()) if stable.any() else 1.0

    overlap = water & rwater
    exact_all = float((rcls[overlap] == cls[overlap]).mean()) if overlap.any() else 1.0
    within1_all = float((np.abs(rcls[overlap] - cls[overlap]) <= 1).mean()) if overlap.any() else 1.0

    orig_counts = [int((cls == k).sum()) for k in range(8)]
    render_counts = [int((rwater & (rcls == k)).sum()) for k in range(8)]
    rel_area_error = [
        (render_counts[k] - orig_counts[k]) / orig_counts[k] if orig_counts[k] else 0.0
        for k in range(8)
    ]
    mean_orig = float(np.mean(cls[water].astype(float) + 0.5))
    mean_render = float(np.mean(rcls[rwater].astype(float) + 0.5))

    qc = {
        'water_mask_iou_at_alpha_128': water_iou,
        'stable_interior_pixels': int(stable.sum()),
        'stable_interior_exact_class_fraction': exact_stable,
        'all_overlap_exact_class_fraction': exact_all,
        'all_overlap_within_1m_fraction': within1_all,
        'original_class_pixels': orig_counts,
        'rendered_class_pixels_nearest_palette': render_counts,
        'relative_area_error_by_class': rel_area_error,
        'mean_depth_midpoint_original_m': mean_orig,
        'mean_depth_midpoint_vector_render_m': mean_render,
    }
    if water_iou < 0.995:
        raise RuntimeError(f'vector water geometry QC failed: IoU={water_iou:.6f}')
    if exact_stable < 0.999:
        raise RuntimeError(f'vector interior class QC failed: exact={exact_stable:.6f}')
    if abs(mean_render - mean_orig) > 0.015:
        raise RuntimeError(f'vector mean-depth QC failed: {mean_render:.4f} vs {mean_orig:.4f}')
    return qc


def patch_ui():
    p = ROOT / 'hires.html'
    s = p.read_text(encoding='utf-8')
    s = s.replace('<title>Lacanautics GeoPDF v4.1 fixed</title>', '<title>Lacanautics Vector v4.2</title>')
    s = s.replace('src="bathymetry-geopdf-v41-native.webp?v=411" alt="Corrected native GeoPDF bathymetry"',
                  'src="bathymetry-geopdf-v42-zones.svg?v=42" alt="Vectorized corrected GeoPDF bathymetry"')
    s = s.replace('GEOPDF 4.1 FIXED · native', 'VECTOR 4.2 · GeoPDF', 1)
    s = s.replace('<button id="layer" class="mini"><strong>4.1</strong><small>FIXED</small></button>',
                  '<button id="layer" class="mini"><strong>VECTOR</strong><small>4.2</small></button>')
    s = s.replace(
        'Corrected GeoPDF 4.1: native strips are vertically oriented per the PDF matrix and stitched with their 1-pixel overlaps removed. Exact GeoPDF georeferencing; 1 m bands @ 13.21 m NGF. Tap 4.1 to compare with v3.1. Not a certified chart.',
        'Vector 4.2: filled depth polygons derived from corrected GeoPDF 4.1 at exact half-pixel class boundaries; no smoothing or invented bathymetry. Tap VECTOR to compare raster 4.1, then v3.1. Not a certified chart.'
    )
    old_splash = '<div id="splash" class="splash"><div class="card"><h1>Lacanautics GeoPDF v4.1 fixed</h1><p>This rebuild fixes the broken strip assembly: each embedded ArcMap strip is vertically flipped exactly as the PDF placement matrix requires, and the five 1-pixel strip overlaps are stitched instead of duplicated.</p><p>The <b>4.1 / 3.1</b> button lets you compare the corrected native GeoPDF directly with the previous Survey v3.1 map.</p><button id="start">Open map + start GPS</button><small>Horizontal source sampling ≈5.66 m/pixel. Vertical definition remains the official 1 m bands.</small></div></div>'
    new_splash = '<div id="splash" class="splash"><div class="card"><h1>Lacanautics Vector v4.2</h1><p>The corrected GeoPDF 4.1 bathymetry is now rendered as <b>filled SVG depth polygons</b>, not a raster image. The vector boundaries follow the source class mask at half-pixel resolution with no smoothing.</p><p>Tap the <b>VECTOR</b> button to cycle through Vector 4.2 → corrected Raster 4.1 → Survey v3.1 for direct comparison.</p><button id="start">Open map + start GPS</button><small>Source sampling ≈5.66 m/pixel; scalable vector rendering does not invent extra measurements. Vertical definition remains the official 1 m bands.</small></div></div>'
    if old_splash not in s:
        raise RuntimeError('current v4.1 splash not found')
    s = s.replace(old_splash, new_splash)
    s = s.replace("mode='v41'", "mode='vector'", 1)

    start = s.index('function configure(){')
    end = s.index('\nPromise.all', start)
    new_config = """function configure(){if(mode==='vector'||mode==='raster'){B=v41.bbox;W=v41.width;H=v41.height;if(mode==='vector'){map.src='bathymetry-geopdf-v42-zones.svg?v=42';badge.textContent='VECTOR 4.2 · GeoPDF';warn.textContent='Vector 4.2: filled polygons from corrected GeoPDF 4.1 half-pixel class boundaries; no smoothing. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.2</small>';meta.textContent='Filled SVG zones · source ~5.66 m/px'}else{map.src='bathymetry-geopdf-v41-native.webp?v=42';badge.textContent='RASTER 4.1 · corrected';warn.textContent='Corrected native GeoPDF 4.1 raster: original source pixels with strip orientation and overlap stitching fixed. Tap RASTER for v3.1, then vector 4.2.';layerBtn.innerHTML='<strong>RASTER</strong><small>4.1</small>';meta.textContent='Corrected native GeoPDF · ~5.66 m/px'}}else{B=survey.bbox;W=1000;const lat0=(B.south+B.north)/2*Math.PI/180,widthM=(B.east-B.west)*111320*Math.cos(lat0),heightM=(B.north-B.south)*111320;H=Math.round(W*heightM/widthM);map.src='bathymetry-2012-v3.webp?v=42';badge.textContent='SURVEY v3.1 · previous';warn.textContent='Survey v3.1 comparison view. Tap 3.1 to return to vector 4.2.';layerBtn.innerHTML='<strong>3.1</strong><small>VIEW</small>';meta.textContent='Survey v3.1 comparison'}world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox',`0 0 ${W} ${H}`);points=[];line.setAttribute('points','');document.querySelectorAll('.poi').forEach(e=>{const p=ll(+e.dataset.lat,+e.dataset.lon);e.style.left=p.x+'px';e.style.top=p.y+'px'});ready=true;coord.textContent='GPS not started';fit()}"""
    s = s[:start] + new_config + s[end:]

    s = s.replace("const z=mode==='v41'?v41Sample(lat,lon):surveySample(lat,lon);",
                  "const z=mode==='v31'?surveySample(lat,lon):v41Sample(lat,lon);")
    s = s.replace("`${mode==='v41'?'4.1 GeoPDF':'3.1 survey'}:",
                  "`${mode==='vector'?'4.2 vector':mode==='raster'?'4.1 raster':'3.1 survey'}:")

    t0 = s.index('function toggleLayer(){')
    t1 = s.index("\n$('#plus').onclick", t0)
    toggle = "function toggleLayer(){mode=mode==='vector'?'raster':mode==='raster'?'v31':'vector';configure();if(last){const p=ll(last.coords.latitude,last.coords.longitude);me.style.left=p.x+'px';me.style.top=p.y+'px';updateDepth(last.coords.latitude,last.coords.longitude)}}"
    s = s[:t0] + toggle + s[t1:]
    s = s.replace("${mode==='v41'?'4.1 depth ':'3.1 depth '}${dv.textContent}",
                  "${mode==='vector'?'4.2 vector depth ':mode==='raster'?'4.1 raster depth ':'3.1 depth '}${dv.textContent}")
    p.write_text(s, encoding='utf-8')

    idx = (ROOT / 'index.html').read_text(encoding='utf-8')
    idx = idx.replace('Lacanautics GeoPDF v4.1 fixed', 'Lacanautics Vector v4.2').replace('GeoPDF v4.1 fixed', 'Vector v4.2')
    idx = re.sub(r'hires\.html\?v=\d+', 'hires.html?v=42', idx)
    (ROOT / 'index.html').write_text(idx, encoding='utf-8')

    swp = ROOT / 'sw.js'
    sw = swp.read_text(encoding='utf-8')
    sw = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.2-vector';", sw)
    sw = re.sub(
        r"const CORE=\[[^;]+;",
        "const CORE=['./','./index.html','./hires.html','./manifest.webmanifest','./bathymetry-geopdf-v42-zones.svg','./bathymetry-geopdf-v41-native.webp','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v3.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json'];",
        sw,
    )
    swp.write_text(sw, encoding='utf-8')

    mp = ROOT / 'manifest.webmanifest'
    man = mp.read_text(encoding='utf-8')
    man = re.sub(r'"description":"[^"]*"', '"description":"Vectorized corrected 2012 GeoPDF bathymetry with live GPS and raster/v3.1 comparison"', man)
    mp.write_text(man, encoding='utf-8')


def main():
    meta, palette, cls = load_classes()
    svg, layers = build_svg(palette, cls)
    OUT_SVG.write_text(svg, encoding='utf-8')
    qc = qc_svg(svg, palette, cls)
    report = {
        'version': '4.2-vector',
        'source_version': meta['version'],
        'source_class_image': CLASS_IMAGE.name,
        'source_resolution_px': [meta['width'], meta['height']],
        'source_resolution_m_per_px': meta.get('native_resolution_m_per_px'),
        'vertical_definition': meta.get('vertical_definition'),
        'vectorization': 'cumulative filled SVG polygons; marching squares at exact half-pixel boundaries; exact collinear point removal only; no smoothing',
        'layers': layers,
        'svg_bytes': OUT_SVG.stat().st_size,
        'qc': qc,
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    patch_ui()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

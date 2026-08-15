#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.interpolate import splprep, splev
from scipy.spatial import cKDTree
from shapely.geometry import LinearRing
from skimage.draw import polygon
from skimage.measure import approximate_polygon, find_contours

ROOT = Path(".")
CLASS_IMAGE = ROOT / "bathymetry-geopdf-v41-classes.webp"
META_PATH = ROOT / "data/lacanau_geopdf_v41.json"
OUT_SVG = ROOT / "bathymetry-geopdf-v45-faired.svg"
OUT_REPORT = ROOT / "data/lacanau_vector_v45_report.json"

# Keep the v4.4 raster-domain low pass: it removes the square-grid staircase without
# altering the GPS lookup. v4.5 adds a second, geometry-domain fairing stage.
SIGMA_BY_THRESHOLD = [1.30, 1.30, 1.30, 1.30, 1.30, 1.10, 0.90, 0.80]
SIMPLIFY_TOLERANCE_PX = 0.08
PAD = 8

# Maximum allowed bidirectional geometric displacement from the v4.4 iso-contour.
# One source pixel is ~=5.66 m. Broad contours may use most of that uncertainty;
# small deep features are protected more strongly.
MAX_DISP_BY_THRESHOLD_PX = [0.90, 0.90, 0.90, 0.85, 0.80, 0.68, 0.52, 0.38]
AREA_CHANGE_LIMIT_BY_THRESHOLD = [0.012, 0.012, 0.012, 0.012, 0.015, 0.018, 0.022, 0.030]
MIN_SPLINE_PERIMETER_PX = [36, 34, 32, 30, 28, 26, 24, 22]
RESAMPLE_SPACING_PX = 0.90
QC_SAMPLE_SPACING_PX = 0.45

# splprep's s is a sum of squared residuals. These candidate RMS residual levels
# are tried from weak to strong; the strongest geometry that remains inside the
# displacement / area / topology constraints wins.
SPLINE_RMS_CANDIDATES_PX = [0.10, 0.16, 0.24, 0.34, 0.48, 0.66, 0.88, 1.15, 1.45]
FAIRING_SCALE_TRIALS = [1.0, 0.78, 0.58, 0.40, 0.24]


def load_classes():
    meta = json.loads(META_PATH.read_text())
    im = np.asarray(Image.open(CLASS_IMAGE).convert("RGBA"))
    h, w = im.shape[:2]
    if (w, h) != (meta["width"], meta["height"]):
        raise RuntimeError("class image / metadata size mismatch")
    pal = np.asarray(meta["palette_rgb"], dtype=np.int16)
    rgb = im[:, :, :3].astype(np.int16)
    water = im[:, :, 3] >= 128
    d2 = ((rgb[:, :, None, :] - pal[None, None, :, :]) ** 2).sum(axis=3)
    cls = np.argmin(d2, axis=2).astype(np.int8)
    if np.any(np.min(d2, axis=2)[water] != 0):
        raise RuntimeError("class image is not exact palette data")
    cls[~water] = -1
    return meta, pal.astype(np.uint8), cls


def smooth_field(mask: np.ndarray, sigma: float) -> np.ndarray:
    padded = np.pad(mask.astype(np.float32), PAD, mode="constant", constant_values=0)
    return ndimage.gaussian_filter(padded, sigma=sigma, mode="constant", cval=0.0)


def clean_ring(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=float)
    if len(pts) < 3:
        return pts
    if np.linalg.norm(pts[0] - pts[-1]) < 1e-9:
        pts = pts[:-1]
    if len(pts) < 3:
        return pts
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9
    pts = pts[keep]
    if len(pts) > 2 and np.linalg.norm(pts[0] - pts[-1]) < 1e-9:
        pts = pts[:-1]
    return pts


def perimeter(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    return float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1).sum())


def signed_area(pts: np.ndarray) -> float:
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def resample_closed_ring(pts: np.ndarray, spacing: float) -> np.ndarray:
    pts = clean_ring(pts)
    if len(pts) < 3:
        return pts
    nxt = np.roll(pts, -1, axis=0)
    seg = np.linalg.norm(nxt - pts, axis=1)
    good = seg > 1e-10
    if not np.all(good):
        pts = pts[good]
        if len(pts) < 3:
            return pts
        nxt = np.roll(pts, -1, axis=0)
        seg = np.linalg.norm(nxt - pts, axis=1)
    total = float(seg.sum())
    n = max(8, int(math.ceil(total / max(spacing, 1e-4))))
    targets = np.linspace(0.0, total, n, endpoint=False)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    idx = np.searchsorted(cum[1:], targets, side="right")
    idx = np.minimum(idx, len(pts) - 1)
    local = (targets - cum[idx]) / (seg[idx] + 1e-15)
    return pts[idx] * (1.0 - local[:, None]) + nxt[idx] * local[:, None]


def linear_svg_path(pts: np.ndarray) -> str:
    pts = clean_ring(pts)
    if len(pts) < 3:
        return ""
    return (
        f"M {pts[0,0]:.3f},{pts[0,1]:.3f}"
        + "".join(f" L {x:.3f},{y:.3f}" for x, y in pts[1:])
        + " Z"
    )


def spline_svg_path(tck) -> str:
    t, _, k = tck
    if k != 3:
        raise RuntimeError("v4.5 expects cubic splines")
    knots = np.asarray(t, dtype=float)
    edges = knots[(knots >= -1e-10) & (knots <= 1.0 + 1e-10)]
    edges = np.unique(np.clip(np.concatenate([edges, [0.0, 1.0]]), 0.0, 1.0))
    edges.sort()
    p0 = np.asarray(splev(0.0, tck), dtype=float)
    out = [f"M {p0[0]:.3f},{p0[1]:.3f}"]
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < 1e-9:
            continue
        ca = np.asarray(splev(float(a), tck), dtype=float)
        cb = np.asarray(splev(float(b), tck), dtype=float)
        da = np.asarray(splev(float(a), tck, der=1), dtype=float)
        db = np.asarray(splev(float(b), tck, der=1), dtype=float)
        dt = float(b - a)
        c1 = ca + da * dt / 3.0
        c2 = cb - db * dt / 3.0
        out.append(
            f" C {c1[0]:.3f},{c1[1]:.3f} {c2[0]:.3f},{c2[1]:.3f} {cb[0]:.3f},{cb[1]:.3f}"
        )
    out.append(" Z")
    return "".join(out)


def bidirectional_distance(a: np.ndarray, b: np.ndarray):
    if len(a) < 2 or len(b) < 2:
        return 0.0, 0.0, 0.0
    da = cKDTree(b).query(a, k=1)[0]
    db = cKDTree(a).query(b, k=1)[0]
    d = np.concatenate([da, db])
    return float(np.max(d)), float(np.percentile(d, 95)), float(np.sqrt(np.mean(d * d)))


def fit_periodic_spline(pts: np.ndarray, threshold: int, fairing_scale: float):
    pts = clean_ring(pts)
    p = perimeter(pts)
    original_path = linear_svg_path(pts)
    base_stats = {
        "perimeter_px": p,
        "faired": False,
        "reason": "too-small",
        "max_displacement_px": 0.0,
        "p95_displacement_px": 0.0,
        "rms_displacement_px": 0.0,
        "area_change_fraction": 0.0,
        "spline_rms_target_px": None,
        "cubic_segments": 0,
    }
    if len(pts) < 8 or p < MIN_SPLINE_PERIMETER_PX[threshold]:
        return original_path, pts, base_stats

    src = resample_closed_ring(pts, RESAMPLE_SPACING_PX)
    if len(src) < 8:
        return original_path, pts, base_stats
    closed = np.vstack([src, src[0]])
    u = np.linspace(0.0, 1.0, len(closed))
    src_area = signed_area(src)
    allowed_disp = MAX_DISP_BY_THRESHOLD_PX[threshold] * fairing_scale
    allowed_area = AREA_CHANGE_LIMIT_BY_THRESHOLD[threshold] * max(0.65, fairing_scale)
    best = None

    for rms_target in SPLINE_RMS_CANDIDATES_PX:
        s = len(closed) * float(rms_target * fairing_scale) ** 2
        try:
            tck, _ = splprep(
                [closed[:, 0], closed[:, 1]],
                u=u,
                s=s,
                per=True,
                k=3,
            )
        except Exception:
            continue

        n_eval = max(64, int(math.ceil(p / QC_SAMPLE_SPACING_PX)))
        ue = np.linspace(0.0, 1.0, n_eval, endpoint=False)
        fit = np.column_stack(splev(ue, tck))
        if not np.all(np.isfinite(fit)):
            continue

        max_d, p95_d, rms_d = bidirectional_distance(src, fit)
        if max_d > allowed_disp + 0.06:
            continue

        fit_area = signed_area(fit)
        if src_area == 0.0 or fit_area == 0.0 or math.copysign(1.0, fit_area) != math.copysign(1.0, src_area):
            continue
        area_change = abs(fit_area - src_area) / max(abs(src_area), 20.0)
        if area_change > allowed_area:
            continue

        ring = LinearRing(np.vstack([fit, fit[0]]))
        if not ring.is_simple or not ring.is_valid:
            continue

        path = spline_svg_path(tck)
        cubic_segments = max(0, path.count(" C "))
        best = (
            path,
            fit,
            {
                "perimeter_px": p,
                "faired": True,
                "reason": "accepted",
                "max_displacement_px": max_d,
                "p95_displacement_px": p95_d,
                "rms_displacement_px": rms_d,
                "area_change_fraction": area_change,
                "spline_rms_target_px": float(rms_target * fairing_scale),
                "cubic_segments": cubic_segments,
            },
        )

    if best is None:
        base_stats["reason"] = "constraints"
        return original_path, pts, base_stats
    return best


def extract_source_rings(field: np.ndarray):
    contours = find_contours(field, 0.5, fully_connected="high")
    rings = []
    for arr in contours:
        if len(arr) < 4:
            continue
        pts = np.asarray([(float(c) - PAD, float(r) - PAD) for r, c in arr], dtype=float)
        pts = clean_ring(pts)
        if len(pts) < 3:
            continue
        closed = np.vstack([pts, pts[0]])
        simp = approximate_polygon(closed, tolerance=SIMPLIFY_TOLERANCE_PX)
        simp = clean_ring(simp)
        if len(simp) >= 3:
            pts = simp
        rings.append(pts)
    return rings


def rasterize_evenodd(rings, h: int, w: int) -> np.ndarray:
    out = np.zeros((h, w), dtype=bool)
    for pts in rings:
        pts = clean_ring(pts)
        if len(pts) < 3:
            continue
        rr, cc = polygon(pts[:, 1], pts[:, 0], shape=(h, w))
        tmp = np.zeros((h, w), dtype=bool)
        tmp[rr, cc] = True
        out ^= tmp
    return out


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
    return np.concatenate(
        [
            ndimage.distance_transform_edt(~bb)[ba],
            ndimage.distance_transform_edt(~ba)[bb],
        ]
    )


def build_trial(pal: np.ndarray, cls: np.ndarray, fairing_scale: float):
    h, w = cls.shape
    path_sets = []
    ring_sets = []
    masks = []
    stats_by_layer = []

    for k, sigma in enumerate(SIGMA_BY_THRESHOLD):
        field = smooth_field(cls >= k, sigma)
        source_rings = extract_source_rings(field)
        paths, rings, ring_stats = [], [], []
        for source_ring in source_rings:
            path, ring, stats = fit_periodic_spline(source_ring, k, fairing_scale)
            if path:
                paths.append(path)
                rings.append(ring)
                ring_stats.append(stats)
        path_sets.append(paths)
        ring_sets.append(rings)
        masks.append(rasterize_evenodd(rings, h, w))

        faired = [s for s in ring_stats if s["faired"]]
        stats_by_layer.append(
            {
                "threshold_m": k,
                "sigma_px": SIGMA_BY_THRESHOLD[k],
                "rings": len(rings),
                "faired_rings": len(faired),
                "linear_fallback_rings": len(rings) - len(faired),
                "source_vertices": int(sum(len(r) for r in source_rings)),
                "render_samples": int(sum(len(r) for r in rings)),
                "cubic_segments": int(sum(s["cubic_segments"] for s in faired)),
                "max_fairing_displacement_px": float(max((s["max_displacement_px"] for s in faired), default=0.0)),
                "max_p95_fairing_displacement_px": float(max((s["p95_displacement_px"] for s in faired), default=0.0)),
                "max_area_change_fraction": float(max((s["area_change_fraction"] for s in faired), default=0.0)),
            }
        )

    nested_violations = []
    for k in range(1, 8):
        n = int(np.sum(masks[k] & ~masks[k - 1]))
        nested_violations.append(n)

    return path_sets, ring_sets, masks, stats_by_layer, nested_violations


def build_svg(pal: np.ndarray, cls: np.ndarray, fairing_scale: float):
    h, w = cls.shape
    path_sets, ring_sets, masks, layer_stats, nested = build_trial(pal, cls, fairing_scale)
    fills, lines, labels = [], [], []
    label_count = 0

    for k in range(8):
        color = "#%02x%02x%02x" % tuple(int(v) for v in pal[k])
        d = " ".join(path_sets[k])
        fills.append(f'<path id="depth-fill-{k}" d="{d}" fill="{color}" fill-rule="evenodd"/>')
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
                f"{k} m</text>"
            )
            label_count += 1
            chosen += 1
            if chosen >= 2:
                break

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        'shape-rendering="geometricPrecision">'
        "<title>Lac de Lacanau bathymetry — fair periodic spline isobaths</title>"
        "<desc>Corrected GeoPDF 4.1 depth classes. v4.4 Gaussian occupancy iso-contours are "
        "reparameterized by arc length and faired with constrained periodic cubic B-splines. "
        "Fairing is bounded inside native source-cell uncertainty and topology/nesting are checked. "
        "GPS lookup remains the untouched corrected 4.1 classes.</desc>"
        '<g id="depth-bands">' + "".join(fills) + "</g>"
        '<g id="depth-lines">' + "".join(lines) + "</g>"
        '<g id="depth-labels" pointer-events="none">' + "".join(labels) + "</g>"
        "</svg>"
    )
    return svg, masks, layer_stats, nested, label_count


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
        thresholds.append(
            {
                "threshold_m": k,
                "sigma_px": SIGMA_BY_THRESHOLD[k],
                "iou": float(inter / union),
                "area_ratio": float(np.sum(mask) / max(1, np.sum(src))),
                "boundary_p95_px": float(np.percentile(dist, 95)),
                "boundary_p99_px": float(np.percentile(dist, 99)),
                "source_components": int(ndimage.label(src)[1]),
                "faired_components": int(ndimage.label(mask)[1]),
            }
        )

    report = {
        "water_mask_iou": water_iou,
        "all_overlap_exact_class_fraction": exact,
        "all_overlap_within_1m_fraction": within1,
        "mean_depth_midpoint_source_m": mean_source,
        "mean_depth_midpoint_vector_m": mean_vector,
        "mean_depth_shift_m": mean_vector - mean_source,
        "threshold_qc": thresholds,
    }

    if water_iou < 0.9965:
        raise RuntimeError(f"water mask QC failed: {water_iou}")
    if within1 < 0.9988:
        raise RuntimeError(f"class-band QC failed: {within1}")
    if abs(mean_vector - mean_source) > 0.015:
        raise RuntimeError(f"mean depth QC failed: {mean_vector - mean_source}")
    for q in thresholds[:5]:
        if q["iou"] < 0.978 or q["boundary_p95_px"] > 2.25:
            raise RuntimeError(f"broad isobath QC failed: {q}")
    for q in thresholds[5:]:
        if q["iou"] < 0.965:
            raise RuntimeError(f"deep isobath QC failed: {q}")
    return report


def patch_ui():
    p = ROOT / "hires.html"
    s = p.read_text()

    s = s.replace("Lacanautics Vector v4.4", "Lacanautics Vector v4.5")
    s = s.replace("bathymetry-geopdf-v44-smooth.svg?v=44", "bathymetry-geopdf-v45-faired.svg?v=45")
    s = s.replace("Smooth corrected GeoPDF bathymetry with integer isobaths", "Faired corrected GeoPDF bathymetry with integer isobaths")
    s = s.replace("VECTOR 4.4 · smooth isobaths", "VECTOR 4.5 · spline-faired")
    s = s.replace("<strong>VECTOR</strong><small>4.4</small>", "<strong>VECTOR</strong><small>4.5</small>")
    s = s.replace(
        "Vector 4.4: smooth iso-contours reconstructed from the corrected 4.1 depth classes, with labelled 1 m depth lines. The visual low-pass filter removes raster/scallop frequency; GPS still samples the untouched 4.1 classes. Not a certified chart.",
        "Vector 4.5: v4.4 iso-contours are arc-length resampled and faired with constrained periodic cubic B-splines. Short grid-frequency scallops are removed while displacement stays within source-cell uncertainty; GPS still samples untouched 4.1 classes. Not a certified chart.",
    )
    s = s.replace(
        "The corrected GeoPDF 4.1 bathymetry is rendered as <b>smooth SVG iso-contours</b>. Each integer depth threshold is low-pass filtered before extracting its 0.5 contour, so the curve is reconstructed directly instead of rounding raster corners. The 1–7 m isobaths are drawn and labelled on top.",
        "The corrected GeoPDF 4.1 bathymetry is rendered as <b>faired SVG iso-contours</b>. v4.4 first removes raster stair-steps in the occupancy field; v4.5 then resamples each closed contour by arc length and fits a constrained periodic cubic B-spline to suppress the remaining short scallop wavelength. The 1–7 m isobaths are drawn and labelled on top.",
    )
    s = s.replace("Vector 4.4 → corrected Raster 4.1 → Survey v3.1", "Vector 4.5 → corrected Raster 4.1 → Survey v3.1")
    s = s.replace(
        "Source sampling ≈5.66 m/pixel. Broad visual contours use σ≈1.3 source pixels; deeper small zones use lighter smoothing. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.",
        "Source sampling ≈5.66 m/pixel. Broad spline fairing is bounded to <0.9 source pixel from the v4.4 contour, with tighter limits in deep small zones. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.",
    )
    s = s.replace(
        "badge.textContent='VECTOR 4.4 · smooth isobaths';warn.textContent='Vector 4.4: Gaussian occupancy iso-contours remove the raster/scallop frequency and add labelled 1 m depth lines. GPS remains on exact corrected 4.1 classes. Tap VECTOR for raster 4.1, then v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.4</small>';meta.textContent='Smooth SVG bands + 1 m isobaths · source ~5.66 m/px'",
        "badge.textContent='VECTOR 4.5 · spline-faired';warn.textContent='Vector 4.5: constrained periodic cubic B-splines suppress residual grid-frequency scallops after the v4.4 Gaussian iso-contour stage. GPS remains on exact corrected 4.1 classes. Tap VECTOR for raster 4.1, then v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.5</small>';meta.textContent='Spline-faired SVG bands + 1 m isobaths · source ~5.66 m/px'",
    )
    s = s.replace("then vector 4.4.", "then vector 4.5.")
    s = s.replace("return to vector 4.4.", "return to vector 4.5.")
    s = s.replace("mode==='vector'?'4.4 smooth vector'", "mode==='vector'?'4.5 spline-faired vector'")
    p.write_text(s)

    idx = ROOT / "index.html"
    x = idx.read_text().replace("Vector v4.4", "Vector v4.5").replace("v=44", "v=45")
    idx.write_text(x)

    sw = ROOT / "sw.js"
    w = sw.read_text()
    w = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.5-spline-faired';", w)
    w = w.replace("./bathymetry-geopdf-v44-smooth.svg", "./bathymetry-geopdf-v45-faired.svg")
    sw.write_text(w)

    manifest = ROOT / "manifest.webmanifest"
    m = json.loads(manifest.read_text())
    m["description"] = "Spline-faired corrected 2012 GeoPDF bathymetry with labelled 1 m isobaths, live GPS and raster/v3.1 comparison"
    manifest.write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")))


def main():
    meta, pal, cls = load_classes()

    selected = None
    failures = []
    for fairing_scale in FAIRING_SCALE_TRIALS:
        svg, masks, layers, nested, label_count = build_svg(pal, cls, fairing_scale)
        if any(nested):
            failures.append({"fairing_scale": fairing_scale, "nested_violations": nested})
            continue
        try:
            q = qc(cls, masks)
        except RuntimeError as exc:
            failures.append({"fairing_scale": fairing_scale, "qc_error": str(exc)})
            continue
        selected = (fairing_scale, svg, masks, layers, nested, label_count, q)
        break

    if selected is None:
        raise RuntimeError(f"all fairing trials failed: {json.dumps(failures)}")

    fairing_scale, svg, masks, layers, nested, label_count, q = selected
    OUT_SVG.write_text(svg)
    report = {
        "version": "4.5-spline-faired",
        "source_version": "4.1-fixed",
        "parent_vector_version": "4.4-smooth-isobaths",
        "method": "Gaussian depth-threshold occupancy -> 0.5 iso-contours -> uniform arc-length resampling -> constrained periodic cubic smoothing B-splines -> exact SVG cubic Bezier spans",
        "sigma_by_threshold_px": SIGMA_BY_THRESHOLD,
        "max_displacement_by_threshold_px": MAX_DISP_BY_THRESHOLD_PX,
        "selected_fairing_scale": fairing_scale,
        "source_resolution_m_per_px": meta["native_resolution_m_per_px"],
        "vertical_definition": "official 1 m classes",
        "simplify_tolerance_px": SIMPLIFY_TOLERANCE_PX,
        "resample_spacing_px": RESAMPLE_SPACING_PX,
        "nested_violations": nested,
        "depth_label_count": label_count,
        "layers": layers,
        "svg_bytes": len(svg.encode()),
        "qc": q,
        "failed_stronger_trials": failures,
        "navigation_note": "GPS lookup remains the exact corrected v4.1 class raster; v4.5 spline fairing is visual/cartographic only.",
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2))
    patch_ui()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

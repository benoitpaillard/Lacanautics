#!/usr/bin/env python3
"""Arc-length spectral-style fairing for Lacanautics v4.5.

The v4.4 contour is uniformly resampled in arc length. A periodic 1-D Gaussian
low-pass is applied to x(s), y(s), then the faired ring is represented by a periodic
cubic spline. This directly damps the short grid/scallop wavelength while hard
geometry limits keep the curve inside source-cell uncertainty.
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy import ndimage
from scipy.interpolate import CubicSpline
from shapely.geometry import LinearRing

import build_vector_v45 as v

v.MIN_SPLINE_PERIMETER_PX = [42, 40, 38, 36, 34, 30, 27, 24]
v.RESAMPLE_SPACING_PX = 0.80
v.QC_SAMPLE_SPACING_PX = 0.50
v.FAIRING_SCALE_TRIALS = [1.0, 0.72, 0.50, 0.32]

# Physical sigma along the contour, in native source pixels. At sigma~1.3 px,
# a 4 px wavelength is attenuated to ~12%, while a 20 px feature remains ~92%.
BASE_ARCLENGTH_SIGMA_PX = [1.65, 1.65, 1.60, 1.50, 1.35, 1.10, 0.82, 0.60]
SIGMA_MULTIPLIERS = [1.0, 0.82, 0.66, 0.52, 0.40, 0.30, 0.22]
SVG_KNOT_SPACING_PX = 1.45


def cubic_svg_path(pts: np.ndarray) -> str:
    pts = v.resample_closed_ring(pts, SVG_KNOT_SPACING_PX)
    if len(pts) < 4:
        return v.linear_svg_path(pts)
    closed = np.vstack([pts, pts[0]])
    u = np.linspace(0.0, 1.0, len(closed))
    sx = CubicSpline(u, closed[:, 0], bc_type="periodic")
    sy = CubicSpline(u, closed[:, 1], bc_type="periodic")

    p0 = np.array([sx(0.0), sy(0.0)], dtype=float)
    out = [f"M {p0[0]:.3f},{p0[1]:.3f}"]
    for a, b in zip(u[:-1], u[1:]):
        h = float(b - a)
        pa = np.array([sx(a), sy(a)], dtype=float)
        pb = np.array([sx(b), sy(b)], dtype=float)
        da = np.array([sx(a, 1), sy(a, 1)], dtype=float)
        db = np.array([sx(b, 1), sy(b, 1)], dtype=float)
        c1 = pa + da * h / 3.0
        c2 = pb - db * h / 3.0
        out.append(
            f" C {c1[0]:.3f},{c1[1]:.3f} {c2[0]:.3f},{c2[1]:.3f} {pb[0]:.3f},{pb[1]:.3f}"
        )
    out.append(" Z")
    return "".join(out)


def fit_periodic_lowpass(pts: np.ndarray, threshold: int, fairing_scale: float):
    pts = v.clean_ring(pts)
    p = v.perimeter(pts)
    original_path = v.linear_svg_path(pts)
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
    if len(pts) < 8 or p < v.MIN_SPLINE_PERIMETER_PX[threshold]:
        return original_path, pts, base_stats

    src = v.resample_closed_ring(pts, v.RESAMPLE_SPACING_PX)
    if len(src) < 8:
        return original_path, pts, base_stats

    src_area = v.signed_area(src)
    allowed_disp = v.MAX_DISP_BY_THRESHOLD_PX[threshold] * fairing_scale
    allowed_area = v.AREA_CHANGE_LIMIT_BY_THRESHOLD[threshold] * max(0.65, fairing_scale)
    base_sigma = BASE_ARCLENGTH_SIGMA_PX[threshold] * fairing_scale

    for mult in SIGMA_MULTIPLIERS:
        sigma_px = base_sigma * mult
        sigma_samples = sigma_px / v.RESAMPLE_SPACING_PX
        fit = np.column_stack(
            [
                ndimage.gaussian_filter1d(src[:, 0], sigma_samples, mode="wrap"),
                ndimage.gaussian_filter1d(src[:, 1], sigma_samples, mode="wrap"),
            ]
        )
        max_d, p95_d, rms_d = v.bidirectional_distance(src, fit)
        if max_d > allowed_disp + 0.05:
            continue

        fit_area = v.signed_area(fit)
        if src_area == 0.0 or fit_area == 0.0:
            continue
        if math.copysign(1.0, fit_area) != math.copysign(1.0, src_area):
            continue
        area_change = abs(fit_area - src_area) / max(abs(src_area), 20.0)
        if area_change > allowed_area:
            continue

        ring = LinearRing(np.vstack([fit, fit[0]]))
        if not ring.is_simple or not ring.is_valid:
            continue

        path = cubic_svg_path(fit)
        return (
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
                "spline_rms_target_px": sigma_px,
                "cubic_segments": path.count(" C "),
            },
        )

    base_stats["reason"] = "constraints"
    return original_path, pts, base_stats


v.fit_periodic_spline = fit_periodic_lowpass

if __name__ == "__main__":
    v.main()
    report = json.loads(v.OUT_REPORT.read_text())
    report["method"] = (
        "Gaussian depth-threshold occupancy -> 0.5 iso-contours -> uniform arc-length "
        "resampling -> periodic Gaussian low-pass of x(s),y(s) targeting grid/scallop "
        "wavelength -> periodic cubic spline / exact SVG cubic Bezier spans"
    )
    report["fairing_filter"] = {
        "type": "periodic Gaussian low-pass in contour arc length",
        "base_sigma_by_threshold_px": BASE_ARCLENGTH_SIGMA_PX,
        "sigma_multipliers": SIGMA_MULTIPLIERS,
        "svg_knot_spacing_px": SVG_KNOT_SPACING_PX,
        "interpretation": "sigma~1.3 px attenuates a 4 px wavelength to about 12% while preserving about 92% of a 20 px wavelength",
    }
    v.OUT_REPORT.write_text(json.dumps(report, indent=2))

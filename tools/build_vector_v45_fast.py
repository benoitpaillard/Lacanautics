#!/usr/bin/env python3
"""Fast constrained spline search for Lacanautics v4.5.

Keeps the full v4.5 geometry/QC implementation in build_vector_v45.py, but replaces
the expensive exhaustive spline-strength scan with a strongest-first bounded search.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.interpolate import splprep, splev
from shapely.geometry import LinearRing

import build_vector_v45 as v

v.MIN_SPLINE_PERIMETER_PX = [50, 48, 45, 42, 38, 34, 30, 26]
v.RESAMPLE_SPACING_PX = 1.25
v.QC_SAMPLE_SPACING_PX = 0.65
v.SPLINE_RMS_CANDIDATES_PX = [1.30, 0.95, 0.70, 0.50, 0.34, 0.22, 0.14]
v.FAIRING_SCALE_TRIALS = [1.0, 0.70, 0.45, 0.28]


def fit_periodic_spline_fast(pts: np.ndarray, threshold: int, fairing_scale: float):
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
    closed = np.vstack([src, src[0]])
    u = np.linspace(0.0, 1.0, len(closed))
    src_area = v.signed_area(src)
    allowed_disp = v.MAX_DISP_BY_THRESHOLD_PX[threshold] * fairing_scale
    allowed_area = v.AREA_CHANGE_LIMIT_BY_THRESHOLD[threshold] * max(0.65, fairing_scale)

    # Strongest-first: accept the first spline satisfying all hard geometry limits.
    for rms_target in v.SPLINE_RMS_CANDIDATES_PX:
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

        n_eval = max(64, int(math.ceil(p / v.QC_SAMPLE_SPACING_PX)))
        ue = np.linspace(0.0, 1.0, n_eval, endpoint=False)
        fit = np.column_stack(splev(ue, tck))
        if not np.all(np.isfinite(fit)):
            continue

        max_d, p95_d, rms_d = v.bidirectional_distance(src, fit)
        if max_d > allowed_disp + 0.06:
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

        path = v.spline_svg_path(tck)
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
                "spline_rms_target_px": float(rms_target * fairing_scale),
                "cubic_segments": path.count(" C "),
            },
        )

    base_stats["reason"] = "constraints"
    return original_path, pts, base_stats


v.fit_periodic_spline = fit_periodic_spline_fast

if __name__ == "__main__":
    v.main()

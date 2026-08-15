#!/usr/bin/env python3
"""Run one v4.5 fairing-strength probe for fast CI tuning."""
import json
import sys

sys.path.insert(0, "tools")
import build_vector_v45_lowpass as m

PROBE_SCALE = 0.40
m.v.FAIRING_SCALE_TRIALS = [PROBE_SCALE]
m.v.fit_periodic_spline = m.fit_periodic_lowpass
m.v.main()

report = json.loads(m.v.OUT_REPORT.read_text())
report["method"] = (
    "Gaussian depth-threshold occupancy -> 0.5 iso-contours -> uniform arc-length "
    "resampling -> periodic Gaussian low-pass of x(s),y(s) targeting grid/scallop "
    "wavelength -> periodic cubic spline / exact SVG cubic Bezier spans"
)
report["fairing_filter"] = {
    "type": "periodic Gaussian low-pass in contour arc length",
    "base_sigma_by_threshold_px": m.BASE_ARCLENGTH_SIGMA_PX,
    "sigma_multipliers": m.SIGMA_MULTIPLIERS,
    "svg_knot_spacing_px": m.SVG_KNOT_SPACING_PX,
    "hard_displacement_limits_px": m.v.MAX_DISP_BY_THRESHOLD_PX,
    "probe_scale": PROBE_SCALE,
    "interpretation": "sigma~1.3 px attenuates a 4 px wavelength to about 12% while preserving about 92% of a 20 px wavelength",
}
m.v.OUT_REPORT.write_text(json.dumps(report, indent=2))
